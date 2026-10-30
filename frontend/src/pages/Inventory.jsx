import { useEffect, useState } from "react";
import { api, fmtDateTime, formSubmit, is, money } from "../api.js";

const qty = (n) => Number(n || 0).toLocaleString("es-EC", { maximumFractionDigits: 2 });
const REASONS = { compra: "Compra", consumo: "Consumo", ajuste: "Ajuste", traslado: "Traslado" };
const loc = (v) => (v === "bodega" || v === "" ? null : Number(v)); // la bodega central es la ubicación sin consultorio

// objetivo 2.2: inventario centralizado por ubicación (bodega y consultorios) y por profesional (consumo en Reportes)
export default function Inventory() {
  const [inv, setInv] = useState(null);
  const [moves, setMoves] = useState([]);
  const [supplies, setSupplies] = useState([]);
  const [error, setError] = useState("");
  const [tError, setTError] = useState("");
  const [ok, setOk] = useState("");
  const canMove = is("asistente", "admin");
  const load = () => {
    api("/api/supplies/by-location/").then(setInv);
    api("/api/stock-movements/").then(setMoves);
    api("/api/supplies/").then(setSupplies);
  };
  useEffect(() => {
    load();
  }, []);

  const movement = formSubmit(async (d) => {
    setOk("");
    const sign = d.direction === "salida" ? -1 : 1;
    await api("/api/stock-movements/", {
      method: "POST",
      body: { supply: Number(d.supply), chair: loc(d.location), reason: d.reason, quantity: sign * Number(d.quantity), note: d.note },
    });
    setOk("Movimiento registrado");
    load();
  }, setError);
  const transfer = formSubmit(async (d) => {
    setOk("");
    const r = await api("/api/stock-movements/transfer/", {
      method: "POST",
      body: { supply: Number(d.supply), from_chair: loc(d.from), to_chair: loc(d.to), quantity: Number(d.quantity) },
    });
    setOk(r.detail);
    load();
  }, setTError);

  const locations = inv?.locations ?? [];
  const low = inv?.supplies.filter((s) => s.low) ?? [];
  const LocationSelect = ({ name, label }) => (
    <label><span className="label">{label}</span>
      <select name={name} className="field" defaultValue="bodega">{locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
    </label>
  );
  const SupplySelect = () => (
    <label className="col-span-2"><span className="label">Insumo</span>
      <select name="supply" className="field" required>{supplies.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.unit})</option>)}</select>
    </label>
  );

  return (
    <div className="space-y-6">
      {low.length > 0 && (
        <p role="alert" className="rounded-[3px] bg-red px-4 py-2 text-sm font-semibold text-white">
          Stock bajo: {low.map((s) => `${s.name} (${qty(s.total)} ${s.unit})`).join(" · ")}
        </p>
      )}
      <section className="sheet min-w-0">
        <div className="border-b-2 border-print px-5 py-4"><h1 className="text-xl font-semibold">Existencias por ubicación</h1></div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left">
            <thead>
              <tr className="border-b border-print">
                <th className="label px-5 py-2">Insumo</th>
                {locations.map((l) => <th key={l.id} className="label px-3 py-2 text-right">{l.name}</th>)}
                <th className="label px-3 py-2 text-right">Total</th>
                <th className="label px-5 py-2 text-right">Mínimo</th>
              </tr>
            </thead>
            <tbody>
              {inv?.supplies.map((s) => (
                <tr key={s.id} className="rule-row">
                  <td className="px-5 py-2.5 text-pen">{s.name} <span className="text-sm text-pencil">({s.unit})</span></td>
                  {locations.map((l) => <td key={l.id} className="px-3 py-2.5 text-right text-pen">{qty(s.by_location[l.id])}</td>)}
                  <td className={`px-3 py-2.5 text-right font-semibold ${s.low ? "text-red" : "text-pen"}`}>{qty(s.total)}</td>
                  <td className="px-5 py-2.5 text-right text-pencil">{qty(s.min_stock)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {inv === null && <p className="px-5 py-6 text-pencil">Cargando inventario…</p>}
      </section>

      {canMove && (
        <div className="grid items-start gap-6 lg:grid-cols-2">
          <form onSubmit={movement} className="sheet border-t-4 border-red">
            <div className="border-b border-dashed border-pencil/50 px-5 py-3"><h2 className="label-red">Compra o ajuste</h2></div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-4 px-5 py-5">
              <SupplySelect />
              <LocationSelect name="location" label="Ubicación" />
              <label><span className="label">Tipo</span>
                <select name="reason" className="field"><option value="compra">Compra (entrada)</option><option value="ajuste">Ajuste</option></select>
              </label>
              <label><span className="label">Sentido</span>
                <select name="direction" className="field"><option value="entrada">Entrada</option><option value="salida">Salida</option></select>
              </label>
              <label><span className="label">Cantidad</span><input name="quantity" type="number" step="0.01" min="0.01" className="field" required /></label>
              <label className="col-span-2"><span className="label">Nota</span><input name="note" className="field" placeholder="Factura, lote, motivo del ajuste…" /></label>
              {error && <p className="error col-span-2" role="alert">{error}</p>}
              <button className="btn col-span-2">Registrar movimiento</button>
            </div>
          </form>
          <form onSubmit={transfer} className="sheet border-t-4 border-red">
            <div className="border-b border-dashed border-pencil/50 px-5 py-3"><h2 className="label-red">Traslado entre ubicaciones</h2></div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-4 px-5 py-5">
              <SupplySelect />
              <LocationSelect name="from" label="Desde" />
              <LocationSelect name="to" label="Hacia" />
              <label><span className="label">Cantidad</span><input name="quantity" type="number" step="0.01" min="0.01" className="field" required /></label>
              <p className="col-span-2 text-sm text-pencil">Los procedimientos descargan los insumos del consultorio donde se realizaron.</p>
              {tError && <p className="error col-span-2" role="alert">{tError}</p>}
              <button className="btn col-span-2">Trasladar</button>
            </div>
          </form>
        </div>
      )}
      {ok && <p className="text-sm font-medium text-pen" role="status">{ok}</p>}

      <section className="sheet">
        <div className="border-b-2 border-print px-5 py-4"><h2 className="text-xl font-semibold">Kardex</h2></div>
        <div className="max-h-96 overflow-auto">
          <table className="w-full min-w-[760px] text-left">
            <thead className="sticky top-0 bg-card">
              <tr className="border-b border-print">
                {["Fecha", "Insumo", "Ubicación", "Movimiento", "Cantidad", "Usuario", "Detalle"].map((h) => <th key={h} className="label px-4 py-2">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {moves.map((m) => (
                <tr key={m.id} className="rule-row text-sm">
                  <td className="px-4 py-2 text-pen">{fmtDateTime(m.created_at)}</td>
                  <td className="px-4 py-2 text-pen">{m.supply_name}</td>
                  <td className="px-4 py-2 text-pen">{locations.find((l) => l.id === String(m.chair))?.name ?? (m.chair ? `#${m.chair}` : "Bodega central")}</td>
                  <td className="px-4 py-2 text-pen">{REASONS[m.reason]}</td>
                  <td className={`px-4 py-2 font-semibold ${m.quantity < 0 ? "text-red" : "text-pen"}`}>{m.quantity > 0 ? "+" : ""}{qty(m.quantity)}</td>
                  <td className="px-4 py-2 text-pen">{m.user_name}</td>
                  <td className="px-4 py-2 text-pencil">{m.treatment ? `Tratamiento #${m.treatment}` : m.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <p className="text-sm text-pencil">Valor del inventario: {money(supplies.reduce((s, x) => s + Math.max(0, x.stock) * x.unit_cost, 0))}</p>
    </div>
  );
}
