import { useEffect, useRef, useState } from "react";
import { api, fmtDateTime, getSession, is, printElement } from "../api.js";

const EMPTY = { drug: "", dose: "", frequency: "", duration: "", instructions: "" };
const COLS = [["drug", "Medicamento y concentración"], ["dose", "Dosis"], ["frequency", "Frecuencia"], ["duration", "Duración"], ["instructions", "Indicaciones"]];

const age = (birth) => {
  if (!birth) return null;
  const b = new Date(`${birth}T12:00`), now = new Date();
  return now.getFullYear() - b.getFullYear() - (now < new Date(now.getFullYear(), b.getMonth(), b.getDate()) ? 1 : 0);
};

// documento imprimible de la receta
function RxDocument({ rx, patient }) {
  const ref = useRef(null);
  return (
    <div className="mt-3">
      <div ref={ref} className="sheet border border-rule px-8 py-6">
        <div className="flex items-baseline justify-between border-b-4 border-red pb-2">
          <span className="text-sm font-bold uppercase tracking-[0.14em] text-red">{getSession().clinic}</span>
          <span className="label">Receta Nº {String(rx.id).padStart(6, "0")}</span>
        </div>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
          <div><dt className="label">Paciente</dt><dd className="text-pen">{patient.first_name} {patient.last_name}</dd></div>
          <div><dt className="label">Cédula</dt><dd className="text-pen">{patient.cedula}</dd></div>
          <div><dt className="label">Edad</dt><dd className="text-pen">{age(patient.birth_date) ?? "—"}</dd></div>
          <div><dt className="label">Fecha</dt><dd className="text-pen">{fmtDateTime(rx.created_at)}</dd></div>
        </dl>
        {patient.allergies && <p className="mt-2 text-sm font-semibold text-red">Alergias: {patient.allergies}</p>}
        <p className="hand mt-4 text-3xl">Rp/</p>
        <ol className="mt-1 list-decimal space-y-2 pl-6">
          {rx.items.map((i, k) => (
            <li key={k}>
              <span className="font-semibold text-pen">{i.drug}</span>
              <span className="block text-sm">{i.dose} · {i.frequency} · {i.duration}</span>
              {i.instructions && <span className="hand block text-lg">{i.instructions}</span>}
            </li>
          ))}
        </ol>
        {rx.notes && <p className="hand mt-3 text-lg">{rx.notes}</p>}
        {rx.allergy_override && <p className="mt-3 text-sm text-red">Emitida pese a alerta de alergia: {rx.allergy_override}</p>}
        <div className="mt-8 border-t border-print pt-2 text-sm">
          <p className="hand text-xl">{rx.author_name}</p>
          <p className="text-xs text-pencil">Firma digital {rx.signature}</p>
        </div>
      </div>
      <button onClick={() => printElement(ref.current)} className="link mt-2">Imprimir receta</button>
    </div>
  );
}

export default function Prescriptions({ patient }) {
  const [list, setList] = useState(null);
  const [open, setOpen] = useState(null);
  const [items, setItems] = useState([{ ...EMPTY }]);
  const [notes, setNotes] = useState("");
  const [override, setOverride] = useState(null); // aparece cuando el backend detecta una alergia
  const [error, setError] = useState("");
  const load = () => api(`/api/prescriptions/?patient=${patient.id}`).then(setList);
  useEffect(() => {
    load();
  }, [patient.id]);

  const set = (k, key, value) => setItems(items.map((it, j) => (j === k ? { ...it, [key]: value } : it)));
  const submit = async (e) => {
    e.preventDefault();
    setError("");
    try {
      const rx = await api("/api/prescriptions/", { method: "POST", body: { patient: patient.id, items, notes, allergy_override: override ?? "" } });
      setItems([{ ...EMPTY }]);
      setNotes("");
      setOverride(null);
      setOpen(rx.id);
      load();
    } catch (err) {
      setError(err.message);
      if (err.message.includes("Alerta de alergia") && override === null) setOverride("");
    }
  };

  return (
    <section className="sheet">
      <div className="border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Recetas</h2>
      </div>
      <ul className="px-5">
        {list?.map((rx) => (
          <li key={rx.id} className="rule-row py-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-semibold text-pen">{fmtDateTime(rx.created_at)}</span>
              <span className="hand text-lg">{rx.author_name}</span>
              <span className="text-sm text-pen">{rx.items.map((i) => i.drug).join(" · ")}</span>
              <button onClick={() => setOpen(open === rx.id ? null : rx.id)} className="link ml-auto">{open === rx.id ? "Ocultar" : "Ver e imprimir"}</button>
            </div>
            {open === rx.id && <RxDocument rx={rx} patient={patient} />}
          </li>
        ))}
        {list?.length === 0 && <li className="py-6 text-pencil">Sin recetas emitidas.</li>}
      </ul>

      {is("odontologo") && (
        <form onSubmit={submit} className="border-t-2 border-print px-5 py-5">
          <h3 className="label-red mb-3">Nueva receta</h3>
          {items.map((it, k) => (
            <div key={k} className="mb-3 grid gap-x-3 gap-y-2 sm:grid-cols-[2fr_1fr_1fr_1fr_2fr_auto]">
              {COLS.map(([key, label]) => (
                <label key={key}><span className="label">{label}</span>
                  <input className="field" value={it[key]} required={key !== "instructions"} onChange={(e) => set(k, key, e.target.value)} />
                </label>
              ))}
              <button type="button" onClick={() => setItems(items.filter((_, j) => j !== k))} disabled={items.length === 1}
                className="self-end pb-2 text-sm font-medium text-red disabled:opacity-30">Quitar</button>
            </div>
          ))}
          <button type="button" onClick={() => setItems([...items, { ...EMPTY }])} className="link">Agregar medicamento</button>
          <label className="mt-4 block"><span className="label">Indicaciones generales</span>
            <textarea rows="2" className="field resize-y" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {error && <p className="error mt-3" role="alert">{error}</p>}
          {override !== null && (
            <label className="mt-3 block"><span className="label-red">Justificación clínica para emitir pese a la alergia</span>
              <input className="field" value={override} onChange={(e) => setOverride(e.target.value)} required />
            </label>
          )}
          <button className="btn mt-4">Firmar y emitir receta</button>
        </form>
      )}
    </section>
  );
}
