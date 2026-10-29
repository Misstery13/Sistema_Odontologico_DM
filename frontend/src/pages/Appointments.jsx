import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formSubmit } from "../api.js";

const today = () => new Date().toLocaleDateString("sv"); // YYYY-MM-DD en hora local
const STATUS_STYLE = { programada: "bg-teal-100 text-teal-800", completada: "bg-slate-200 text-slate-700", cancelada: "bg-red-100 text-red-700 line-through" };

export default function Appointments() {
  const [date, setDate] = useState(today);
  const [items, setItems] = useState([]);
  const [patients, setPatients] = useState([]);
  const [dentists, setDentists] = useState([]);
  const [error, setError] = useState("");

  const load = () => api(`/api/appointments/?date=${date}`).then(setItems);
  useEffect(() => {
    load();
  }, [date]);
  useEffect(() => {
    api("/api/patients/").then(setPatients);
    api("/api/dentists/").then(setDentists);
  }, []);

  const submit = formSubmit(async (data) => {
    await api("/api/appointments/", { method: "POST", body: data });
    setDate(data.start.slice(0, 10));
    load();
  }, setError);

  const setStatus = async (a, status) => {
    try {
      await api(`/api/appointments/${a.id}/`, { method: "PATCH", body: { status } });
      load();
    } catch (e) {
      setError(e.message);
    }
  };

  const time = (iso) => new Date(iso).toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <section className="card md:col-span-2">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-lg font-semibold">Agenda</h2>
          <input type="date" className="input ml-auto max-w-44" value={date} onChange={(e) => setDate(e.target.value)} />
        </div>
        <ul className="divide-y divide-slate-100 text-sm">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="w-24 font-mono">{time(a.start)} · {a.minutes}m</span>
              <Link to={`/pacientes/${a.patient}`} className="text-teal-700 hover:underline">{a.patient_name}</Link>
              <span className="text-slate-500">con {a.dentist_name}{a.reason && ` — ${a.reason}`}</span>
              <span className={`ml-auto rounded px-2 py-0.5 text-xs ${STATUS_STYLE[a.status]}`}>{a.status}</span>
              {a.status === "programada" && (
                <>
                  <button onClick={() => setStatus(a, "completada")} className="text-xs text-teal-700 hover:underline">Completar</button>
                  <button onClick={() => setStatus(a, "cancelada")} className="text-xs text-red-600 hover:underline">Cancelar</button>
                </>
              )}
            </li>
          ))}
          {!items.length && <li className="py-4 text-center text-slate-400">Sin citas este día</li>}
        </ul>
      </section>

      <form onSubmit={submit} className="card space-y-2">
        <h2 className="text-lg font-semibold">Nueva cita</h2>
        <div>
          <label className="label" htmlFor="patient">Paciente</label>
          <select id="patient" name="patient" className="input" required>
            {patients.map((p) => <option key={p.id} value={p.id}>{p.last_name}, {p.first_name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="dentist">Odontólogo</label>
          <select id="dentist" name="dentist" className="input" required>
            {dentists.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label" htmlFor="start">Fecha y hora</label>
          <input id="start" name="start" type="datetime-local" className="input" required />
        </div>
        <div>
          <label className="label" htmlFor="minutes">Duración (min)</label>
          <input id="minutes" name="minutes" type="number" min="5" max="480" step="5" defaultValue="30" className="input" />
        </div>
        <div>
          <label className="label" htmlFor="reason">Motivo</label>
          <input id="reason" name="reason" className="input" />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="btn w-full">Agendar</button>
      </form>
    </div>
  );
}
