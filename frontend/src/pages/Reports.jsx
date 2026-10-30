import { useEffect, useState } from "react";
import { api, money } from "../api.js";

const STATUS = { programado: "Programado", confirmado: "Confirmado", en_espera: "En sala de espera", en_atencion: "En atención", atendido: "Atendido", cancelado: "Cancelado", no_asistio: "No asistió" };
const KINDS = { pct: "% del precio", fixed: "Monto fijo por procedimiento", pct_net: "% tras laboratorio y materiales" };
const firstOfMonth = () => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).toLocaleDateString("sv"); };

const Table = ({ head, rows, empty }) => (
  <div className="overflow-x-auto">
    <table className="w-full min-w-[480px] text-left text-sm">
      <thead><tr className="border-b border-print">{head.map((h, i) => <th key={h} className={`label px-5 py-2 ${i ? "text-right" : ""}`}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, k) => (
          <tr key={k} className="rule-row">{r.map((c, i) => <td key={i} className={`px-5 py-2 text-pen ${i ? "text-right" : ""}`}>{c}</td>)}</tr>
        ))}
      </tbody>
    </table>
    {!rows.length && <p className="px-5 py-4 text-sm text-pencil">{empty}</p>}
  </div>
);
const Card = ({ title, children, className = "" }) => (
  <section className={`sheet ${className}`}>
    <div className="border-b-2 border-print px-5 py-3"><h2 className="font-semibold">{title}</h2></div>
    {children}
  </section>
);

// RF-13 liquidación de honorarios por regla configurable por odontólogo
function CommissionRules({ onSaved }) {
  const [rules, setRules] = useState([]);
  const [dentists, setDentists] = useState([]);
  const [error, setError] = useState("");
  const load = () => api("/api/commission-rules/").then(setRules);
  useEffect(() => {
    load();
    api("/api/dentists/").then(setDentists).catch(() => setDentists([]));
  }, []);

  const save = async (e, dentist, rule) => {
    e.preventDefault();
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await (rule
        ? api(`/api/commission-rules/${rule.id}/`, { method: "PATCH", body: data })
        : api("/api/commission-rules/", { method: "POST", body: { ...data, dentist } }));
      load();
      onSaved();
    } catch (err) {
      setError(err.message);
    }
  };
  const ids = [...new Set([...rules.map((r) => r.dentist), ...dentists.map((d) => d.id)])];
  const name = (id) => dentists.find((d) => d.id === id)?.name || rules.find((r) => r.dentist === id)?.dentist_name;

  return (
    <Card title="Reglas de honorarios">
      <ul className="px-5">
        {ids.map((id) => {
          const rule = rules.find((r) => r.dentist === id);
          return (
            <li key={id} className="rule-row py-3">
              <form key={`${rule?.kind}-${rule?.value}`} onSubmit={(e) => save(e, id, rule)} className="flex flex-wrap items-end gap-3">
                <span className="w-40 font-medium text-pen">{name(id)}</span>
                <label className="w-80"><span className="label">Regla</span>
                  <select name="kind" defaultValue={rule?.kind || "pct"} className="field">
                    {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="w-28"><span className="label">Valor</span><input name="value" type="number" step="0.01" min="0" defaultValue={rule?.value || ""} className="field" required /></label>
                <button className="link pb-2">{rule ? "Guardar" : "Crear regla"}</button>
              </form>
            </li>
          );
        })}
      </ul>
      {error && <p className="error px-5 pb-3" role="alert">{error}</p>}
    </Card>
  );
}

export default function Reports() {
  const [range, setRange] = useState({ from: firstOfMonth(), to: new Date().toLocaleDateString("sv") });
  const [data, setData] = useState(null);
  const [income, setIncome] = useState([]);
  const [error, setError] = useState("");
  const load = () => {
    setError("");
    const q = `from=${range.from}&to=${range.to}`;
    api(`/api/reports/?${q}`).then(setData).catch((e) => setError(e.message));
    api(`/pay/reports/income?${q}`).then(setIncome).catch(() => setIncome([]));
  };
  useEffect(load, [range]);

  const totalIncome = income.reduce((s, i) => s + i.amount, 0);
  const totalCommission = data?.commissions.reduce((s, c) => s + c.commission, 0) ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <h1 className="mr-auto text-xl font-semibold">Reportes de gestión</h1>
        {["from", "to"].map((k) => (
          <label key={k} className="w-40"><span className="label">{k === "from" ? "Desde" : "Hasta"}</span>
            <input type="date" className="field" value={range[k]} onChange={(e) => e.target.value && setRange({ ...range, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {data && (
        <>
          <dl className="sheet grid grid-cols-2 gap-4 px-5 py-4 md:grid-cols-4">
            {[
              ["Producción", money(data.production)],
              ["Cobrado", money(totalIncome)],
              ["Honorarios a liquidar", money(totalCommission)],
              ["Ausentismo", data.no_show_rate === null ? "—" : `${data.no_show_rate}%`],
            ].map(([k, v]) => <div key={k}><dt className="label">{k}</dt><dd className="hand text-3xl">{v}</dd></div>)}
          </dl>

          <Card title="Liquidación de honorarios">
            <Table head={["Odontólogo", "Regla", "Procedimientos", "Producción", "Laboratorio", "Materiales", "Honorario"]}
              rows={data.commissions.map((c) => [c.dentist, c.rule, c.treatments, money(c.production), money(c.lab), money(c.materials), <b key="c">{money(c.commission)}</b>])}
              empty="Sin procedimientos realizados en el período." />
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Procedimientos más realizados">
              <Table head={["Procedimiento", "Cantidad", "Producción"]} rows={data.top_procedures.map((p) => [p.procedure, p.count, money(p.production)])} empty="Sin datos." />
            </Card>
            <Card title="Ingresos por método de pago">
              <Table head={["Método", "Cobros", "Monto"]} rows={income.map((i) => [i.method, i.count, money(i.amount)])} empty="Sin cobros en el período." />
            </Card>
            <Card title="Citas por estado">
              <Table head={["Estado", "Citas"]} rows={Object.entries(data.appointments).map(([k, v]) => [STATUS[k] || k, v])} empty="Sin citas." />
              <p className="px-5 py-3 text-sm text-pencil">Pacientes nuevos en el período: <b className="text-pen">{data.new_patients}</b></p>
            </Card>
            <Card title="Consumo de insumos">
              <Table head={["Insumo", "Consumido"]} rows={data.consumption.map((c) => [c.supply__name, `${Number(c.quantity).toLocaleString("es-EC")} ${c.supply__unit}`])} empty="Sin consumo registrado." />
              <div className="grid gap-x-6 border-t border-rule sm:grid-cols-2">
                <Table head={["Consultorio", "Costo"]} rows={data.consumption_by_location.map((c) => [c.location, money(c.cost)])} empty="—" />
                <Table head={["Profesional", "Costo"]} rows={data.consumption_by_dentist.map((c) => [c.dentist, money(c.cost)])} empty="—" />
              </div>
              {data.low_stock.length > 0 && (
                <p className="px-5 py-3 text-sm font-medium text-red">Stock bajo: {data.low_stock.map((s) => s.name).join(", ")}</p>
              )}
            </Card>
          </div>
          <CommissionRules onSaved={load} />
        </>
      )}
    </div>
  );
}
