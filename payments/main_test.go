// Tests de integración del servicio de caja contra PostgreSQL y Redis reales.
// Necesitan una base con las migraciones de Django aplicadas: ver scripts/test-payments.sh.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/gofiber/fiber/v2"
)

var seq atomic.Int64

type fixture struct {
	clinic, patient int64
	tokens          map[string]string // rol -> token
}

func setup(t *testing.T) (*App, *fiber.App) {
	t.Helper()
	if os.Getenv("DATABASE_URL") == "" {
		t.Skip("DATABASE_URL no definida: se omiten los tests de integración")
	}
	app, err := connect(context.Background(), os.Getenv("DATABASE_URL"), os.Getenv("REDIS_URL"))
	if err != nil {
		t.Fatal(err)
	}
	return app, app.routes()
}

func exec(t *testing.T, a *App, sql string, args ...any) int64 {
	t.Helper()
	var id int64
	if err := a.db.QueryRow(context.Background(), sql, args...).Scan(&id); err != nil {
		t.Fatalf("%v\n%s", err, sql)
	}
	return id
}

// newClinic crea una clínica con un usuario por rol, un paciente y un tratamiento de $100.
func newClinic(t *testing.T, a *App) fixture {
	n := fmt.Sprintf("%d-%d", time.Now().UnixNano(), seq.Add(1))
	fx := fixture{tokens: map[string]string{}}
	fx.clinic = exec(t, a, `INSERT INTO clinica_clinic (name) VALUES ($1) RETURNING id`, "Test "+n)
	for _, role := range []string{"recepcion", "odontologo", "auditor"} {
		uid := exec(t, a, `INSERT INTO clinica_user (password, is_superuser, username, first_name, last_name, email, is_staff,
			is_active, date_joined, clinic_id, role, last_activity) VALUES ('!', false, $1, $2, 'Test', '', false, true, now(), $3, $2, now())
			RETURNING id`, role+n, role, fx.clinic)
		key := fmt.Sprintf("%040x", seq.Add(1)*7919+time.Now().UnixNano())[:40]
		exec(t, a, `INSERT INTO authtoken_token (key, created, user_id) VALUES ($1, now(), $2) RETURNING user_id`, key, uid)
		fx.tokens[role] = key
	}
	fx.patient = exec(t, a, `INSERT INTO clinica_patient (clinic_id, cedula, first_name, last_name, phone, email, allergies,
		medical_history, created_at, emergency_contact_name, emergency_contact_phone, guardian_name, guardian_cedula, insurance,
		systemic_diseases, surgical_history, anticoagulated, coagulopathy)
		VALUES ($1, $2, 'P', 'Test', '', '', '', '', now(), '', '', '', '', '', '', '', false, false) RETURNING id`, fx.clinic, n[len(n)-12:])
	exec(t, a, `INSERT INTO clinica_treatment (clinic_id, patient_id, procedure, cost, date, notes, lab_cost, material_cost)
		VALUES ($1, $2, 'Endodoncia', 100, now()::date, '', 0, 0) RETURNING id`, fx.clinic, fx.patient)
	return fx
}

func call(t *testing.T, f *fiber.App, method, path, token string, body any) (int, any) {
	t.Helper()
	var r io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		r = strings.NewReader(string(b))
	}
	req := httptest.NewRequest(method, path, r)
	req.Header.Set("Content-Type", "application/json")
	if token != "" {
		req.Header.Set("Authorization", "Token "+token)
	}
	res, err := f.Test(req, -1)
	if err != nil {
		t.Fatal(err)
	}
	var out any
	json.NewDecoder(res.Body).Decode(&out)
	return res.StatusCode, out
}

func TestParseCents(t *testing.T) {
	for in, want := range map[float64]int64{0.1 + 0.2: 30, 19.999: 2000, 45: 4500, 0.004: 0} {
		if got := parseCents(in); got != want {
			t.Errorf("parseCents(%v) = %d, quiero %d", in, got, want)
		}
	}
}

func TestAuthAndRoles(t *testing.T) {
	a, f := setup(t)
	fx := newClinic(t, a)
	path := fmt.Sprintf("/pay/patients/%d/balance", fx.patient)
	if s, _ := call(t, f, "GET", path, "", nil); s != 401 {
		t.Errorf("sin token: %d", s)
	}
	if s, _ := call(t, f, "GET", path, "noexiste", nil); s != 401 {
		t.Errorf("token inválido: %d", s)
	}
	if s, b := call(t, f, "GET", path, fx.tokens["recepcion"], nil); s != 200 || b.(map[string]any)["balance"] != 100.0 {
		t.Errorf("saldo: %d %v", s, b)
	}
	if s, _ := call(t, f, "POST", "/pay/payments", fx.tokens["odontologo"], map[string]any{"patient_id": fx.patient, "amount": 1, "method": "efectivo"}); s != 403 {
		t.Errorf("odontólogo cobrando: %d", s)
	}
	// sesión inactiva más de 15 min: se rechaza aunque el token exista
	exec(t, a, `UPDATE clinica_user u SET last_activity = now() - interval '16 minutes' FROM authtoken_token k
		WHERE k.user_id = u.id AND k.key = $1 RETURNING u.id`, fx.tokens["auditor"])
	if s, _ := call(t, f, "GET", "/pay/cash-closings", fx.tokens["auditor"], nil); s != 401 {
		t.Errorf("sesión inactiva: %d", s)
	}
	if s, _ := call(t, f, "GET", "/pay/health", "", nil); s != 200 {
		t.Errorf("health: %d", s)
	}
}

func TestTenantIsolation(t *testing.T) {
	a, f := setup(t)
	mine, other := newClinic(t, a), newClinic(t, a)
	if s, _ := call(t, f, "GET", fmt.Sprintf("/pay/patients/%d/balance", other.patient), mine.tokens["recepcion"], nil); s != 404 {
		t.Errorf("saldo de otra clínica: %d", s)
	}
	if s, _ := call(t, f, "POST", "/pay/payments", mine.tokens["recepcion"], map[string]any{"patient_id": other.patient, "amount": 1, "method": "efectivo"}); s != 404 {
		t.Errorf("cobro a otra clínica: %d", s)
	}
}

func TestPaymentValidationAndInvoice(t *testing.T) {
	a, f := setup(t)
	fx := newClinic(t, a)
	tok := fx.tokens["recepcion"]
	for _, body := range []map[string]any{
		{"patient_id": fx.patient, "amount": 0, "method": "efectivo"},
		{"patient_id": fx.patient, "amount": 5, "method": "bitcoin"},
	} {
		if s, _ := call(t, f, "POST", "/pay/payments", tok, body); s != 400 {
			t.Errorf("%v: %d", body, s)
		}
	}
	if s, _ := call(t, f, "POST", "/pay/payments", tok, map[string]any{"patient_id": fx.patient, "amount": 100.01, "method": "efectivo"}); s != 422 {
		t.Errorf("sobrepago: %d", s)
	}
	s, b := call(t, f, "POST", "/pay/payments", tok, map[string]any{"patient_id": fx.patient, "amount": 40, "method": "tarjeta"})
	if s != 201 || !strings.HasPrefix(b.(map[string]any)["invoice_number"].(string), "001-001-") {
		t.Fatalf("cobro: %d %v", s, b)
	}
	if _, list := call(t, f, "GET", fmt.Sprintf("/pay/patients/%d/payments", fx.patient), tok, nil); len(list.([]any)) != 1 {
		t.Errorf("lista de pagos: %v", list)
	}
}

// Cinco cobros simultáneos de $30 contra un saldo de $100: el bloqueo de fila deja pasar exactamente tres.
func TestConcurrentPaymentsNeverExceedBalance(t *testing.T) {
	a, f := setup(t)
	fx := newClinic(t, a)
	var ok atomic.Int32
	var wg sync.WaitGroup
	for range 5 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if s, _ := call(t, f, "POST", "/pay/payments", fx.tokens["recepcion"], map[string]any{"patient_id": fx.patient, "amount": 30, "method": "efectivo"}); s == 201 {
				ok.Add(1)
			}
		}()
	}
	wg.Wait()
	_, b := call(t, f, "GET", fmt.Sprintf("/pay/patients/%d/balance", fx.patient), fx.tokens["recepcion"], nil)
	if ok.Load() != 3 || b.(map[string]any)["balance"] != 10.0 {
		t.Errorf("cobros aceptados %d, saldo %v", ok.Load(), b)
	}
}

func TestBlindCashClosingAndIncome(t *testing.T) {
	a, f := setup(t)
	fx := newClinic(t, a)
	rec, aud := fx.tokens["recepcion"], fx.tokens["auditor"]
	call(t, f, "POST", "/pay/payments", rec, map[string]any{"patient_id": fx.patient, "amount": 25, "method": "efectivo"})
	call(t, f, "POST", "/pay/payments", rec, map[string]any{"patient_id": fx.patient, "amount": 15, "method": "tarjeta"})
	if s, _ := call(t, f, "GET", "/pay/cash-closings", rec, nil); s != 403 {
		t.Errorf("recepción viendo cierres: %d", s)
	}
	if s, _ := call(t, f, "POST", "/pay/cash-closings", rec, map[string]any{"counted": -1}); s != 400 {
		t.Errorf("conteo negativo: %d", s)
	}
	s, b := call(t, f, "POST", "/pay/cash-closings", rec, map[string]any{"counted": 20})
	m := b.(map[string]any)
	if s != 201 || m["expected"] != 25.0 || m["difference"] != -5.0 {
		t.Errorf("cierre: %d %v", s, b) // solo efectivo cuenta para la caja
	}
	if s, _ := call(t, f, "POST", "/pay/cash-closings", rec, map[string]any{"counted": 20}); s != 409 {
		t.Errorf("segundo cierre del día: %d", s)
	}
	if _, list := call(t, f, "GET", "/pay/cash-closings", aud, nil); len(list.([]any)) != 1 {
		t.Errorf("cierres para auditoría: %v", list)
	}
	today := time.Now().In(time.FixedZone("ECT", -5*3600)).Format("2006-01-02")
	if s, _ := call(t, f, "GET", "/pay/reports/income?from=bad&to="+today, aud, nil); s != 400 {
		t.Errorf("rango inválido: %d", s)
	}
	_, inc := call(t, f, "GET", "/pay/reports/income?from="+today+"&to="+today, aud, nil)
	if len(inc.([]any)) != 2 {
		t.Errorf("ingresos por método: %v", inc)
	}
}
