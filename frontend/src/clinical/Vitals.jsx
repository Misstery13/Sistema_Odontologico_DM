import { useEffect, useState } from "react";
import { api, fmtDateTime, formSubmit } from "../api.js";

const FIELDS = [
  ["systolic", "Sistólica", "mmHg", true, 50, 260],
  ["diastolic", "Diastólica", "mmHg", true, 30, 160],
  ["heart_rate", "Pulso", "lpm", true, 30, 220],
  ["respiratory_rate", "Respiración", "rpm", false, 5, 60],
  ["temperature", "Temperatura", "°C", false, 30, 43],
  ["spo2", "SpO₂", "%", false, 50, 100],
  ["glucose", "Glucemia", "mg/dL", false, 20, 600],
];

// signos vitales previos a la atención (rol asistente dental); las alertas condicionan anestesia y procedimientos
export default function Vitals({ patient }) {
  const [items, setItems] = useState(null);
  const [fresh, setFresh] = useState(null);
  const [error, setError] = useState("");
  const load = () => api(`/api/vitals/?patient=${patient.id}`).then(setItems);
  useEffect(() => {
    load();
  }, [patient.id]);

  const submit = formSubmit(async (data) => {
    const body = { patient: patient.id, notes: data.notes };
    FIELDS.forEach(([k]) => data[k] !== "" && (body[k] = Number(data[k])));
    const v = await api("/api/vitals/", { method: "POST", body });
    setFresh(v.id);
    load();
  }, setError);

  return (
    <section className="sheet">
      <div className="border-b-2 border-print px-5 py-4"><h2 className="text-xl font-semibold">Signos vitales</h2></div>
      <form onSubmit={submit} className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-rule px-5 py-4 sm:grid-cols-4 lg:grid-cols-8">
        {FIELDS.map(([name, label, unit, required, min, max]) => (
          <label key={name}><span className="label">{label} <span className="normal-case tracking-normal text-pencil">{unit}</span>{required && <span className="text-red"> *</span>}</span>
            <input name={name} type="number" step={name === "temperature" ? "0.1" : "1"} min={min} max={max} required={required} className="field" inputMode="decimal" />
          </label>
        ))}
        <label className="col-span-2 sm:col-span-3 lg:col-span-1"><span className="label">Nota</span><input name="notes" className="field" /></label>
        {error && <p className="error col-span-full" role="alert">{error}</p>}
        <button className="btn col-span-full sm:col-span-1 sm:col-start-4 lg:col-start-8">Registrar</button>
      </form>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead>
            <tr className="border-b border-print">
              {["Fecha", "Presión", "Pulso", "Resp.", "Temp.", "SpO₂", "Glucemia", "Registró", "Alertas"].map((h) => <th key={h} className="label px-4 py-2">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {items?.map((v) => (
              <tr key={v.id} className={`rule-row ${v.id === fresh ? "write-in" : ""}`}>
                <td className="px-4 py-2 text-pen">{fmtDateTime(v.created_at)}</td>
                <td className="px-4 py-2 font-semibold text-pen">{v.systolic}/{v.diastolic}</td>
                <td className="px-4 py-2 text-pen">{v.heart_rate}</td>
                <td className="px-4 py-2 text-pen">{v.respiratory_rate ?? "—"}</td>
                <td className="px-4 py-2 text-pen">{v.temperature ?? "—"}</td>
                <td className="px-4 py-2 text-pen">{v.spo2 ?? "—"}</td>
                <td className="px-4 py-2 text-pen">{v.glucose ?? "—"}</td>
                <td className="px-4 py-2 text-pencil">{v.recorded_by_name}</td>
                <td className="px-4 py-2 font-medium text-red">{v.alerts.join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items?.length === 0 && <p className="px-5 py-6 text-pencil">Sin registros de signos vitales.</p>}
    </section>
  );
}
