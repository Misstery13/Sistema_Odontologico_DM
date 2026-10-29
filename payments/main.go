// Microservicio de pagos: registra cobros contra el saldo de tratamientos del paciente.
// Comparte PostgreSQL con Django (lee tokens, pacientes y tratamientos) y usa Redis
// para cachear la resolución token -> clínica.
package main

import (
	"context"
	"errors"
	"log"
	"math"
	"os"
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
	CreatedAt time.Time `json:"created_at"`
}

// querier lo cumplen tanto el pool como una transacción.
type querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

var methods = map[string]bool{"efectivo": true, "tarjeta": true, "transferencia": true}

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
		`CREATE INDEX IF NOT EXISTS payments_patient_idx ON payments (clinic_id, patient_id)`,
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
	api.Get("/patients/:id/balance", app.balance)
	api.Get("/patients/:id/payments", app.listPayments)
	api.Post("/payments", app.createPayment)
	log.Fatal(f.Listen(":8080"))
}

func fail(c *fiber.Ctx, status int, msg string) error {
	return c.Status(status).JSON(fiber.Map{"detail": msg})
}

// auth valida el token de Django y guarda la clínica del usuario en Locals.
func (a *App) auth(c *fiber.Ctx) error {
	key, ok := strings.CutPrefix(c.Get("Authorization"), "Token ")
	if !ok || key == "" {
		return fail(c, 401, "Token requerido")
	}
	ctx := c.Context()
	clinic, err := a.rdb.Get(ctx, "tok:"+key).Int64()
	if err != nil { // no está en caché (o Redis caído): ir a la base
		err = a.db.QueryRow(ctx, `
			SELECT u.clinic_id FROM authtoken_token t JOIN clinica_user u ON u.id = t.user_id
			WHERE t.key = $1 AND u.is_active AND u.clinic_id IS NOT NULL`, key).Scan(&clinic)
		if err != nil {
			return fail(c, 401, "Token inválido")
		}
		a.rdb.Set(ctx, "tok:"+key, clinic, 5*time.Minute)
	}
	c.Locals("clinic", clinic)
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
	clinic := c.Locals("clinic").(int64)
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
	clinic := c.Locals("clinic").(int64)
	pid, err := c.ParamsInt("id")
	if err != nil {
		return fail(c, 404, "Paciente no encontrado")
	}
	rows, err := a.db.Query(c.Context(), `SELECT id, amount_cents, method, created_at FROM payments
		WHERE clinic_id = $1 AND patient_id = $2 ORDER BY created_at DESC`, clinic, pid)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []Payment{}
	for rows.Next() {
		var p Payment
		var cents int64
		if err := rows.Scan(&p.ID, &cents, &p.Method, &p.CreatedAt); err != nil {
			return err
		}
		p.Amount = float64(cents) / 100
		out = append(out, p)
	}
	return c.JSON(out)
}

func (a *App) createPayment(c *fiber.Ctx) error {
	clinic := c.Locals("clinic").(int64)
	var in struct {
		PatientID int64   `json:"patient_id"`
		Amount    float64 `json:"amount"`
		Method    string  `json:"method"`
	}
	if err := c.BodyParser(&in); err != nil {
		return fail(c, 400, "JSON inválido")
	}
	cents := int64(math.Round(in.Amount * 100))
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
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	return c.Status(201).JSON(p)
}
