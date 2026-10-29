import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, formSubmit, money } from "../api.js";

const STATES = {
  sano: ["Sano", "bg-white"],
  caries: ["Caries", "bg-red-400"],
  obturado: ["Obturado", "bg-blue-400"],
  endodoncia: ["Endodoncia", "bg-purple-400"],
  corona: ["Corona", "bg-amber-300"],
  extraido: ["Extraído", "bg-slate-400"],
};
// arcada superior 18→11 | 21→28, inferior 48→41 | 31→38 (vista del odontólogo)
const quadrant = (q) => [1, 2, 3, 4, 5, 6, 7, 8].map((n) => q * 10 + n);
const ARCHES = [
  [...quadrant(1).reverse(), ...quadrant(2)],
  [...quadrant(4).reverse(), ...quadrant(3)],
];

export default function PatientDetail() {
  const { id } = useParams();
  const [patient, setPatient] = useState(null);
  const [error, setError] = useState("");
  const [rev, setRev] = useState(0); // se incrementa al registrar un tratamiento para refrescar el saldo

  useEffect(() => {
    api(`/api/patients/${id}/`).then(setPatient).catch((e) => setError(e.message));
  }, [id]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!patient) return <p>Cargando…</p>;
  return (
    <div className="space-y-4">
      <section className="card">
        <h2 className="text-xl font-semibold">{patient.last_name}, {patient.first_name}</h2>
        <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
          <Info k="Cédula" v={patient.cedula} />
          <Info k="Nacimiento" v={patient.birth_date} />
          <Info k="Teléfono" v={patient.phone} />
          <Info k="Email" v={patient.email} />
          <Info k="Alergias" v={patient.allergies} warn />
          <Info k="Antecedentes" v={patient.medical_history} />
        </dl>
      </section>
      <Odontogram patientId={id} />
      <div className="grid gap-4 md:grid-cols-2">
        <Treatments patientId={id} onChange={() => setRev(rev + 1)} />
        <Payments patientId={id} rev={rev} />
      </div>
    </div>
  );
}

function Info({ k, v, warn }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{k}</dt>
      <dd className={warn && v ? "font-medium text-red-600" : ""}>{v || "—"}</dd>
    </div>
  );
}

function Odontogram({ patientId }) {
  const [teeth, setTeeth] = useState({});
  const [brush, setBrush] = useState("caries");
  const url = `/api/patients/${patientId}/odontogram/`;
  const apply = (list) => setTeeth(Object.fromEntries(list.map((t) => [t.number, t.state])));

  useEffect(() => {
    api(url).then(apply);
  }, [url]);

  const paint = async (number) => apply(await api(url, { method: "POST", body: { number, state: brush } }));

  return (
    <section className="card">
      <h3 className="mb-2 font-semibold">Odontograma</h3>
      <div className="mb-3 flex flex-wrap gap-2 text-xs">
        {Object.entries(STATES).map(([key, [label, color]]) => (
          <button key={key} onClick={() => setBrush(key)}
            className={`flex items-center gap-1 rounded border px-2 py-1 ${brush === key ? "border-teal-600 ring-2 ring-teal-500" : "border-slate-300"}`}>
            <span className={`h-3 w-3 rounded-sm border border-slate-400 ${color}`} /> {label}
          </button>
        ))}
      </div>
      <div className="overflow-x-auto">
        {ARCHES.map((row, i) => (
          <div key={i} className="flex justify-center gap-1 py-1">
            {row.map((n, j) => (
              <button key={n} onClick={() => paint(n)} title={`Pieza ${n}`}
                className={`h-10 w-8 shrink-0 rounded border border-slate-400 text-xs ${STATES[teeth[n] || "sano"][1]} ${j === 8 ? "ml-3" : ""}`}>
                {n}
              </button>
            ))}
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-500">Elige un estado y haz clic en la pieza.</p>
    </section>
  );
}

function Treatments({ patientId, onChange }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const load = () => api(`/api/treatments/?patient=${patientId}`).then(setItems);
  useEffect(() => {
    load();
  }, [patientId]);

  const submit = formSubmit(async (data) => {
    await api("/api/treatments/", { method: "POST", body: { ...data, patient: patientId, tooth: data.tooth || null } });
    load();
    onChange();
  }, setError);

  return (
    <section className="card">
      <h3 className="mb-2 font-semibold">Historia clínica / Tratamientos</h3>
      <form onSubmit={submit} className="mb-3 grid grid-cols-2 gap-2">
        <input name="procedure" placeholder="Procedimiento" className="input col-span-2" required />
        <input name="tooth" type="number" min="11" max="48" placeholder="Pieza (opcional)" className="input" />
        <input name="cost" type="number" step="0.01" min="0" placeholder="Costo" className="input" required />
        <input name="date" type="date" className="input" required defaultValue={new Date().toLocaleDateString("sv")} />
        <input name="notes" placeholder="Notas" className="input" />
        {error && <p className="col-span-2 text-sm text-red-600">{error}</p>}
        <button className="btn col-span-2">Registrar tratamiento</button>
      </form>
      <ul className="divide-y divide-slate-100 text-sm">
        {items.map((t) => (
          <li key={t.id} className="py-1.5">
            <div className="flex justify-between">
              <span>{t.date} · {t.procedure}{t.tooth && ` (pieza ${t.tooth})`}</span>
              <span className="font-medium">{money(t.cost)}</span>
            </div>
            {t.notes && <p className="text-xs text-slate-500">{t.notes}</p>}
          </li>
        ))}
        {!items.length && <li className="py-2 text-slate-400">Sin tratamientos</li>}
      </ul>
    </section>
  );
}

function Payments({ patientId, rev }) {
  const [items, setItems] = useState([]);
  const [balance, setBalance] = useState(null);
  const [error, setError] = useState("");
  const load = () => {
    api(`/pay/patients/${patientId}/payments`).then(setItems).catch((e) => setError(e.message));
    api(`/pay/patients/${patientId}/balance`).then((r) => setBalance(r.balance)).catch(() => {});
  };
  useEffect(load, [patientId, rev]);

  const submit = formSubmit(async (data) => {
    await api("/pay/payments", { method: "POST", body: { ...data, patient_id: Number(patientId), amount: Number(data.amount) } });
    load();
  }, setError);

  return (
    <section className="card">
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="font-semibold">Pagos</h3>
        <span className="text-sm">Saldo pendiente: <b>{balance === null ? "—" : money(balance)}</b></span>
      </div>
      <form onSubmit={submit} className="mb-3 flex gap-2">
        <input name="amount" type="number" step="0.01" min="0.01" placeholder="Monto" className="input" required />
        <select name="method" className="input">
          <option value="efectivo">Efectivo</option>
          <option value="tarjeta">Tarjeta</option>
          <option value="transferencia">Transferencia</option>
        </select>
        <button className="btn shrink-0">Cobrar</button>
      </form>
      {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
      <ul className="divide-y divide-slate-100 text-sm">
        {items.map((p) => (
          <li key={p.id} className="flex justify-between py-1.5">
            <span>{new Date(p.created_at).toLocaleString("es-EC")} · {p.method}</span>
            <span className="font-medium">{money(p.amount)}</span>
          </li>
        ))}
        {!items.length && <li className="py-2 text-slate-400">Sin pagos</li>}
      </ul>
    </section>
  );
}
