import { useEffect, useState } from "react";
import { api, fmtDateTime, is, money } from "../api.js";

const STATUS = { pendiente: "Pendiente de aprobación", aprobado: "Aprobado", parcial: "Aprobado parcialmente", rechazado: "Rechazado" };
const MAX_DISCOUNT = 15; // tope del backend (MAX_DISCOUNT_PCT)

function BudgetCard({ b, onDecided }) {
  const [approved, setApproved] = useState(() => new Set(b.items.map((i) => i.id)));
  const [error, setError] = useState("");
  const pending = b.status === "pendiente";
  const phases = [...new Set(b.items.map((i) => i.phase))];
  const toggle = (id) => {
    const next = new Set(approved);
    next.has(id) ? next.delete(id) : next.add(id);
    setApproved(next);
  };
  const decide = async () => {
    setError("");
    try {
      onDecided(await api(`/api/budgets/${b.id}/decide/`, { method: "POST", body: { approved_items: [...approved] } }));
    } catch (e) {
      setError(e.message);
    }
  };
  const itemState = (i) =>
    i.done ? "Realizado" : i.approved === false ? "No aprobado" : i.approved ? (i.scheduled ? "Agendado" : "Por agendar") : "";

  return (
    <li className="rule-row py-4">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-semibold text-pen">Presupuesto Nº {String(b.id).padStart(5, "0")}</span>
        <span className="text-sm text-pencil">{fmtDateTime(b.created_at)} · {b.author_name}</span>
        <span className={`ml-auto text-sm font-semibold ${b.status === "rechazado" ? "text-red" : pending ? "text-pencil" : "text-pen"}`}>{STATUS[b.status]}</span>
      </div>
      <table className="mt-2 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-print">
            {pending && is("recepcion", "odontologo") && <th className="label w-10 py-1">Aprueba</th>}
            <th className="label py-1">Procedimiento</th>
            <th className="label py-1">Pieza</th>
            <th className="label py-1 text-right">Honorario</th>
            <th className="label py-1 text-right">Laboratorio</th>
            <th className="label py-1 text-right">Neto</th>
            <th className="label py-1 pl-4">Estado</th>
          </tr>
        </thead>
        {phases.map((phase) => (
          <tbody key={phase}>
            <tr><td colSpan="7" className="label-red pt-3 pb-1">Fase {phase}</td></tr>
            {b.items.filter((i) => i.phase === phase).map((i) => (
              <tr key={i.id} className="rule-row">
                {pending && is("recepcion", "odontologo") && (
                  <td className="py-1.5"><input type="checkbox" checked={approved.has(i.id)} onChange={() => toggle(i.id)} className="h-4 w-4 accent-pen" aria-label={`Aprobar ${i.procedure_name}`} /></td>
                )}
                <td className={`py-1.5 ${i.approved === false ? "text-pencil line-through" : "text-pen"}`}>{i.procedure_name}</td>
                <td className="py-1.5 text-pen">{i.tooth || "—"}</td>
                <td className="py-1.5 text-right text-pen">{money(i.fee)}</td>
                <td className="py-1.5 text-right text-pen">{Number(i.lab_cost) ? money(i.lab_cost) : "—"}</td>
                <td className="py-1.5 text-right font-medium text-pen">{money(i.net)}</td>
                <td className="py-1.5 pl-4 text-pencil">{itemState(i)}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
      <dl className="mt-3 flex flex-wrap justify-end gap-x-6 text-sm">
        <div className="flex gap-2"><dt className="label">Subtotal</dt><dd className="text-pen">{money(b.totals.fees + b.totals.lab)}</dd></div>
        {Number(b.discount_pct) > 0 && <div className="flex gap-2"><dt className="label">Descuento {Number(b.discount_pct)}%</dt><dd className="text-pen">− {money(b.totals.discount)}</dd></div>}
        <div className="flex gap-2"><dt className="label">Total</dt><dd className="font-semibold text-pen">{money(b.totals.total)}</dd></div>
        {!pending && <div className="flex gap-2"><dt className="label">Aprobado</dt><dd className="hand text-lg">{money(b.totals.approved)}</dd></div>}
      </dl>
      {b.notes && <p className="hand mt-1 text-lg">{b.notes}</p>}
      {pending && is("recepcion", "odontologo") && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button onClick={decide} className="btn">{approved.size ? `Registrar aprobación (${approved.size}/${b.items.length})` : "Registrar rechazo"}</button>
          <span className="text-sm text-pencil">Marca lo que el paciente acepta; lo aprobado queda listo para agendar.</span>
          {error && <p className="error w-full" role="alert">{error}</p>}
        </div>
      )}
    </li>
  );
}

function NewBudget({ patient, onCreated }) {
  const [catalog, setCatalog] = useState([]);
  const [rows, setRows] = useState([{ phase: 1, procedure: "", tooth: "" }]);
  const [discount, setDiscount] = useState(0);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/procedures/").then((list) => setCatalog(list.filter((p) => p.active)));
  }, []);
  const set = (k, key, value) => setRows(rows.map((r, j) => (j === k ? { ...r, [key]: value } : r)));
  const byId = Object.fromEntries(catalog.map((p) => [p.id, p]));
  const subtotal = rows.reduce((s, r) => s + (byId[r.procedure] ? Number(byId[r.procedure].fee) + Number(byId[r.procedure].lab_cost) : 0), 0);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const items = rows.map((r) => ({ phase: Number(r.phase), procedure: Number(r.procedure), tooth: r.tooth ? Number(r.tooth) : null }));
      onCreated(await api("/api/budgets/", { method: "POST", body: { patient: patient.id, discount_pct: discount, notes, items } }));
      setRows([{ phase: 1, procedure: "", tooth: "" }]);
      setDiscount(0);
      setNotes("");
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <form onSubmit={submit} className="border-t-2 border-print px-5 py-5">
      <h3 className="label-red mb-3">Nuevo presupuesto</h3>
      {rows.map((r, k) => (
        <div key={k} className="mb-2 grid grid-cols-[72px_1fr_88px_auto] gap-x-3">
          <label><span className="label">Fase</span><input type="number" min="1" max="20" className="field" value={r.phase} onChange={(e) => set(k, "phase", e.target.value)} required /></label>
          <label><span className="label">Procedimiento</span>
            <select className="field" value={r.procedure} onChange={(e) => set(k, "procedure", e.target.value)} required>
              <option value="" disabled>Elegir…</option>
              {catalog.map((p) => <option key={p.id} value={p.id}>{p.name} · {money(Number(p.fee) + Number(p.lab_cost))}</option>)}
            </select>
          </label>
          <label><span className="label">Pieza</span><input type="number" min="11" max="85" className="field" value={r.tooth} onChange={(e) => set(k, "tooth", e.target.value)} /></label>
          <button type="button" onClick={() => setRows(rows.filter((_, j) => j !== k))} disabled={rows.length === 1} className="self-end pb-2 text-sm font-medium text-red disabled:opacity-30">Quitar</button>
        </div>
      ))}
      <button type="button" onClick={() => setRows([...rows, { phase: rows.at(-1).phase, procedure: "", tooth: "" }])} className="link">Agregar procedimiento</button>
      <div className="mt-4 grid gap-4 sm:grid-cols-[160px_1fr]">
        <label><span className="label">Descuento % (máx. {MAX_DISCOUNT})</span>
          <input type="number" min="0" max={MAX_DISCOUNT} step="0.5" className="field" value={discount} onChange={(e) => setDiscount(e.target.value)} />
        </label>
        <label><span className="label">Observaciones</span><input className="field" value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      <p className="mt-3 text-sm text-pencil">
        Subtotal {money(subtotal)} · total estimado <span className="font-semibold text-pen">{money(subtotal * (1 - Number(discount || 0) / 100))}</span>
      </p>
      {error && <p className="error mt-2" role="alert">{error}</p>}
      <button className="btn mt-3">Emitir presupuesto</button>
    </form>
  );
}

// RF-07/08: presupuesto por fases, aprobación total o parcial, ítems aprobados pasan a la agenda
export default function Budgets({ patient, onChange }) {
  const [list, setList] = useState(null);
  const load = () => api(`/api/budgets/?patient=${patient.id}`).then(setList);
  useEffect(() => {
    load();
  }, [patient.id]);
  const replace = (b) => {
    setList(list.map((x) => (x.id === b.id ? b : x)));
    onChange?.();
  };

  return (
    <section className="sheet">
      <div className="border-b-2 border-print px-5 py-4"><h2 className="text-xl font-semibold">Planes de tratamiento y presupuestos</h2></div>
      <ul className="px-5">
        {list?.map((b) => <BudgetCard key={b.id} b={b} onDecided={replace} />)}
        {list?.length === 0 && <li className="py-6 text-pencil">Sin presupuestos emitidos.</li>}
      </ul>
      {is("odontologo") && <NewBudget patient={patient} onCreated={(b) => setList([b, ...(list || [])])} />}
    </section>
  );
}
