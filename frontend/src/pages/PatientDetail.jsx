import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { api, formSubmit, getSession, is, money, printElement } from "../api.js";
import PatientForm from "../PatientForm.jsx";

import Odontogram, { pendingFindings } from "../Odontogram.jsx";
import Budgets from "../clinical/Budgets.jsx";
import Attachments from "../clinical/Attachments.jsx";
import Vitals from "../clinical/Vitals.jsx";
import Consents from "../clinical/Consents.jsx";
import Perio from "../clinical/Perio.jsx";
import Prescriptions from "../clinical/Prescriptions.jsx";

const fmtDate = (d) => new Date(`${d}T12:00`).toLocaleDateString("es-EC", { day: "2-digit", month: "2-digit", year: "numeric" });

export default function PatientDetail() {
  const { id } = useParams();
  const [patient, setPatient] = useState(null);
  const [teeth, setTeeth] = useState({});
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0); // se incrementa al registrar un tratamiento para refrescar el saldo
  const [planRev, setPlanRev] = useState(0); // se incrementa al decidir un presupuesto para refrescar "Por tratar"

  useEffect(() => {
    api(`/api/patients/${id}/`).then(setPatient).catch((e) => setError(e.message));
  }, [id]);

  const save = async (data) => {
    setPatient(await api(`/api/patients/${id}/`, { method: "PATCH", body: data }));
    setEditing(false);
  };

  if (error) return <p className="error">{error}</p>;
  if (!patient) return <p className="text-pencil">Cargando ficha…</p>;
  if (editing)
    return (
      <section className="sheet mx-auto max-w-2xl border-t-4 border-red">
        <div className="border-b border-dashed border-pencil/50 px-5 py-3">
          <h1 className="label-red">Editar ficha · {patient.last_name}, {patient.first_name}</h1>
        </div>
        <PatientForm initial={patient} onSave={save} submitLabel="Guardar cambios" onCancel={() => setEditing(false)} />
      </section>
    );
  return (
    <div className="space-y-6">
      {patient.alerts.length > 0 && (
        <div role="alert" className="flex flex-wrap items-center gap-2">
          {patient.alerts.map((a) => (
            <span key={a} className="inline-flex items-center gap-2 rounded-[3px] bg-red px-3 py-1.5 text-sm font-semibold uppercase tracking-[0.06em] text-white">
              <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 3l10 18H2L12 3z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" />
                <path d="M12 10v5M12 18v.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
              </svg>
              {a}
            </span>
          ))}
        </div>
      )}
      <article className="sheet grid grid-cols-1 lg:grid-cols-[52px_minmax(0,0.85fr)_minmax(0,1.5fr)_minmax(0,0.95fr)]">
        <div className="flex items-center justify-between gap-3 bg-red px-4 py-2 text-white lg:flex-col lg:px-0 lg:py-5">
          <span className="font-semibold uppercase tracking-[0.14em] lg:[writing-mode:vertical-rl] lg:rotate-180">
            {patient.last_name}, {patient.first_name}
          </span>
          <span className="text-xs font-semibold tracking-[0.1em] lg:[writing-mode:vertical-rl] lg:rotate-180">HC {String(patient.id).padStart(6, "0")}</span>
        </div>
        <PatientData patient={patient} onEdit={is("recepcion", "odontologo") ? () => setEditing(true) : null} />
        <Treatments patientId={id} teeth={teeth} planRev={planRev} onChange={() => setRev(rev + 1)} />
        <Payments patient={patient} rev={rev} />
      </article>
      <Odontogram patientId={id} teeth={teeth} setTeeth={setTeeth} />
      {is("odontologo", "asistente", "recepcion") && <ClinicalRecord patient={patient} teeth={teeth} onPlanChange={() => setPlanRev(planRev + 1)} />}
    </div>
  );
}

function Panel({ title, children, className = "" }) {
  return (
    <section className={`border-t border-dashed border-pencil/50 px-5 py-5 lg:border-t-0 lg:border-l ${className}`}>
      <h2 className="label-red mb-4">{title}</h2>
      {children}
    </section>
  );
}

const ACTIVE = ["programado", "confirmado", "en_espera"];

function PatientData({ patient, onEdit }) {
  const [next, setNext] = useState(undefined);
  useEffect(() => {
    api(`/api/appointments/?patient=${patient.id}`).then((list) =>
      setNext(list.find((a) => ACTIVE.includes(a.status) && new Date(a.start) >= new Date()) || null),
    );
  }, [patient.id]);

  const rows = [
    ["Cédula", patient.cedula],
    ["Nacimiento", patient.birth_date && fmtDate(patient.birth_date)],
    ["Teléfono", patient.phone],
    ["Email", patient.email],
    ["Seguro", patient.insurance],
    ["Emergencia", patient.emergency_contact_name && `${patient.emergency_contact_name} · ${patient.emergency_contact_phone}`],
    ...(patient.is_minor ? [["Tutor legal", `${patient.guardian_name}${patient.guardian_cedula ? ` · ${patient.guardian_cedula}` : ""}`]] : []),
  ];
  const anamnesis = [
    ["Alergias a fármacos", patient.allergies],
    ["Enfermedades sistémicas", patient.systemic_diseases],
    ["Antecedentes quirúrgicos", patient.surgical_history],
    ["Otros antecedentes", patient.medical_history],
  ];
  return (
    <Panel title="Datos del paciente" className="lg:border-l-0">
      <div className="flex items-start justify-between gap-3">
        <p className="hand text-4xl leading-tight">{patient.first_name} {patient.last_name}</p>
        {onEdit && <button onClick={onEdit} className="link mt-2 shrink-0">Editar</button>}
      </div>
      <dl className="mt-4">
        {rows.map(([k, v]) => (
          <div key={k} className="rule-row flex items-baseline justify-between gap-4 py-2">
            <dt className="label shrink-0">{k}</dt>
            <dd className={v ? "text-right font-medium text-pen" : "text-pencil"}>{v || "—"}</dd>
          </div>
        ))}
      </dl>
      <h3 className="label mt-5 border-b-2 border-print pb-1">Anamnesis</h3>
      <dl>
        {anamnesis.map(([k, v]) => (
          <div key={k} className="rule-row py-1.5">
            <dt className="text-xs font-semibold text-pencil">{k}</dt>
            <dd className={v ? "hand text-lg leading-snug" : "text-sm text-pencil"}>{v || "—"}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-6 border-t-2 border-print pt-3">
        <h3 className="label">Próxima cita</h3>
        {next === undefined ? null : next ? (
          <p className="hand mt-1 text-xl">
            {new Date(next.start).toLocaleString("es-EC", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
            <span className="block text-base text-pencil">{[next.dentist_name, next.chair_name, next.reason].filter(Boolean).join(" · ")}</span>
          </p>
        ) : (
          <p className="mt-1 text-sm text-pencil">Sin citas programadas</p>
        )}
      </div>
    </Panel>
  );
}

function Treatments({ patientId, teeth, planRev, onChange }) {
  const [items, setItems] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [planned, setPlanned] = useState([]); // ítems aprobados del presupuesto, aún no realizados
  const [source, setSource] = useState("");
  const [chairs, setChairs] = useState([]);
  const [chair, setChair] = useState("");
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");
  const load = () => {
    api(`/api/treatments/?patient=${patientId}`).then(setItems);
    if (is("odontologo")) api(`/api/budgets/pending/?patient=${patientId}`).then(setPlanned);
  };
  useEffect(() => {
    if (planRev && is("odontologo")) api(`/api/budgets/pending/?patient=${patientId}`).then(setPlanned);
  }, [planRev]);
  useEffect(() => {
    load();
    if (!is("odontologo")) return;
    api("/api/procedures/").then((l) => setCatalog(l.filter((p) => p.active)));
    api("/api/chairs/").then((l) => setChairs(l.filter((c) => c.active)));
    // por defecto, el consultorio de la cita de hoy
    api(`/api/appointments/?patient=${patientId}&date=${new Date().toLocaleDateString("sv")}`).then((l) => l[0]?.chair && setChair(String(l[0].chair)));
  }, [patientId]);

  // origen: "b<id>" ítem del presupuesto, "c<id>" catálogo, "otro" texto libre
  const submit = formSubmit(async (data) => {
    const body = { patient: patientId, date: data.date, notes: data.notes, tooth: data.tooth || null, chair: chair ? Number(chair) : null };
    if (source.startsWith("b")) body.budget_item = Number(source.slice(1));
    else if (source.startsWith("c")) body.catalog = Number(source.slice(1));
    else Object.assign(body, { procedure: data.procedure, cost: data.cost });
    const t = await api("/api/treatments/", { method: "POST", body });
    setFresh(t.id);
    setSource("");
    load();
    onChange();
  }, setError);

  const pending = pendingFindings(teeth);
  const selectedPlan = planned.find((i) => `b${i.id}` === source);
  const selectedProc = catalog.find((p) => `c${p.id}` === source);
  const price = selectedPlan ? selectedPlan.net : selectedProc ? Number(selectedProc.fee) + Number(selectedProc.lab_cost) : null;

  return (
    <Panel title="Tratamientos">
      <h3 className="label border-b-2 border-print pb-1">Por tratar</h3>
      {pending.length || planned.length ? (
        <ul>
          {pending.map((f) => <li key={f} className="rule-row py-1.5 font-medium text-red">{f}</li>)}
          {planned.map((i) => (
            <li key={i.id} className="rule-row flex justify-between py-1.5 text-pen">
              <span>{i.procedure_name}{i.tooth && ` · pieza ${i.tooth}`} <span className="text-pencil">· fase {i.phase}{i.scheduled ? " · agendado" : ""}</span></span>
              <span>{money(i.net)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-2 text-sm text-pencil">Sin hallazgos ni presupuestos pendientes.</p>
      )}
      <h3 className="label mt-6 flex justify-between border-b-2 border-print pb-1">
        <span>Realizado</span>
        <span>{money(items.reduce((s, t) => s + Number(t.cost), 0))}</span>
      </h3>
      <ul>
        {items.map((t) => (
          <li key={t.id} className="rule-row py-1.5">
            <div className={`flex justify-between gap-3 ${t.id === fresh ? "write-in" : ""}`}>
              <span className="text-pen"><span className="text-pencil">{fmtDate(t.date)}</span> · {t.procedure}{t.tooth && ` · pieza ${t.tooth}`}</span>
              <span className="font-medium text-pen">{money(t.cost)}</span>
            </div>
            {(t.dentist_name || t.notes) && (
              <p className="text-sm text-pencil">{t.dentist_name}{t.notes && <span className="hand text-base text-pen"> · {t.notes}</span>}</p>
            )}
          </li>
        ))}
        {!items.length && <li className="py-2 text-sm text-pencil">Sin tratamientos registrados.</li>}
      </ul>
      {is("odontologo") && <form onSubmit={submit} className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3">
        <label className="col-span-full"><span className="label">Procedimiento realizado</span>
          <select className="field" value={source} onChange={(e) => setSource(e.target.value)} required>
            <option value="" disabled>Elegir…</option>
            {planned.length > 0 && (
              <optgroup label="Del presupuesto aprobado">
                {planned.map((i) => <option key={i.id} value={`b${i.id}`}>{i.procedure_name}{i.tooth ? ` · pieza ${i.tooth}` : ""} · {money(i.net)}</option>)}
              </optgroup>
            )}
            <optgroup label="Catálogo">
              {catalog.map((p) => <option key={p.id} value={`c${p.id}`}>{p.name} · {money(Number(p.fee) + Number(p.lab_cost))}</option>)}
            </optgroup>
            <option value="otro">Otro (texto libre)</option>
          </select>
        </label>
        {source === "otro" && <>
          <label className="col-span-2"><span className="label">Descripción</span><input name="procedure" className="field" required /></label>
          <label className="col-span-2"><span className="label">Costo $</span><input name="cost" type="number" step="0.01" min="0" className="field" required /></label>
        </>}
        <label><span className="label">Pieza</span><input name="tooth" type="number" min="11" max="85" className="field" placeholder={selectedPlan?.tooth ? String(selectedPlan.tooth) : "Opcional"} /></label>
        <label><span className="label">Fecha</span><input name="date" type="date" className="field" required defaultValue={new Date().toLocaleDateString("sv")} /></label>
        <label><span className="label">Consultorio</span>
          <select className="field" value={chair} onChange={(e) => setChair(e.target.value)}>
            <option value="">Bodega central</option>
            {chairs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label><span className="label">Notas</span><input name="notes" className="field" /></label>
        {price !== null && <p className="col-span-full text-sm text-pencil">Se cargará {money(price)} al saldo y se descargarán los insumos de la receta estándar del consultorio elegido.</p>}
        {error && <p className="error col-span-full" role="alert">{error}</p>}
        <button className="btn col-span-full">Registrar tratamiento</button>
      </form>}
    </Panel>
  );
}

export const METHODS = {
  efectivo: "Efectivo",
  tarjeta_credito: "Tarjeta de crédito",
  tarjeta_debito: "Tarjeta de débito",
  transferencia: "Transferencia",
  seguro: "Seguro",
  tarjeta: "Tarjeta", // registros anteriores a la distinción crédito/débito
};
const FINAL_CONSUMER = "9999999999999";

// comprobante imprimible; pedirlo al servicio de caja deja la exportación en la auditoría (RNF-06)
function Receipt({ id }) {
  const ref = useRef(null);
  const [r, setR] = useState(null);
  useEffect(() => {
    api(`/pay/payments/${id}/receipt`).then(setR);
  }, [id]);
  if (!r) return <p className="text-sm text-pencil">Cargando comprobante…</p>;
  const p = r.payment;
  return (
    <div className="mt-2">
      <div ref={ref} className="sheet border border-rule px-6 py-5 text-sm">
        <div className="flex items-baseline justify-between border-b-4 border-red pb-2">
          <span className="font-bold uppercase tracking-[0.14em] text-red">{r.clinic}</span>
          <span className="label">Comprobante de venta</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1">
          <dt className="label">Número</dt><dd className="text-right font-semibold text-pen">{p.invoice_number}</dd>
          <dt className="label">Fecha</dt><dd className="text-right text-pen">{new Date(p.created_at).toLocaleString("es-EC")}</dd>
          <dt className="label">Cliente</dt><dd className="text-right text-pen">{p.buyer_name}</dd>
          <dt className="label">{p.buyer_id === FINAL_CONSUMER ? "Consumidor final" : p.buyer_id.length === 13 ? "RUC" : "Cédula"}</dt><dd className="text-right text-pen">{p.buyer_id}</dd>
          <dt className="label">Paciente</dt><dd className="text-right text-pen">{r.patient}</dd>
        </dl>
        <table className="mt-3 w-full">
          <tbody>
            <tr className="border-y border-print"><td className="py-1.5">Servicios odontológicos (abono a tratamientos)</td><td className="py-1.5 text-right">{money(p.amount)}</td></tr>
            <tr><td className="pt-1.5 text-pencil">Subtotal IVA 0 % ({r.tax.note.toLowerCase()})</td><td className="pt-1.5 text-right">{money(p.amount)}</td></tr>
            <tr><td className="text-pencil">IVA</td><td className="text-right">{money(0)}</td></tr>
            <tr className="font-semibold"><td className="pt-1">Total</td><td className="pt-1 text-right">{money(p.amount)}</td></tr>
          </tbody>
        </table>
        <p className="mt-2 text-pencil">Forma de pago: {METHODS[p.method] || p.method}{p.authorization && ` · autorización ${p.authorization}`}</p>
        <p className="mt-1 text-xs text-pencil">Autorización SRI: simulada (ambiente de pruebas)</p>
      </div>
      <button onClick={() => printElement(ref.current)} className="link mt-1">Imprimir</button>
    </div>
  );
}

function Payments({ patient, rev }) {
  const patientId = patient.id;
  const [items, setItems] = useState([]);
  const [balance, setBalance] = useState(null);
  const [fresh, setFresh] = useState(null);
  const [open, setOpen] = useState(null);
  const [finalConsumer, setFinalConsumer] = useState(false);
  const [error, setError] = useState("");
  const load = () => {
    api(`/pay/patients/${patientId}/payments`).then(setItems).catch((e) => setError(e.message));
    api(`/pay/patients/${patientId}/balance`).then((r) => setBalance(r.balance)).catch(() => {});
  };
  useEffect(load, [patientId, rev]);

  // por defecto factura al paciente; si es menor, a su tutor
  const defaultBuyer = patient.is_minor
    ? { id: patient.guardian_cedula, name: patient.guardian_name }
    : { id: patient.cedula, name: `${patient.first_name} ${patient.last_name}` };
  const submit = formSubmit(async (data) => {
    const buyer = finalConsumer ? { buyer_id: FINAL_CONSUMER, buyer_name: "CONSUMIDOR FINAL" } : { buyer_id: data.buyer_id, buyer_name: data.buyer_name };
    const p = await api("/pay/payments", { method: "POST", body: { method: data.method, ...buyer, patient_id: Number(patientId), amount: Number(data.amount) } });
    setFresh(p.id);
    setOpen(p.id);
    load();
  }, setError);
  const paid = items.reduce((s, p) => s + p.amount, 0);

  return (
    <Panel title="Caja">
      <h3 className="label">Saldo pendiente</h3>
      <p className={`hand mt-1 text-5xl leading-none ${balance > 0 ? "" : "text-pencil"}`}>
        {balance === null ? "—" : balance > 0 ? money(balance) : "Al día"}
      </p>
      {balance !== null && (
        <p className="mt-2 text-sm text-pencil">{money(balance + paid)} en tratamientos − {money(paid)} pagado</p>
      )}
      {is("recepcion") && <form onSubmit={submit} className="mt-5 space-y-3">
        <div className="grid grid-cols-2 gap-4">
          <label><span className="label">Monto $</span><input name="amount" type="number" step="0.01" min="0.01" className="field" required /></label>
          <label><span className="label">Método</span>
            <select name="method" className="field">
              {Object.entries(METHODS).filter(([k]) => k !== "tarjeta").map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
        </div>
        <fieldset className="space-y-2">
          <legend className="label">Comprobante a nombre de</legend>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={finalConsumer} onChange={(e) => setFinalConsumer(e.target.checked)} className="h-4 w-4 accent-pen" />
            Consumidor final
          </label>
          {!finalConsumer && (
            <div className="grid grid-cols-2 gap-4">
              <input name="buyer_id" className="field" defaultValue={defaultBuyer.id} placeholder="Cédula o RUC" inputMode="numeric" pattern="\d{10}|\d{13}" required aria-label="Cédula o RUC" />
              <input name="buyer_name" className="field" defaultValue={defaultBuyer.name} placeholder="Nombre o razón social" required aria-label="Nombre o razón social" />
            </div>
          )}
        </fieldset>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn w-full" disabled={!(balance > 0)}>Cobrar y emitir comprobante</button>
      </form>}
      <h3 className="label mt-6 border-b-2 border-print pb-1">Pagos</h3>
      <ul>
        {items.map((p) => (
          <li key={p.id} className="rule-row py-1.5">
            <div className={`flex justify-between ${p.id === fresh ? "write-in" : ""}`}>
              <span className="text-pen"><span className="text-pencil">{new Date(p.created_at).toLocaleDateString("es-EC")}</span> · {METHODS[p.method] || p.method}</span>
              <span className="font-medium text-pen">{money(p.amount)}</span>
            </div>
            <p className="flex justify-between text-xs text-pencil">
              <span>Comprobante {p.invoice_number || "—"}{p.authorization && ` · autorización ${p.authorization}`}</span>
              {p.buyer_id && <button onClick={() => setOpen(open === p.id ? null : p.id)} className="link text-xs">{open === p.id ? "Ocultar" : "Ver comprobante"}</button>}
            </p>
            {open === p.id && <Receipt id={p.id} />}
          </li>
        ))}
        {!items.length && <li className="py-2 text-sm text-pencil">Sin pagos registrados.</li>}
      </ul>
    </Panel>
  );
}

const SOEP = [
  ["subjective", "S", "Subjetivo"],
  ["objective", "O", "Objetivo"],
  ["assessment", "E", "Evaluación"],
  ["plan", "P", "Plan"],
];
const fmtDateTime = (s) => new Date(s).toLocaleString("es-EC", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

function NoteForm({ initial, onSave, onCancel, label }) {
  const [error, setError] = useState("");
  const submit = formSubmit(onSave, setError);
  return (
    <form onSubmit={submit} className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
      {SOEP.map(([name, , title]) => (
        <label key={name}>
          <span className="label">{title}</span>
          <textarea name={name} rows="2" className="field resize-y" defaultValue={initial?.[name] ?? ""} />
        </label>
      ))}
      {error && <p className="error sm:col-span-2" role="alert">{error}</p>}
      <div className="flex gap-3 sm:col-span-2">
        <button className="btn">{label}</button>
        {onCancel && <button type="button" onClick={onCancel} className="link">Cancelar</button>}
      </div>
    </form>
  );
}

// RF-05: bitácora SOEP firmada; editable solo por su autor hasta que se bloquea, luego solo adendas (RN-01)
function Notes({ patientId }) {
  const [notes, setNotes] = useState(null);
  const [mode, setMode] = useState(null); // { edit: nota } | { amend: nota }
  const [fresh, setFresh] = useState(null);
  const me = getSession().id;
  const load = () => api(`/api/notes/?patient=${patientId}`).then(setNotes);
  useEffect(() => {
    load();
  }, [patientId]);

  const save = async (data, note = null, amends = null) => {
    const n = note
      ? await api(`/api/notes/${note.id}/`, { method: "PATCH", body: data })
      : await api("/api/notes/", { method: "POST", body: { ...data, patient: Number(patientId), amends } });
    setFresh(n.id);
    setMode(null);
    load();
  };

  const NoteBody = ({ n }) => (
    <>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-semibold text-pen">{fmtDateTime(n.created_at)}</span>
        <span className="hand text-lg">{n.author_name}</span>
        <span className="text-xs text-pencil" title={n.signature}>Firma {n.signature.slice(0, 12)}…</span>
        {n.locked && <span className="label text-pencil">Bloqueada</span>}
        <span className="ml-auto flex gap-4">
          {!n.locked && n.author === me && <button onClick={() => setMode({ edit: n })} className="link">Editar</button>}
          {n.locked && !n.amends && <button onClick={() => setMode({ amend: n })} className="link">Agregar adenda</button>}
        </span>
      </div>
      {mode?.edit?.id === n.id ? (
        <div className="mt-3"><NoteForm initial={n} label="Firmar cambios" onSave={(d) => save(d, n)} onCancel={() => setMode(null)} /></div>
      ) : (
        <dl className={`mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4 ${n.id === fresh ? "write-in" : ""}`}>
          {SOEP.map(([name, letter, title]) => (
            <div key={name}>
              <dt className="label"><span className="text-red">{letter}</span> · {title}</dt>
              <dd className={n[name] ? "hand text-lg leading-snug" : "text-sm text-pencil"}>{n[name] || "—"}</dd>
            </div>
          ))}
        </dl>
      )}
    </>
  );

  const roots = notes?.filter((n) => !n.amends) ?? [];
  return (
    <section className="sheet">
      <div className="flex items-baseline justify-between border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Evolución clínica (SOEP)</h2>
        <span className="text-sm text-pencil">Las notas se bloquean a las 24 h; después solo admiten adendas.</span>
      </div>
      <ol className="px-5">
        {roots.map((n) => (
          <li key={n.id} className="rule-row py-4">
            <NoteBody n={n} />
            {notes.filter((a) => a.amends === n.id).map((a) => (
              <div key={a.id} className="mt-4 border-t border-dashed border-pencil/50 pt-3 pl-6">
                <p className="label-red mb-1">Adenda</p>
                <NoteBody n={a} />
              </div>
            ))}
            {mode?.amend?.id === n.id && (
              <div className="mt-4 border-t border-dashed border-pencil/50 pt-3 pl-6">
                <p className="label-red mb-2">Nueva adenda</p>
                <NoteForm label="Firmar adenda" onSave={(d) => save(d, null, n.id)} onCancel={() => setMode(null)} />
              </div>
            )}
          </li>
        ))}
        {notes?.length === 0 && <li className="py-6 text-pencil">Sin notas de evolución.</li>}
      </ol>
      <div className="border-t-2 border-print px-5 py-5">
        <h3 className="label-red mb-3">Nueva nota</h3>
        <NoteForm label="Firmar y guardar nota" onSave={(d) => save(d)} />
      </div>
    </section>
  );
}

// expediente clínico (solo personal clínico): evolución, periodontograma, recetas y consentimientos
const TABS = {
  vitales: ["Signos vitales", ["odontologo", "asistente"]],
  soep: ["Evolución SOEP", ["odontologo", "asistente"]],
  perio: ["Periodontograma", ["odontologo", "asistente"]],
  presupuestos: ["Presupuestos", ["odontologo", "asistente", "recepcion"]],
  recetas: ["Recetas", ["odontologo", "asistente"]],
  consentimientos: ["Consentimientos", ["odontologo", "asistente"]],
  archivos: ["Archivos", ["odontologo", "asistente"]],
};

function ClinicalRecord({ patient, teeth, onPlanChange }) {
  const tabs = Object.entries(TABS).filter(([, [, roles]]) => is(...roles));
  const [tab, setTab] = useState(tabs[0][0]);
  return (
    <section>
      <div role="tablist" className="flex flex-wrap gap-1">
        {tabs.map(([k, [v]]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-t-[3px] px-4 py-2 text-sm font-semibold ${tab === k ? "bg-card text-pen" : "text-print hover:text-pen"}`}>
            {v}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "vitales" && <Vitals patient={patient} />}
        {tab === "soep" && <Notes patientId={patient.id} />}
        {tab === "archivos" && <Attachments patient={patient} />}
        {tab === "perio" && <Perio patient={patient} teeth={teeth} />}
        {tab === "presupuestos" && <Budgets patient={patient} onChange={onPlanChange} />}
        {tab === "recetas" && <Prescriptions patient={patient} />}
        {tab === "consentimientos" && <Consents patient={patient} />}
      </div>
    </section>
  );
}
