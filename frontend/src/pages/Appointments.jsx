import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, formSubmit, getSession } from "../api.js";

// Agenda en vivo: el servicio de caja avisa por WebSocket cuando cambia una cita de la clínica y la vista se recarga.
// El aviso no trae datos: la agenda se vuelve a pedir a Django, que aplica permisos y auditoría.
function useLiveAgenda(onChange) {
  const [live, setLive] = useState(false);
  const callback = useRef(onChange);
  callback.current = onChange;
  useEffect(() => {
    let ws, retry;
    let stopped = false;
    const connect = () => {
      ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/pay/ws`);
      ws.onopen = () => ws.send(JSON.stringify({ token: getSession()?.token })); // nunca en la URL: quedaría en los logs
      ws.onmessage = (e) => {
        if (JSON.parse(e.data).type === "ready") setLive(true);
        callback.current(); // también al reconectar: recupera lo que cambió mientras estuvo desconectada
      };
      ws.onclose = (e) => {
        setLive(false);
        if (!stopped && e.code !== 4001) retry = setTimeout(connect, 5000); // 4001: sesión cerrada, no reintentar
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws.close();
    };
  }, []);
  return live;
}

const iso = (d) => d.toLocaleDateString("sv"); // YYYY-MM-DD en hora local
const shift = (date, days) => {
  const d = new Date(`${date}T12:00`);
  d.setDate(d.getDate() + days);
  return iso(d);
};
const monday = (date) => shift(date, -((new Date(`${date}T12:00`).getDay() + 6) % 7));
const time = (s) => new Date(s).toLocaleTimeString("es-EC", { hour: "2-digit", minute: "2-digit" });

// RF-10: ciclo de vida del turno
const STATUS = {
  programado: "Programado",
  confirmado: "Confirmado",
  en_espera: "En sala de espera",
  en_atencion: "En atención",
  atendido: "Atendido",
  cancelado: "Cancelado",
  no_asistio: "No asistió",
};
const INACTIVE = ["cancelado", "no_asistio"];
const statusText = (s) =>
  INACTIVE.includes(s) ? "text-red" : s === "atendido" ? "text-pencil" : s === "en_atencion" || s === "en_espera" ? "font-semibold text-pen" : "text-pen";

const localInput = (iso) => {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

// cambia fecha, hora, duración, consultorio u odontólogo; vuelve a validar choques (RN-03) y avisa al paciente
function Reschedule({ a, chairs, dentists, onDone }) {
  const [error, setError] = useState("");
  const submit = formSubmit(async (d) => {
    await api(`/api/appointments/${a.id}/`, {
      method: "PATCH",
      body: { start: d.start, minutes: Number(d.minutes), chair: Number(d.chair), dentist: Number(d.dentist) },
    });
    onDone(d.start.slice(0, 10));
  }, setError);
  return (
    <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-[1fr_90px_1fr_1fr_auto]">
      <label><span className="label">Nueva fecha y hora</span><input name="start" type="datetime-local" defaultValue={localInput(a.start)} className="field" required /></label>
      <label><span className="label">Minutos</span><input name="minutes" type="number" min="5" max="480" step="5" defaultValue={a.minutes} className="field" /></label>
      <label><span className="label">Consultorio</span>
        <select name="chair" defaultValue={a.chair} className="field">{chairs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
      </label>
      <label><span className="label">Odontólogo</span>
        <select name="dentist" defaultValue={a.dentist} className="field">{dentists.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
      </label>
      <button className="btn">Guardar y avisar</button>
      {error && <p className="error sm:col-span-5" role="alert">{error}</p>}
    </form>
  );
}

export default function Appointments() {
  const [view, setView] = useState("dia");
  const [date, setDate] = useState(() => iso(new Date()));
  const [filters, setFilters] = useState({ chair: "", dentist: "" });
  const [items, setItems] = useState(null);
  const [patients, setPatients] = useState([]);
  const [dentists, setDentists] = useState([]);
  const [chairs, setChairs] = useState([]);
  const [patient, setPatient] = useState("");
  const [planned, setPlanned] = useState([]); // RF-08: ítems aprobados del presupuesto del paciente
  const [fresh, setFresh] = useState(null);
  const [moving, setMoving] = useState(null); // cita que se está reprogramando
  const [error, setError] = useState("");

  const from = view === "dia" ? date : monday(date);
  const to = view === "dia" ? date : shift(from, 6);
  const load = () => {
    const q = new URLSearchParams({ from, to, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) });
    return api(`/api/appointments/?${q}`).then(setItems);
  };
  useEffect(() => {
    load();
  }, [from, to, filters]);
  const live = useLiveAgenda(load);
  useEffect(() => {
    setPlanned([]);
    if (patient) api(`/api/budgets/pending/?patient=${patient}`).then(setPlanned);
  }, [patient]);
  useEffect(() => {
    api("/api/patients/").then((list) => {
      setPatients(list);
      if (list.length) setPatient(String(list[0].id));
    });
    api("/api/dentists/").then(setDentists);
    api("/api/chairs/").then((l) => setChairs(l.filter((c) => c.active)));
  }, []);

  const submit = formSubmit(async (data) => {
    if (!data.budget_item) delete data.budget_item;
    const a = await api("/api/appointments/", { method: "POST", body: data });
    api(`/api/budgets/pending/?patient=${patient}`).then(setPlanned);
    setFresh(a.id);
    const day = data.start.slice(0, 10);
    if (day >= from && day <= to) load();
    else setDate(day);
  }, setError);

  const setStatus = async (a, status) => {
    setError("");
    try {
      await api(`/api/appointments/${a.id}/`, { method: "PATCH", body: { status } });
      load();
    } catch (e) {
      setError(e.message);
      load();
    }
  };

  const title =
    view === "dia"
      ? new Date(`${date}T12:00`).toLocaleDateString("es-EC", { weekday: "long", day: "numeric", month: "long" })
      : `Semana del ${new Date(`${from}T12:00`).toLocaleDateString("es-EC", { day: "numeric", month: "long" })}`;
  const step = view === "dia" ? 1 : 7;
  const active = items?.filter((a) => !INACTIVE.includes(a.status)).length ?? 0;
  const tab = (v) => `px-3 py-1 text-sm font-semibold ${view === v ? "bg-pen text-white" : "text-pen hover:bg-rule/50"}`;

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
      <section className="sheet min-w-0">
        <div className="flex flex-wrap items-center gap-3 border-b-2 border-print px-5 py-4">
          <h1 className="text-xl font-semibold first-letter:uppercase">{title}</h1>
          <span className="text-sm text-pencil">{active} {active === 1 ? "cita" : "citas"}</span>
          {live && (
            <span className="flex items-center gap-1.5 text-sm text-pencil" title="Los cambios de otros usuarios aparecen sin recargar">
              <span className="size-2 rounded-full bg-pen" aria-hidden="true" />En vivo
            </span>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <div className="flex rounded-[3px] border border-pen" role="group" aria-label="Vista">
              <button onClick={() => setView("dia")} className={tab("dia")} aria-pressed={view === "dia"}>Día</button>
              <button onClick={() => setView("semana")} className={tab("semana")} aria-pressed={view === "semana"}>Semana</button>
            </div>
            <button onClick={() => setDate(shift(date, -step))} className="link">Anterior</button>
            <button onClick={() => setDate(iso(new Date()))} className="link">Hoy</button>
            <button onClick={() => setDate(shift(date, step))} className="link">Siguiente</button>
            <input type="date" className="field w-36" value={date} onChange={(e) => e.target.value && setDate(e.target.value)} aria-label="Ir a fecha" />
          </div>
        </div>
        <div className="flex flex-wrap gap-4 border-b border-print px-5 py-3">
          <label className="w-44"><span className="label">Consultorio</span>
            <select className="field" value={filters.chair} onChange={(e) => setFilters({ ...filters, chair: e.target.value })}>
              <option value="">Todos</option>
              {chairs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label className="w-52"><span className="label">Odontólogo</span>
            <select className="field" value={filters.dentist} onChange={(e) => setFilters({ ...filters, dentist: e.target.value })}>
              <option value="">Todos</option>
              {dentists.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
        </div>
        {error && <p className="error px-5 pt-3" role="alert">{error}</p>}

        {view === "dia" ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead>
                <tr className="border-b border-print">
                  <th className="label w-24 px-5 py-2">Hora</th>
                  <th className="label px-3 py-2">Paciente</th>
                  <th className="label px-3 py-2">Odontólogo · consultorio</th>
                  <th className="label px-3 py-2">Motivo</th>
                  <th className="label px-5 py-2">Estado</th>
                </tr>
              </thead>
              <tbody>
                {items?.map((a) => {
                  const off = INACTIVE.includes(a.status);
                  return (
                    <Fragment key={a.id}>
                    <tr className="rule-row">
                      <td className="px-5 py-2.5">
                        <span className={`font-semibold ${off ? "text-pencil" : "text-pen"}`}>{time(a.start)}</span>
                        <span className="ml-1.5 text-sm text-pencil">{a.minutes}′</span>
                      </td>
                      <td className="px-3 py-2.5">
                        <Link to={`/pacientes/${a.patient}`}
                          className={`inline-block font-medium hover:underline ${a.id === fresh ? "write-in" : ""} ${off ? "text-pencil line-through decoration-red decoration-2" : "text-pen"}`}>
                          {a.patient_name}
                        </Link>
                      </td>
                      <td className="px-3 py-2.5 text-pen">{a.dentist_name}<span className="text-pencil"> · {a.chair_name || "—"}</span></td>
                      <td className="px-3 py-2.5 text-pen">{a.reason || <span className="text-pencil">—</span>}</td>
                      <td className="px-5 py-2">
                        <select value={a.status} onChange={(e) => setStatus(a, e.target.value)} aria-label={`Estado de la cita de ${a.patient_name}`}
                          className={`field w-44 py-1 text-sm ${statusText(a.status)}`}>
                          {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        {!off && a.status !== "atendido" && (
                          <button onClick={() => setMoving(moving === a.id ? null : a.id)} className="link mt-1 block text-xs">
                            {moving === a.id ? "Cancelar" : "Reprogramar"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {moving === a.id && (
                      <tr className="rule-row bg-rule/20">
                        <td colSpan="5" className="px-5 py-3">
                          <Reschedule a={a} chairs={chairs} dentists={dentists} onDone={(day) => { setMoving(null); setFresh(a.id); day === date ? load() : setDate(day); }} />
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {items === null && <p className="px-5 py-6 text-pencil">Cargando agenda…</p>}
            {items?.length === 0 && <p className="px-5 py-8 text-pencil">Día libre: no hay citas con estos filtros.</p>}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-7">
            {[0, 1, 2, 3, 4, 5, 6].map((i) => {
              const day = shift(from, i);
              const list = items?.filter((a) => iso(new Date(a.start)) === day) ?? [];
              return (
                <div key={day} className="min-h-40 border-b border-rule px-3 py-3 lg:border-r">
                  <button onClick={() => { setDate(day); setView("dia"); }}
                    className={`label mb-2 hover:text-pen ${day === iso(new Date()) ? "text-red" : ""}`}>
                    {new Date(`${day}T12:00`).toLocaleDateString("es-EC", { weekday: "short", day: "numeric" })}
                  </button>
                  <ul className="space-y-2">
                    {list.map((a) => (
                      <li key={a.id} className={`text-sm ${INACTIVE.includes(a.status) ? "text-pencil line-through decoration-red" : ""}`}>
                        <span className="font-semibold text-pen">{time(a.start)}</span>{" "}
                        <Link to={`/pacientes/${a.patient}`} className="text-pen hover:underline">{a.patient_name}</Link>
                        <span className="block text-xs text-pencil">{a.chair_name} · {STATUS[a.status]}</span>
                      </li>
                    ))}
                    {!list.length && <li className="text-sm text-pencil">—</li>}
                  </ul>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <form onSubmit={submit} className="sheet border-t-4 border-red">
        <div className="border-b border-dashed border-pencil/50 px-5 py-3">
          <h2 className="label-red">Tarjeta de cita</h2>
        </div>
        <div className="space-y-4 px-5 py-5">
          <div>
            <label className="label" htmlFor="patient">Paciente</label>
            <select id="patient" name="patient" className="field" required value={patient} onChange={(e) => setPatient(e.target.value)}>
              {patients.map((p) => <option key={p.id} value={p.id}>{p.last_name}, {p.first_name}</option>)}
            </select>
          </div>
          {planned.length > 0 && (
            <div>
              <label className="label" htmlFor="budget_item">Del presupuesto aprobado</label>
              <select id="budget_item" name="budget_item" className="field" defaultValue="">
                <option value="">— Cita sin presupuesto —</option>
                {planned.map((i) => (
                  <option key={i.id} value={i.id}>
                    Fase {i.phase} · {i.procedure_name}{i.tooth ? ` · pieza ${i.tooth}` : ""}{i.scheduled ? " (ya agendado)" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label" htmlFor="dentist">Odontólogo</label>
              <select id="dentist" name="dentist" className="field" required>
                {dentists.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="chair">Consultorio</label>
              <select id="chair" name="chair" className="field" required>
                {chairs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-[1fr_96px] gap-4">
            <div>
              <label className="label" htmlFor="start">Fecha y hora</label>
              <input id="start" name="start" type="datetime-local" className="field" required />
            </div>
            <div>
              <label className="label" htmlFor="minutes">Minutos</label>
              <input id="minutes" name="minutes" type="number" min="5" max="480" step="5" defaultValue="30" className="field" />
            </div>
          </div>
          <div>
            <label className="label" htmlFor="reason">Motivo</label>
            <input id="reason" name="reason" className="field" placeholder="Limpieza, control, dolor… (o el del presupuesto)" />
          </div>
          <p className="text-sm text-pencil">Al agendar se envía la confirmación al paciente; los recordatorios salen 48 h y 24 h antes.</p>
          <button className="btn w-full">Agendar cita</button>
        </div>
      </form>
    </div>
  );
}
