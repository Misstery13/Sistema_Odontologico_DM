import { useEffect, useState } from "react";
import { api, formSubmit, is, money } from "../api.js";

const fmtDay = (d) => new Date(`${d}T12:00`).toLocaleDateString("es-EC", { weekday: "long", day: "numeric", month: "long" });
const Diff = ({ value }) =>
  value === 0 ? <span className="text-pen">Cuadra</span>
    : <span className={value < 0 ? "font-semibold text-red" : "font-semibold text-pen"}>{value < 0 ? "Faltante" : "Sobrante"} {money(Math.abs(value))}</span>;

export default function Cash() {
  return is("recepcion") ? <BlindClosing /> : <Closings />;
}

// RN-02: la recepción ingresa el conteo físico sin ver el total del sistema; el total aparece solo después
function BlindClosing() {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const submit = formSubmit(async (data) => {
    setResult(await api("/pay/cash-closings", { method: "POST", body: { counted: Number(data.counted) } }));
  }, setError);

  return (
    <section className="sheet mx-auto max-w-lg border-t-4 border-red">
      <div className="border-b border-dashed border-pencil/50 px-6 py-3">
        <h1 className="label-red">Cierre de caja · {fmtDay(new Date().toLocaleDateString("sv"))}</h1>
      </div>
      {result ? (
        <div className="px-6 py-6">
          <p className="hand text-2xl">Caja cerrada</p>
          <dl className="mt-4">
            {[["Efectivo contado", money(result.counted)], ["Efectivo según sistema", money(result.expected)]].map(([k, v]) => (
              <div key={k} className="rule-row flex justify-between py-2"><dt className="label">{k}</dt><dd className="font-medium text-pen">{v}</dd></div>
            ))}
            <div className="flex justify-between border-t-2 border-print py-2"><dt className="label">Diferencia</dt><dd><Diff value={result.difference} /></dd></div>
          </dl>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4 px-6 py-6">
          <p className="text-sm text-pencil">Cuenta el efectivo de la caja e ingresa el total. El sistema mostrará su cifra solo después de registrar tu conteo.</p>
          <label className="block">
            <span className="label">Efectivo contado $</span>
            <input name="counted" type="number" step="0.01" min="0" className="field text-2xl" required autoFocus />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="btn w-full">Registrar conteo y cerrar caja</button>
        </form>
      )}
    </section>
  );
}

function Closings() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api("/pay/cash-closings").then(setRows);
  }, []);
  return (
    <section className="sheet">
      <div className="border-b-2 border-print px-5 py-4"><h1 className="text-xl font-semibold">Cierres de caja</h1></div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left">
          <thead>
            <tr className="border-b border-print">
              {["Día", "Cajero", "Contado", "Sistema", "Diferencia"].map((h) => <th key={h} className="label px-5 py-2">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.day} className="rule-row">
                <td className="px-5 py-2.5 text-pen first-letter:uppercase">{fmtDay(r.day)}</td>
                <td className="px-5 py-2.5 text-pen">{r.user}</td>
                <td className="px-5 py-2.5 text-pen">{money(r.counted)}</td>
                <td className="px-5 py-2.5 text-pen">{money(r.expected)}</td>
                <td className="px-5 py-2.5"><Diff value={r.difference} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows === null && <p className="px-5 py-6 text-pencil">Cargando cierres…</p>}
      {rows?.length === 0 && <p className="px-5 py-8 text-pencil">Aún no hay cierres de caja.</p>}
    </section>
  );
}
