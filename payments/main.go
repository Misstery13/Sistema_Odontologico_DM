// Microservicio de facturación y caja: registra cobros contra el saldo de tratamientos del paciente,
// emite el comprobante (adaptador SRI simulado) y lleva el cierre de caja ciego (RN-02).
// Comparte PostgreSQL con Django (lee tokens, usuarios, pacientes y tratamientos) y usa Redis
// para cachear la resolución token -> sesión.
package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

// App agrupa las dependencias; se inyectan en main y los handlers las usan vía receptor.
type App struct {
	db  *pgxpool.Pool
	rdb *redis.Client
}

type Payment struct {
	ID        int64     `json:"id"`
	Amount    float64   `json:"amount"`
	Method    string    `json:"method"`
	Invoice   string    `json:"invoice_number"`
	CreatedAt time.Time `json:"created_at"`
}

type session struct{ user, clinic int64; role string }

// querier lo cumplen tanto el pool como una transacción.
type querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

var methods = map[string]bool{"efectivo": true, "tarjeta": true, "transferencia": true, "seguro": true}

// RBAC (RNF-05), igual criterio que Django: la recepción cobra y cierra caja; auditoría solo lee.
var (
	readers  = []string{"recepcion", "odontologo", "asistente", "auditor"}
	cashiers = []string{"recepcion"}
	auditors = []string{"admin", "auditor"}
)

const idleMinutes = 15

// issueInvoice emite el comprobante electrónico.
// ponytail: adaptador simulado (solo log); conectar aquí la API de facturación electrónica del SRI.
var issueInvoice = func(p Payment, clinic int64) string {
	n := fmt.Sprintf("001-001-%09d", p.ID)
	log.Printf("[SRI simulado] clínica %d comprobante %s por %.2f (%s)", clinic, n, p.Amount, p.Method)
	return n
}

func main() {
	ctx := context.Background()
	db, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		log.Fatal(err)
	}
	for _, stmt := range []string{
		`CREATE TABLE IF NOT EXISTS payments (
			id BIGSERIAL PRIMARY KEY,
			clinic_id BIGINT NOT NULL,
			patient_id BIGINT NOT NULL,
			amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
			method TEXT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now())`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_number TEXT NOT NULL DEFAULT ''`,
		`CREATE INDEX IF NOT EXISTS payments_patient_idx ON payments (clinic_id, patient_id)`,
		`CREATE TABLE IF NOT EXISTS cash_closings (
			id BIGSERIAL PRIMARY KEY,
			clinic_id BIGINT NOT NULL,
			user_id BIGINT NOT NULL,
			day DATE NOT NULL,
			counted_cents BIGINT NOT NULL CHECK (counted_cents >= 0),
			expected_cents BIGINT NOT NULL,
			created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
			UNIQUE (clinic_id, day))`,
	} {
		if _, err := db.Exec(ctx, stmt); err != nil {
			log.Fatal(err)
		}
	}
	opt, err := redis.ParseURL(os.Getenv("REDIS_URL"))
	if err != nil {
		log.Fatal(err)
	}
	app := &App{db: db, rdb: redis.NewClient(opt)}

	f := fiber.New()
	api := f.Group("/pay", app.auth)
	api.Get("/patients/:id/balance", allow(readers), app.balance)
	api.Get("/patients/:id/payments", allow(readers), app.listPayments)
	api.Post("/payments", allow(cashiers), app.createPayment)
	api.Post("/cash-closings", allow(cashiers), app.closeCash)
	api.Get("/cash-closings", allow(auditors), app.listClosings)
	api.Get("/reports/income", allow(auditors), app.income)
	log.Fatal(f.Listen(":8080"))
}

func fail(c *fiber.Ctx, status int, msg string) error {
	return c.Status(status).JSON(fiber.Map{"detail": msg})
}

func sess(c *fiber.Ctx) session { return c.Locals("session").(session) }

func allow(roles []string) fiber.Handler {
	return func(c *fiber.Ctx) error {
		if !slices.Contains(roles, sess(c).role) {
			return fail(c, 403, "No tienes permiso para esta acción")
		}
		return c.Next()
	}
}

// auth valida el token de Django (incluida la inactividad de 15 min) y guarda la sesión en Locals.
func (a *App) auth(c *fiber.Ctx) error {
	key, ok := strings.CutPrefix(c.Get("Authorization"), "Token ")
	if !ok || key == "" {
		return fail(c, 401, "Token requerido")
	}
	ctx := c.Context()
	var s session
	if parts := strings.SplitN(a.rdb.Get(ctx, "tok:"+key).Val(), ":", 3); len(parts) == 3 {
		s.user, _ = strconv.ParseInt(parts[0], 10, 64)
		s.clinic, _ = strconv.ParseInt(parts[1], 10, 64)
		s.role = parts[2]
	} else { // no está en caché (o Redis caído): ir a la base y contar esta petición como actividad
		err := a.db.QueryRow(ctx, `
			UPDATE clinica_user u SET last_activity = now() FROM authtoken_token t
			WHERE t.key = $1 AND u.id = t.user_id AND u.is_active AND u.clinic_id IS NOT NULL
			  AND u.last_activity > now() - make_interval(mins => $2)
			RETURNING u.id, u.clinic_id, u.role`, key, idleMinutes).Scan(&s.user, &s.clinic, &s.role)
		if err != nil {
			return fail(c, 401, "Sesión inválida o cerrada por inactividad")
		}
		// TTL corto: una sesión vencida en Django deja de valer aquí en menos de un minuto
		a.rdb.Set(ctx, "tok:"+key, fmt.Sprintf("%d:%d:%s", s.user, s.clinic, s.role), time.Minute)
	}
	c.Locals("session", s)
	return c.Next()
}

func balanceCents(ctx context.Context, q querier, clinic, patient int64) (int64, error) {
	var b int64
	err := q.QueryRow(ctx, `SELECT
		(SELECT COALESCE(SUM(cost), 0) * 100 FROM clinica_treatment WHERE clinic_id = $1 AND patient_id = $2)::bigint -
		(SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE clinic_id = $1 AND patient_id = $2)::bigint`,
		clinic, patient).Scan(&b)
	return b, err
}

func (a *App) ownsPatient(ctx context.Context, clinic, patient int64) bool {
	var ok bool
	a.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM clinica_patient WHERE id = $1 AND clinic_id = $2)`,
		patient, clinic).Scan(&ok)
	return ok
}

func (a *App) balance(c *fiber.Ctx) error {
	clinic := sess(c).clinic
	pid, err := c.ParamsInt("id")
	if err != nil || !a.ownsPatient(c.Context(), clinic, int64(pid)) {
		return fail(c, 404, "Paciente no encontrado")
	}
	b, err := balanceCents(c.Context(), a.db, clinic, int64(pid))
	if err != nil {
		return err
	}
	return c.JSON(fiber.Map{"balance": float64(b) / 100})
}

func (a *App) listPayments(c *fiber.Ctx) error {
	pid, err := c.ParamsInt("id")
	if err != nil {
		return fail(c, 404, "Paciente no encontrado")
	}
	rows, err := a.db.Query(c.Context(), `SELECT id, amount_cents, method, invoice_number, created_at FROM payments
		WHERE clinic_id = $1 AND patient_id = $2 ORDER BY created_at DESC`, sess(c).clinic, pid)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []Payment{}
	for rows.Next() {
		var p Payment
		var cents int64
		if err := rows.Scan(&p.ID, &cents, &p.Method, &p.Invoice, &p.CreatedAt); err != nil {
			return err
		}
		p.Amount = float64(cents) / 100
		out = append(out, p)
	}
	return c.JSON(out)
}

func parseCents(v float64) int64 { return int64(math.Round(v * 100)) }

func (a *App) createPayment(c *fiber.Ctx) error {
	clinic := sess(c).clinic
	var in struct {
		PatientID int64   `json:"patient_id"`
		Amount    float64 `json:"amount"`
		Method    string  `json:"method"`
	}
	if err := c.BodyParser(&in); err != nil {
		return fail(c, 400, "JSON inválido")
	}
	cents := parseCents(in.Amount)
	if cents <= 0 {
		return fail(c, 400, "El monto debe ser mayor a 0")
	}
	if !methods[in.Method] {
		return fail(c, 400, "Método de pago inválido")
	}

	ctx := c.Context()
	tx, err := a.db.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	// FOR UPDATE bloquea al paciente: dos cobros simultáneos no pueden sobrepasar el saldo.
	var id int64
	err = tx.QueryRow(ctx, `SELECT id FROM clinica_patient WHERE id = $1 AND clinic_id = $2 FOR UPDATE`,
		in.PatientID, clinic).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return fail(c, 404, "Paciente no encontrado")
	} else if err != nil {
		return err
	}
	bal, err := balanceCents(ctx, tx, clinic, in.PatientID)
	if err != nil {
		return err
	}
	if cents > bal {
		return fail(c, 422, "El monto excede el saldo pendiente")
	}
	p := Payment{Amount: float64(cents) / 100, Method: in.Method}
	err = tx.QueryRow(ctx, `INSERT INTO payments (clinic_id, patient_id, amount_cents, method)
		VALUES ($1, $2, $3, $4) RETURNING id, created_at`, clinic, in.PatientID, cents, in.Method).Scan(&p.ID, &p.CreatedAt)
	if err != nil {
		return err
	}
	p.Invoice = issueInvoice(p, clinic)
	if _, err := tx.Exec(ctx, `UPDATE payments SET invoice_number = $1 WHERE id = $2`, p.Invoice, p.ID); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	return c.Status(201).JSON(p)
}

// closeCash registra el conteo físico del efectivo del día. RN-02: el total teórico solo se revela
// después de guardar el conteo; no existe otro endpoint que lo muestre a la recepción.
func (a *App) closeCash(c *fiber.Ctx) error {
	s := sess(c)
	var in struct {
		Counted float64 `json:"counted"`
	}
	if err := c.BodyParser(&in); err != nil || in.Counted < 0 {
		return fail(c, 400, "Ingresa el efectivo contado")
	}
	var day time.Time
	var expected int64
	err := a.db.QueryRow(c.Context(), `
		INSERT INTO cash_closings (clinic_id, user_id, day, counted_cents, expected_cents)
		SELECT $1, $2, d, $3, (SELECT COALESCE(SUM(amount_cents), 0) FROM payments
			WHERE clinic_id = $1 AND method = 'efectivo' AND (created_at AT TIME ZONE 'America/Guayaquil')::date = d)
		FROM (SELECT (now() AT TIME ZONE 'America/Guayaquil')::date AS d) t
		ON CONFLICT (clinic_id, day) DO NOTHING
		RETURNING day, expected_cents`, s.clinic, s.user, parseCents(in.Counted)).Scan(&day, &expected)
	if errors.Is(err, pgx.ErrNoRows) {
		return fail(c, 409, "La caja de hoy ya fue cerrada")
	} else if err != nil {
		return err
	}
	counted := parseCents(in.Counted)
	return c.Status(201).JSON(fiber.Map{
		"day": day.Format("2006-01-02"), "counted": float64(counted) / 100,
		"expected": float64(expected) / 100, "difference": float64(counted-expected) / 100,
	})
}

func (a *App) listClosings(c *fiber.Ctx) error {
	rows, err := a.db.Query(c.Context(), `SELECT k.day, k.counted_cents, k.expected_cents,
		COALESCE(NULLIF(u.first_name || ' ' || u.last_name, ' '), u.username)
		FROM cash_closings k JOIN clinica_user u ON u.id = k.user_id
		WHERE k.clinic_id = $1 ORDER BY k.day DESC LIMIT 60`, sess(c).clinic)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []fiber.Map{}
	for rows.Next() {
		var day time.Time
		var counted, expected int64
		var user string
		if err := rows.Scan(&day, &counted, &expected, &user); err != nil {
			return err
		}
		out = append(out, fiber.Map{"day": day.Format("2006-01-02"), "counted": float64(counted) / 100,
			"expected": float64(expected) / 100, "difference": float64(counted-expected) / 100, "user": user})
	}
	return c.JSON(out)
}

// income resume lo cobrado en el período por método de pago (reportes de gestión).
func (a *App) income(c *fiber.Ctx) error {
	from, to := c.Query("from"), c.Query("to")
	if _, err := time.Parse("2006-01-02", from); err != nil {
		return fail(c, 400, "Indica el rango ?from=AAAA-MM-DD&to=AAAA-MM-DD")
	}
	if _, err := time.Parse("2006-01-02", to); err != nil {
		return fail(c, 400, "Indica el rango ?from=AAAA-MM-DD&to=AAAA-MM-DD")
	}
	rows, err := a.db.Query(c.Context(), `SELECT method, COUNT(*), SUM(amount_cents) FROM payments
		WHERE clinic_id = $1 AND (created_at AT TIME ZONE 'America/Guayaquil')::date BETWEEN $2::date AND $3::date
		GROUP BY method ORDER BY SUM(amount_cents) DESC`, sess(c).clinic, from, to)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []fiber.Map{}
	for rows.Next() {
		var method string
		var count, cents int64
		if err := rows.Scan(&method, &count, &cents); err != nil {
			return err
		}
		out = append(out, fiber.Map{"method": method, "count": count, "amount": float64(cents) / 100})
	}
	return c.JSON(out)
}
