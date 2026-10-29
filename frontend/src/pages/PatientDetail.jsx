import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, formSubmit, getSession, is, money } from "../api.js";
import PatientForm from "../PatientForm.jsx";

// cada estado tiene color y forma propios, legible aunque no se vea el color
const STATES = {
  sano: "Sano",
  caries: "Caries",
  obturado: "Obturado",
  endodoncia: "Endodoncia",
  corona: "Corona",
  extraido: "Extraído",
};
const PEN = "var(--color-pen)";
const MARKS = {
  sano: <circle cx="12" cy="12" r="7" fill="none" stroke="var(--color-rule)" strokeWidth="1.5" />,
  caries: <circle cx="12" cy="12" r="6.5" fill="var(--color-red)" />,
  obturado: <rect x="5.5" y="5.5" width="13" height="13" rx="2" fill={PEN} />,
  endodoncia: <path d="M12 4v16M8.5 7.5h7" stroke={PEN} strokeWidth="2.5" strokeLinecap="round" fill="none" />,
  corona: <circle cx="12" cy="12" r="7.5" fill="none" stroke={PEN} strokeWidth="2.5" />,
  extraido: <path d="M6 6l12 12M18 6L6 18" stroke={PEN} strokeWidth="2.5" strokeLinecap="round" />,
};
const Mark = ({ state, size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{MARKS[state]}</svg>
);

// arcada superior 18→11 | 21→28, inferior 48→41 | 31→38 (vista del odontólogo)
const quadrant = (q) => [1, 2, 3, 4, 5, 6, 7, 8].map((n) => q * 10 + n);
const ARCHES = [
  [...quadrant(1).reverse(), ...quadrant(2)],
  [...quadrant(4).reverse(), ...quadrant(3)],
];

const fmtDate = (d) => new Date(`${d}T12:00`).toLocaleDateString("es-EC", { day: "2-digit", month: "2-digit", year: "numeric" });

export default function PatientDetail() {
  const { id } = useParams();
  const [patient, setPatient] = useState(null);
  const [teeth, setTeeth] = useState({});
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0); // se incrementa al registrar un tratamiento para refrescar el saldo

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
        <Odontogram patientId={id} teeth={teeth} setTeeth={setTeeth} onTreatment={() => setRev(rev + 1)} />
        <Payments patientId={id} rev={rev} />
      </article>
      {is("odontologo", "asistente") && <Notes patientId={id} />}
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

function Odontogram({ patientId, teeth, setTeeth, onTreatment }) {
  const [brush, setBrush] = useState("caries");
  const [error, setError] = useState("");
  const url = `/api/patients/${patientId}/odontogram/`;
  const apply = (list) => setTeeth(Object.fromEntries(list.map((t) => [t.number, t.state])));

  useEffect(() => {
    api(url).then(apply);
  }, [url]);

  const paint = async (number) => {
    setError("");
    try {
      apply(await api(url, { method: "POST", body: { number, state: brush } }));
    } catch (e) {
      setError(e.message);
    }
  };
  const pending = Object.entries(teeth).filter(([, s]) => s === "caries").map(([n]) => n).sort();
  const canEdit = is("odontologo");

  return (
    <Panel title="Odontograma">
      {canEdit && <div className="flex flex-wrap gap-1.5" role="group" aria-label="Estado a marcar">
        {Object.entries(STATES).map(([key, label]) => (
          <button key={key} onClick={() => setBrush(key)} aria-pressed={brush === key}
            className={`flex items-center gap-1.5 rounded-[3px] border px-2 py-1 text-sm ${brush === key ? "border-pen bg-rule/60 font-semibold text-pen" : "border-rule text-print hover:border-pen"}`}>
            <Mark state={key} size={16} /> {label}
          </button>
        ))}
      </div>}
      <div className="mt-4 overflow-x-auto pb-1">
        {ARCHES.map((row, i) => (
          <div key={i} className={`grid min-w-[440px] grid-cols-[repeat(8,minmax(0,1fr))_8px_repeat(8,minmax(0,1fr))] gap-[3px] ${i ? "mt-2 border-t border-print pt-2" : ""}`}>
            {row.map((n, j) => (
              <button key={n} onClick={() => paint(n)} disabled={!canEdit} aria-label={`Pieza ${n}: ${STATES[teeth[n] || "sano"]}`}
                className={`flex h-14 flex-col items-center justify-between border border-print/60 py-1 enabled:hover:border-pen enabled:hover:bg-rule/30 ${j === 8 ? "col-start-10" : ""}`}>
                <span className="text-[11px] font-semibold leading-none">{n}</span>
                <Mark state={teeth[n] || "sano"} />
              </button>
            ))}
          </div>
        ))}
      </div>
      {canEdit && <p className="mt-2 text-sm text-pencil">Elige un estado y marca la pieza.</p>}
      {error && <p className="error mt-1">{error}</p>}

      <h3 className="label mt-6 border-b-2 border-print pb-1">Por tratar</h3>
      {pending.length ? (
        <ul>{pending.map((n) => <li key={n} className="rule-row flex items-center gap-2 py-1.5 text-pencil"><Mark state="caries" size={14} /> Pieza {n} · caries</li>)}</ul>
      ) : (
        <p className="py-2 text-sm text-pencil">Ninguna pieza con caries marcada.</p>
      )}
      <Treatments patientId={patientId} onChange={onTreatment} />
    </Panel>
  );
}

function Treatments({ patientId, onChange }) {
  const [items, setItems] = useState([]);
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");
  const load = () => api(`/api/treatments/?patient=${patientId}`).then(setItems);
  useEffect(() => {
    load();
  }, [patientId]);

  const submit = formSubmit(async (data) => {
    const t = await api("/api/treatments/", { method: "POST", body: { ...data, patient: patientId, tooth: data.tooth || null } });
    setFresh(t.id);
    load();
    onChange();
  }, setError);

  return (
    <>
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
            {t.notes && <p className="hand text-base">{t.notes}</p>}
          </li>
        ))}
        {!items.length && <li className="py-2 text-sm text-pencil">Sin tratamientos registrados.</li>}
      </ul>
      {is("odontologo") && <form onSubmit={submit} className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
        <label className="col-span-2"><span className="label">Procedimiento</span><input name="procedure" className="field" required /></label>
        <label><span className="label">Pieza</span><input name="tooth" type="number" min="11" max="48" className="field" placeholder="Opcional" /></label>
        <label><span className="label">Costo $</span><input name="cost" type="number" step="0.01" min="0" className="field" required /></label>
        <label className="col-span-2"><span className="label">Fecha</span><input name="date" type="date" className="field" required defaultValue={new Date().toLocaleDateString("sv")} /></label>
        <label className="col-span-2"><span className="label">Notas</span><input name="notes" className="field" /></label>
        {error && <p className="error col-span-full" role="alert">{error}</p>}
        <button className="btn col-span-full sm:col-span-2 sm:col-start-3">Registrar tratamiento</button>
      </form>}
    </>
  );
}

function Payments({ patientId, rev }) {
  const [items, setItems] = useState([]);
  const [balance, setBalance] = useState(null);
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");
  const load = () => {
    api(`/pay/patients/${patientId}/payments`).then(setItems).catch((e) => setError(e.message));
    api(`/pay/patients/${patientId}/balance`).then((r) => setBalance(r.balance)).catch(() => {});
  };
  useEffect(load, [patientId, rev]);

  const submit = formSubmit(async (data) => {
    const p = await api("/pay/payments", { method: "POST", body: { ...data, patient_id: Number(patientId), amount: Number(data.amount) } });
    setFresh(p.id);
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
              <option value="efectivo">Efectivo</option>
              <option value="tarjeta">Tarjeta</option>
              <option value="transferencia">Transferencia</option>
              <option value="seguro">Seguro</option>
            </select>
          </label>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn w-full" disabled={!(balance > 0)}>Cobrar y emitir comprobante</button>
      </form>}
      <h3 className="label mt-6 border-b-2 border-print pb-1">Pagos</h3>
      <ul>
        {items.map((p) => (
          <li key={p.id} className="rule-row py-1.5">
            <div className={`flex justify-between ${p.id === fresh ? "write-in" : ""}`}>
              <span className="text-pen"><span className="text-pencil">{new Date(p.created_at).toLocaleDateString("es-EC")}</span> · {p.method}</span>
              <span className="font-medium text-pen">{money(p.amount)}</span>
            </div>
            <p className="text-xs text-pencil">Comprobante {p.invoice_number || "—"}</p>
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
