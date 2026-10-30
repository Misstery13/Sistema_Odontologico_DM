// Microservicio de facturación y caja: registra cobros contra el saldo de tratamientos del paciente,
// emite el comprobante (adaptador SRI simulado) y lleva el cierre de caja ciego (RN-02).
// Comparte PostgreSQL con Django (lee tokens, usuarios, pacientes y tratamientos) y usa Redis
// para cachear la resolución token -> sesión.
package main

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gofiber/contrib/websocket"
	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

// App agrupa las dependencias; se inyectan en main y los handlers las usan vía receptor.
type App struct {
	db  *pgxpool.Pool
	rdb *redis.Client
	hub *hub
}

type Payment struct {
	ID        int64     `json:"id"`
	Amount    float64   `json:"amount"`
	Method    string    `json:"method"`
	Invoice   string    `json:"invoice_number"`
	Auth      string    `json:"authorization,omitempty"` // código de la pasarela (tarjeta)
	BuyerID   string    `json:"buyer_id"`                // cédula, RUC o 9999999999999 (consumidor final)
	BuyerName string    `json:"buyer_name"`
	// RN-01: un cobro erróneo no se borra; se anula con nota de crédito
	Voided     bool       `json:"voided"`
	VoidReason string     `json:"void_reason,omitempty"`
	VoidedAt   *time.Time `json:"voided_at,omitempty"`
	CreditNote string     `json:"credit_note,omitempty"`
	CreatedAt time.Time `json:"created_at"`
}

type session struct{ user, clinic int64; role string }

// querier lo cumplen tanto el pool como una transacción.
type querier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// especificación OpenAPI 3 de este servicio, servida en /pay/openapi.yaml
//
//go:embed openapi.yaml
var openapiSpec []byte

// RF-12: pagos mixtos = varios cobros con métodos distintos ("tarjeta" queda solo para registros antiguos)
var methods = map[string]bool{"efectivo": true, "tarjeta_credito": true, "tarjeta_debito": true, "transferencia": true, "seguro": true}

const finalConsumer = "9999999999999"

// validBuyer: cédula (10 dígitos), RUC (13 dígitos terminado en 001) o consumidor final, como exige el comprobante.
// ponytail: valida formato, no el dígito verificador del SRI; agregarlo al conectar la facturación real.
func validBuyer(id, name string) bool {
	for _, r := range id {
		if r < '0' || r > '9' {
			return false
		}
	}
	return strings.TrimSpace(name) != "" && (len(id) == 10 || (len(id) == 13 && (strings.HasSuffix(id, "001") || id == finalConsumer)))
}

// RBAC (RNF-05), igual criterio que Django: la recepción cobra y cierra caja; auditoría solo lee.
var (
	readers  = []string{"recepcion", "odontologo", "asistente", "auditor"}
	cashiers = []string{"recepcion"}
	auditors = []string{"admin", "auditor"}
)

const idleMinutes = 15

// authorizeCard cobra la tarjeta en la pasarela y devuelve el código de autorización.
// ponytail: adaptador simulado (siempre aprueba, solo log); conectar aquí Stripe / dLocal / la pasarela bancaria.
var authorizeCard = func(cents int64, clinic int64) (string, error) {
	code := fmt.Sprintf("SIM-%06d", time.Now().UnixNano()%1_000_000)
	log.Printf("[pasarela simulada] clínica %d autoriza %.2f con código %s", clinic, float64(cents)/100, code)
	return code, nil
}

// issueCreditNote emite la nota de crédito que anula un comprobante (y reversa el cobro en la pasarela si fue con tarjeta).
// ponytail: adaptador simulado (solo log); conectar aquí el SRI y la pasarela reales.
var issueCreditNote = func(p Payment, clinic int64) string {
	n := fmt.Sprintf("NC-001-001-%09d", p.ID)
	log.Printf("[SRI simulado] clínica %d nota de crédito %s anula %s por %.2f", clinic, n, p.Invoice, p.Amount)
	if strings.HasPrefix(p.Method, "tarjeta") {
		log.Printf("[pasarela simulada] reverso de la autorización %s", p.Auth)
	}
	return n
}

// issueInvoice emite el comprobante electrónico.
// ponytail: adaptador simulado (solo log); conectar aquí la API de facturación electrónica del SRI.
var issueInvoice = func(p Payment, clinic int64) string {
	n := fmt.Sprintf("001-001-%09d", p.ID)
	log.Printf("[SRI simulado] clínica %d comprobante %s por %.2f (%s)", clinic, n, p.Amount, p.Method)
	return n
}

func main() {
	ctx := context.Background()
	app, err := connect(ctx, os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL"))
	if err != nil {
		log.Fatal(err)
	}
	go app.listen(ctx)
	log.Fatal(app.routes().Listen(":8080"))
}

// connect abre PostgreSQL y Redis y crea las tablas propias del servicio.
func connect(ctx context.Context, dbURL, redisURL string) (*App, error) {
	db, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		return nil, err
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
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS authorization_code TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS buyer_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS buyer_name TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided BOOLEAN NOT NULL DEFAULT false`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS void_reason TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided_by BIGINT`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS voided_at TIMESTAMPTZ`,
		`ALTER TABLE payments ADD COLUMN IF NOT EXISTS credit_note TEXT NOT NULL DEFAULT ''`,
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
			return nil, err
		}
	}
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, err
	}
	return &App{db: db, rdb: redis.NewClient(opt), hub: &hub{subs: map[int64]map[chan struct{}]bool{}}}, nil
}

func (a *App) routes() *fiber.App {
	f := fiber.New()
	f.Get("/pay/health", func(c *fiber.Ctx) error {
		if err := a.db.Ping(c.Context()); err != nil {
			return fail(c, 503, "base de datos no disponible")
		}
		return c.JSON(fiber.Map{"status": "ok"})
	})
	f.Get("/pay/openapi.yaml", func(c *fiber.Ctx) error {
		c.Set(fiber.HeaderContentType, "application/yaml")
		return c.Send(openapiSpec)
	})
	// antes del grupo con a.auth: el WebSocket se autentica con su primer mensaje
	f.Get("/pay/ws", func(c *fiber.Ctx) error {
		if !websocket.IsWebSocketUpgrade(c) {
			return fail(c, 426, "Se requiere una conexión WebSocket")
		}
		return c.Next()
	}, websocket.New(a.agendaSocket))
	api := f.Group("/pay", a.auth)
	api.Get("/patients/:id/balance", allow(readers), a.balance)
	api.Get("/patients/:id/payments", allow(readers), a.listPayments)
	api.Post("/payments", allow(cashiers), a.createPayment)
	api.Get("/payments/:id/receipt", allow(readers), a.receipt)
	api.Post("/payments/:id/void", allow(cashiers), a.voidPayment)
	api.Post("/cash-closings", allow(cashiers), a.closeCash)
	api.Get("/cash-closings", allow(auditors), a.listClosings)
	api.Get("/reports/income", allow(auditors), a.income)
	return f
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
	s, err := a.session(c.Context(), key)
	if err != nil {
		return fail(c, 401, "Sesión inválida o cerrada por inactividad")
	}
	c.Locals("session", s)
	return c.Next()
}

func (a *App) session(ctx context.Context, key string) (session, error) {
	var s session
	if parts := strings.SplitN(a.rdb.Get(ctx, "tok:"+key).Val(), ":", 3); len(parts) == 3 {
		s.user, _ = strconv.ParseInt(parts[0], 10, 64)
		s.clinic, _ = strconv.ParseInt(parts[1], 10, 64)
		s.role = parts[2]
		return s, nil
	}
	// no está en caché (o Redis caído): ir a la base y contar esta petición como actividad
	err := a.db.QueryRow(ctx, `
		UPDATE clinica_user u SET last_activity = now() FROM authtoken_token t
		WHERE t.key = $1 AND u.id = t.user_id AND u.is_active AND u.clinic_id IS NOT NULL AND NOT u.must_change_password
		  AND u.last_activity > now() - make_interval(mins => $2)
		RETURNING u.id, u.clinic_id, u.role`, key, idleMinutes).Scan(&s.user, &s.clinic, &s.role)
	if err != nil {
		return s, err
	}
	// TTL corto: una sesión vencida en Django deja de valer aquí en menos de un minuto
	a.rdb.Set(ctx, "tok:"+key, fmt.Sprintf("%d:%d:%s", s.user, s.clinic, s.role), time.Minute)
	return s, nil
}

// --- Agenda en vivo (RF-09/RF-10) ---
// Django publica pg_notify('agenda', {"clinic": id}) al guardar una cita; este servicio lo reenvía por WebSocket
// a las pantallas abiertas de esa clínica, que vuelven a pedir la agenda a Django (con su RBAC y auditoría).
// Vive aquí y no en Django porque gunicorn atiende con un número fijo de hilos y cada WebSocket ocuparía uno.

// mismo criterio que PERMISSIONS["appointments"] en Django
var agendaReaders = []string{"recepcion", "odontologo", "asistente"}

// cada cuánto se revisa que la sesión siga activa (cierre por 15 min de inactividad, RNF-05)
var socketCheck = time.Minute

// hub reparte los avisos por clínica. Cada suscriptor tiene un canal con buffer 1: una ráfaga de cambios
// se reduce a una sola recarga.
type hub struct {
	mu   sync.Mutex
	subs map[int64]map[chan struct{}]bool
}

func (h *hub) subscribe(clinic int64) chan struct{} {
	ch := make(chan struct{}, 1)
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.subs[clinic] == nil {
		h.subs[clinic] = map[chan struct{}]bool{}
	}
	h.subs[clinic][ch] = true
	return ch
}

func (h *hub) unsubscribe(clinic int64, ch chan struct{}) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.subs[clinic], ch)
}

func (h *hub) publish(clinic int64) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for ch := range h.subs[clinic] {
		select {
		case ch <- struct{}{}:
		default: // ya tiene un aviso pendiente
		}
	}
}

// listen escucha el canal 'agenda' de PostgreSQL con una conexión propia y se reconecta si se cae.
func (a *App) listen(ctx context.Context) {
	for ctx.Err() == nil {
		if err := a.listenOnce(ctx); err != nil && ctx.Err() == nil {
			log.Printf("agenda en vivo: %v; reintento en 2 s", err)
			time.Sleep(2 * time.Second)
		}
	}
}

func (a *App) listenOnce(ctx context.Context) error {
	conn, err := pgx.ConnectConfig(ctx, a.db.Config().ConnConfig.Copy())
	if err != nil {
		return err
	}
	defer conn.Close(context.Background())
	if _, err := conn.Exec(ctx, "LISTEN agenda"); err != nil {
		return err
	}
	for {
		n, err := conn.WaitForNotification(ctx)
		if err != nil {
			return err
		}
		var msg struct {
			Clinic int64 `json:"clinic"`
		}
		if json.Unmarshal([]byte(n.Payload), &msg) == nil {
			a.hub.publish(msg.Clinic)
		}
	}
}

// active revisa la sesión sin contarla como actividad: tener la agenda abierta no evita el cierre por inactividad.
func (a *App) active(ctx context.Context, key string) bool {
	var ok bool
	a.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM clinica_user u JOIN authtoken_token t ON t.user_id = u.id
		WHERE t.key = $1 AND u.is_active AND NOT u.must_change_password AND u.last_activity > now() - make_interval(mins => $2))`,
		key, idleMinutes).Scan(&ok)
	return ok
}

// agendaSocket: el navegador no puede enviar cabeceras al abrir un WebSocket, así que el token llega en el primer
// mensaje (nunca en la URL, que queda en los logs). Al cliente solo se le avisa "cambió la agenda", sin datos clínicos.
func (a *App) agendaSocket(c *websocket.Conn) {
	ctx := context.Background()
	var in struct {
		Token string `json:"token"`
	}
	c.SetReadDeadline(time.Now().Add(10 * time.Second))
	if err := c.ReadJSON(&in); err != nil {
		return
	}
	s, err := a.session(ctx, in.Token)
	if err != nil || !slices.Contains(agendaReaders, s.role) {
		c.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(4001, "Sesión inválida"))
		return
	}
	c.SetReadDeadline(time.Time{})
	ch := a.hub.subscribe(s.clinic)
	defer a.hub.unsubscribe(s.clinic, ch)
	closed := make(chan struct{})
	go func() { // lector: detecta el cierre del navegador y procesa los pong
		defer close(closed)
		for {
			if _, _, err := c.ReadMessage(); err != nil {
				return
			}
		}
	}()
	if c.WriteJSON(fiber.Map{"type": "ready"}) != nil {
		return
	}
	tick := time.NewTicker(socketCheck)
	defer tick.Stop()
	for {
		select {
		case <-closed:
			return
		case <-ch:
			if c.WriteJSON(fiber.Map{"type": "agenda"}) != nil {
				return
			}
		case <-tick.C:
			if !a.active(ctx, in.Token) {
				c.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(4001, "Sesión cerrada por inactividad"))
				return
			}
			if c.WriteMessage(websocket.PingMessage, nil) != nil {
				return
			}
		}
	}
}

func balanceCents(ctx context.Context, q querier, clinic, patient int64) (int64, error) {
	var b int64
	err := q.QueryRow(ctx, `SELECT
		(SELECT COALESCE(SUM(cost), 0) * 100 FROM clinica_treatment WHERE clinic_id = $1 AND patient_id = $2 AND NOT voided)::bigint -
		(SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE clinic_id = $1 AND patient_id = $2 AND NOT voided)::bigint`,
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
	rows, err := a.db.Query(c.Context(), `SELECT id, amount_cents, method, invoice_number, authorization_code, buyer_id, buyer_name, created_at,
		voided, void_reason, voided_at, credit_note FROM payments
		WHERE clinic_id = $1 AND patient_id = $2 ORDER BY created_at DESC`, sess(c).clinic, pid)
	if err != nil {
		return err
	}
	defer rows.Close()
	out := []Payment{}
	for rows.Next() {
		var p Payment
		var cents int64
		if err := rows.Scan(&p.ID, &cents, &p.Method, &p.Invoice, &p.Auth, &p.BuyerID, &p.BuyerName, &p.CreatedAt,
			&p.Voided, &p.VoidReason, &p.VoidedAt, &p.CreditNote); err != nil {
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
		BuyerID   string  `json:"buyer_id"`
		BuyerName string  `json:"buyer_name"`
	}
	if err := c.BodyParser(&in); err != nil {
		return fail(c, 400, "JSON inválido")
	}
	in.BuyerID, in.BuyerName = strings.TrimSpace(in.BuyerID), strings.TrimSpace(in.BuyerName)
	if !validBuyer(in.BuyerID, in.BuyerName) {
		return fail(c, 400, "Datos del comprobante inválidos: cédula (10 dígitos), RUC (13) o consumidor final, y nombre")
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
	p := Payment{Amount: float64(cents) / 100, Method: in.Method, BuyerID: in.BuyerID, BuyerName: in.BuyerName}
	err = tx.QueryRow(ctx, `INSERT INTO payments (clinic_id, patient_id, amount_cents, method, buyer_id, buyer_name)
		VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, created_at`, clinic, in.PatientID, cents, in.Method, in.BuyerID, in.BuyerName).Scan(&p.ID, &p.CreatedAt)
	if err != nil {
		return err
	}
	if strings.HasPrefix(in.Method, "tarjeta") { // dentro de la transacción: si la pasarela rechaza, el cobro no queda registrado
		if p.Auth, err = authorizeCard(cents, clinic); err != nil {
			return fail(c, 402, "La pasarela rechazó la tarjeta: "+err.Error())
		}
	}
	p.Invoice = issueInvoice(p, clinic)
	if _, err := tx.Exec(ctx, `UPDATE payments SET invoice_number = $1, authorization_code = $2 WHERE id = $3`, p.Invoice, p.Auth, p.ID); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	return c.Status(201).JSON(p)
}

// receipt devuelve el comprobante imprimible y registra la exportación en la auditoría clínica (RNF-06).
func (a *App) receipt(c *fiber.Ctx) error {
	s := sess(c)
	pid, err := c.ParamsInt("id")
	if err != nil {
		return fail(c, 404, "Comprobante no encontrado")
	}
	var p Payment
	var cents int64
	var clinicName, patientName string
	err = a.db.QueryRow(c.Context(), `SELECT p.id, p.amount_cents, p.method, p.invoice_number, p.authorization_code, p.buyer_id,
		p.buyer_name, p.created_at, k.name, pa.first_name || ' ' || pa.last_name, p.voided, p.credit_note
		FROM payments p JOIN clinica_clinic k ON k.id = p.clinic_id JOIN clinica_patient pa ON pa.id = p.patient_id
		WHERE p.id = $1 AND p.clinic_id = $2`, pid, s.clinic).Scan(&p.ID, &cents, &p.Method, &p.Invoice, &p.Auth, &p.BuyerID,
		&p.BuyerName, &p.CreatedAt, &clinicName, &patientName, &p.Voided, &p.CreditNote)
	if errors.Is(err, pgx.ErrNoRows) {
		return fail(c, 404, "Comprobante no encontrado")
	} else if err != nil {
		return err
	}
	p.Amount = float64(cents) / 100
	ip := strings.TrimSpace(strings.Split(c.Get("X-Forwarded-For"), ",")[0])
	if ip == "" {
		ip = c.IP()
	}
	if _, err := a.db.Exec(c.Context(), `INSERT INTO clinica_auditlog (clinic_id, user_id, action, model, object_id, ip, timestamp)
		VALUES ($1, $2, 'export', 'Payment', $3, $4, now())`, s.clinic, s.user, fmt.Sprint(p.ID), ip); err != nil {
		return err
	}
	return c.JSON(fiber.Map{"payment": p, "clinic": clinicName, "patient": patientName,
		"tax": fiber.Map{"iva_rate": 0, "note": "Servicios de salud: tarifa 0 % de IVA"}})
}

// voidPayment anula un cobro con justificación y nota de crédito. No se permite si la caja de ese día ya se cerró:
// la anulación cambiaría un cierre ya cuadrado (RN-02); una corrección posterior va con un nuevo cobro o reembolso.
func (a *App) voidPayment(c *fiber.Ctx) error {
	s := sess(c)
	pid, err := c.ParamsInt("id")
	if err != nil {
		return fail(c, 404, "Cobro no encontrado")
	}
	var in struct {
		Reason string `json:"reason"`
	}
	if err := c.BodyParser(&in); err != nil || len([]rune(strings.TrimSpace(in.Reason))) < 10 {
		return fail(c, 400, "Explica el motivo de la anulación (mínimo 10 caracteres)")
	}
	ctx := c.Context()
	tx, err := a.db.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var p Payment
	var cents int64
	var closed bool
	err = tx.QueryRow(ctx, `SELECT p.id, p.amount_cents, p.method, p.invoice_number, p.authorization_code, p.voided,
		EXISTS (SELECT 1 FROM cash_closings k WHERE k.clinic_id = p.clinic_id AND k.day = (p.created_at AT TIME ZONE 'America/Guayaquil')::date)
		FROM payments p WHERE p.id = $1 AND p.clinic_id = $2 FOR UPDATE OF p`, pid, s.clinic).Scan(&p.ID, &cents, &p.Method, &p.Invoice, &p.Auth, &p.Voided, &closed)
	if errors.Is(err, pgx.ErrNoRows) {
		return fail(c, 404, "Cobro no encontrado")
	} else if err != nil {
		return err
	}
	if p.Voided {
		return fail(c, 409, "El cobro ya está anulado")
	}
	if closed {
		return fail(c, 409, "La caja de ese día ya fue cerrada; no se puede anular el cobro")
	}
	p.Amount = float64(cents) / 100
	p.CreditNote = issueCreditNote(p, s.clinic)
	err = tx.QueryRow(ctx, `UPDATE payments SET voided = true, void_reason = $1, voided_by = $2, voided_at = now(), credit_note = $3
		WHERE id = $4 RETURNING voided_at`, strings.TrimSpace(in.Reason), s.user, p.CreditNote, p.ID).Scan(&p.VoidedAt)
	if err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO clinica_auditlog (clinic_id, user_id, action, model, object_id, ip, timestamp)
		VALUES ($1, $2, 'update', 'Payment', $3, $4, now())`, s.clinic, s.user, fmt.Sprint(p.ID), c.IP()); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	p.Voided, p.VoidReason = true, strings.TrimSpace(in.Reason)
	return c.JSON(p)
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
			WHERE clinic_id = $1 AND method = 'efectivo' AND NOT voided AND (created_at AT TIME ZONE 'America/Guayaquil')::date = d)
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
		WHERE clinic_id = $1 AND NOT voided AND (created_at AT TIME ZONE 'America/Guayaquil')::date BETWEEN $2::date AND $3::date
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
