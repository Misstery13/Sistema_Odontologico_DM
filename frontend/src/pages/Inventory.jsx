import { useEffect, useState } from "react";
import { api, fmtDateTime, formSubmit, is, money } from "../api.js";

const qty = (n) => Number(n).toLocaleString("es-EC", { maximumFractionDigits: 2 });
const REASONS = { compra: "Compra", consumo: "Consumo", ajuste: "Ajuste" };

// RF-14: stock de insumos, kardex y receta estándar de consumo por procedimiento
export default function Inventory() {
  const [supplies, setSupplies] = useState(null);
  const [moves, setMoves] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [error, setError] = useState("");
  const canMove = is("asistente", "admin");
  const load = () => {
    api("/api/supplies/").then(setSupplies);
    api("/api/stock-movements/").then(setMoves);
  };
  useEffect(() => {
    load();
    api("/api/procedures/").then(setCatalog);
  }, []);

  const submit = formSubmit(async (data) => {
    const sign = data.direction === "salida" ? -1 : 1;
    await api("/api/stock-movements/", {
      method: "POST",
      body: { supply: Number(data.supply), reason: data.reason, quantity: sign * Number(data.quantity), note: data.note },
    });
    load();
  }, setError);
  const low = supplies?.filter((s) => s.low) ?? [];

  return (
    <div className="space-y-6">
      {low.length > 0 && (
        <p role="alert" className="rounded-[3px] bg-red px-4 py-2 text-sm font-semibold text-white">
          Stock bajo: {low.map((s) => `${s.name} (${qty(s.stock)} ${s.unit})`).join(" · ")}
        </p>
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
        <section className="sheet min-w-0">
          <div className="border-b-2 border-print px-5 py-4"><h1 className="text-xl font-semibold">Insumos clínicos</h1></div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left">
              <thead>
                <tr className="border-b border-print">
                  {["Insumo", "Stock", "Mínimo", "Costo unitario", "Valor"].map((h, i) => <th key={h} className={`label px-5 py-2 ${i ? "text-right" : ""}`}>{h}</th>)}
                </tr>
              </thead>
              <tbody>
                {supplies?.map((s) => (
                  <tr key={s.id} className="rule-row">
                    <td className="px-5 py-2.5 text-pen">{s.name}</td>
                    <td className={`px-5 py-2.5 text-right font-semibold ${s.low ? "text-red" : "text-pen"}`}>{qty(s.stock)} {s.unit}</td>
                    <td className="px-5 py-2.5 text-right text-pencil">{qty(s.min_stock)}</td>
                    <td className="px-5 py-2.5 text-right text-pen">{money(s.unit_cost)}</td>
                    <td className="px-5 py-2.5 text-right text-pen">{money(Math.max(0, s.stock * s.unit_cost))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {supplies === null && <p className="px-5 py-6 text-pencil">Cargando inventario…</p>}
        </section>

        {canMove && (
          <form onSubmit={submit} className="sheet border-t-4 border-red">
            <div className="border-b border-dashed border-pencil/50 px-5 py-3"><h2 className="label-red">Movimiento de kardex</h2></div>
            <div className="space-y-4 px-5 py-5">
              <label className="block"><span className="label">Insumo</span>
                <select name="supply" className="field" required>{supplies?.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.unit})</option>)}</select>
              </label>
              <div className="grid grid-cols-2 gap-4">
                <label><span className="label">Tipo</span>
                  <select name="reason" className="field"><option value="compra">Compra</option><option value="ajuste">Ajuste</option></select>
                </label>
                <label><span className="label">Sentido</span>
                  <select name="direction" className="field"><option value="entrada">Entrada</option><option value="salida">Salida</option></select>
                </label>
              </div>
              <label className="block"><span className="label">Cantidad</span><input name="quantity" type="number" step="0.01" min="0.01" className="field" required /></label>
              <label className="block"><span className="label">Nota</span><input name="note" className="field" placeholder="Factura, lote, motivo del ajuste…" /></label>
              <p className="text-sm text-pencil">El consumo se descarga solo al registrar procedimientos según su receta.</p>
              {error && <p className="error" role="alert">{error}</p>}
              <button className="btn w-full">Registrar movimiento</button>
            </div>
          </form>
        )}
      </div>

      <section className="sheet">
        <div className="border-b-2 border-print px-5 py-4"><h2 className="text-xl font-semibold">Kardex</h2></div>
        <div className="max-h-96 overflow-auto">
          <table className="w-full min-w-[640px] text-left">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b border-print">
                {["Fecha", "Insumo", "Movimiento", "Cantidad", "Usuario", "Detalle"].map((h) => <th key={h} className="label px-5 py-2">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {moves.map((m) => (
                <tr key={m.id} className="rule-row text-sm">
                  <td className="px-5 py-2 text-pen">{fmtDateTime(m.created_at)}</td>
                  <td className="px-5 py-2 text-pen">{m.supply_name}</td>
                  <td className="px-5 py-2 text-pen">{REASONS[m.reason]}</td>
                  <td className={`px-5 py-2 font-semibold ${m.quantity < 0 ? "text-red" : "text-pen"}`}>{m.quantity > 0 ? "+" : ""}{qty(m.quantity)}</td>
                  <td className="px-5 py-2 text-pen">{m.user_name}</td>
                  <td className="px-5 py-2 text-pencil">{m.treatment ? `Tratamiento #${m.treatment}` : m.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="sheet">
        <div className="border-b-2 border-print px-5 py-4"><h2 className="text-xl font-semibold">Catálogo de procedimientos y receta de consumo</h2></div>
        <ul className="grid gap-x-8 px-5 sm:grid-cols-2">
          {catalog.map((p) => (
            <li key={p.id} className="rule-row py-3">
              <div className="flex justify-between gap-3">
                <span className="font-semibold text-pen"><span className="text-pencil">{p.code}</span> · {p.name}</span>
                <span className="text-pen">{money(p.fee)}{Number(p.lab_cost) > 0 && <span className="text-pencil"> + lab. {money(p.lab_cost)}</span>}</span>
              </div>
              <p className="text-sm text-pencil">{p.recipe.length ? p.recipe.map((r) => `${r.supply_name} ${qty(r.quantity)} ${r.unit}`).join(" · ") : "Sin receta de consumo"}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
