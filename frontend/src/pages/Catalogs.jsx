import { useEffect, useState } from "react";
import { api, formSubmit, money } from "../api.js";

const Err = ({ msg }) => (msg ? <p className="error" role="alert">{msg}</p> : null);
const Active = ({ value, onChange }) => (
  <label className="flex items-center gap-2 text-sm">
    <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} className="h-4 w-4 accent-pen" /> Activo
  </label>
);

// guarda un registro del catálogo (alta o edición) y devuelve el error para mostrarlo en su fila
function useSave(endpoint, reload) {
  return async (item, data) => {
    try {
      await api(item ? `${endpoint}${item.id}/` : endpoint, { method: item ? "PATCH" : "POST", body: data });
      reload();
      return "";
    } catch (e) {
      return e.message;
    }
  };
}

function ProcedureRow({ p, supplies, save }) {
  const [edit, setEdit] = useState(!p);
  const [recipe, setRecipe] = useState(p?.recipe.map((r) => ({ supply: String(r.supply), quantity: r.quantity })) ?? []);
  const [active, setActive] = useState(p?.active ?? true);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.currentTarget));
    const msg = await save(p, {
      code: d.code, name: d.name, fee: d.fee, lab_cost: d.lab_cost || 0, active,
      recipe: recipe.filter((r) => r.supply).map((r) => ({ supply: Number(r.supply), quantity: r.quantity })),
    });
    setError(msg);
    if (!msg && p) setEdit(false);
    if (!msg && !p) e.target.reset();
  };
  if (!edit)
    return (
      <li className={`rule-row flex flex-wrap items-baseline gap-x-4 py-3 ${p.active ? "" : "text-pencil"}`}>
        <span className="w-14 text-sm text-pencil">{p.code}</span>
        <span className={`font-medium ${p.active ? "text-pen" : "line-through"}`}>{p.name}</span>
        <span className="text-pen">{money(p.fee)}{Number(p.lab_cost) > 0 && <span className="text-pencil"> + lab. {money(p.lab_cost)}</span>}</span>
        <span className="text-sm text-pencil">{p.recipe.length ? p.recipe.map((r) => `${r.supply_name} ${Number(r.quantity)} ${r.unit}`).join(" · ") : "Sin receta de consumo"}</span>
        <button onClick={() => setEdit(true)} className="link ml-auto">Editar</button>
      </li>
    );
  return (
    <li className="rule-row py-4">
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-[90px_1fr_120px_120px_auto]">
          <label><span className="label">Código</span><input name="code" defaultValue={p?.code} className="field" required /></label>
          <label><span className="label">Nombre</span><input name="name" defaultValue={p?.name} className="field" required /></label>
          <label><span className="label">Honorario $</span><input name="fee" type="number" step="0.01" min="0" defaultValue={p?.fee} className="field" required /></label>
          <label><span className="label">Laboratorio $</span><input name="lab_cost" type="number" step="0.01" min="0" defaultValue={p?.lab_cost ?? 0} className="field" /></label>
          <div className="self-end pb-2"><Active value={active} onChange={setActive} /></div>
        </div>
        <fieldset>
          <legend className="label">Receta estándar de consumo (se descarga al registrar el procedimiento)</legend>
          {recipe.map((r, k) => (
            <div key={k} className="mt-1 grid grid-cols-[1fr_110px_auto] gap-3">
              <select value={r.supply} onChange={(e) => setRecipe(recipe.map((x, j) => (j === k ? { ...x, supply: e.target.value } : x)))} className="field" aria-label="Insumo">
                <option value="">Elegir insumo…</option>
                {supplies.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.unit})</option>)}
              </select>
              <input type="number" step="0.01" min="0.01" value={r.quantity} onChange={(e) => setRecipe(recipe.map((x, j) => (j === k ? { ...x, quantity: e.target.value } : x)))} className="field" aria-label="Cantidad" />
              <button type="button" onClick={() => setRecipe(recipe.filter((_, j) => j !== k))} className="text-sm font-medium text-red">Quitar</button>
            </div>
          ))}
          <button type="button" onClick={() => setRecipe([...recipe, { supply: "", quantity: 1 }])} className="link mt-2">Agregar insumo</button>
        </fieldset>
        <Err msg={error} />
        <div className="flex gap-3">
          <button className="btn">{p ? "Guardar" : "Crear procedimiento"}</button>
          {p && <button type="button" onClick={() => setEdit(false)} className="link">Cancelar</button>}
        </div>
      </form>
    </li>
  );
}

function SupplyRow({ s, save }) {
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const msg = await save(s, Object.fromEntries(new FormData(e.currentTarget)));
    setError(msg);
    if (!msg && !s) e.target.reset();
  };
  return (
    <li className="rule-row py-2">
      <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-[1fr_110px_110px_120px_auto]">
        <label><span className="label">Insumo</span><input name="name" defaultValue={s?.name} className="field" required /></label>
        <label><span className="label">Unidad</span><input name="unit" defaultValue={s?.unit} className="field" required placeholder="par, ml, g…" /></label>
        <label><span className="label">Stock mínimo</span><input name="min_stock" type="number" step="0.01" min="0" defaultValue={s?.min_stock ?? 0} className="field" /></label>
        <label><span className="label">Costo unitario $</span><input name="unit_cost" type="number" step="0.0001" min="0" defaultValue={s?.unit_cost ?? 0} className="field" /></label>
        <button className={s ? "link pb-2" : "btn"}>{s ? "Guardar" : "Crear insumo"}</button>
        <div className="sm:col-span-5"><Err msg={error} /></div>
      </form>
    </li>
  );
}

function ChairRow({ c, save }) {
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const msg = await save(c, { name: new FormData(e.currentTarget).get("name") });
    setError(msg);
    if (!msg && !c) e.target.reset();
  };
  return (
    <li className="rule-row py-2">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-4">
        <label className="w-64"><span className="label">Consultorio / sillón</span><input name="name" defaultValue={c?.name} className="field" required /></label>
        {c && <div className="pb-2"><Active value={c.active} onChange={async (v) => setError(await save(c, { active: v }))} /></div>}
        <button className={c ? "link pb-2" : "btn"}>{c ? "Renombrar" : "Agregar consultorio"}</button>
        <Err msg={error} />
      </form>
    </li>
  );
}

function TemplateRow({ t, save }) {
  const [edit, setEdit] = useState(!t);
  const [error, setError] = useState("");
  const submit = async (e) => {
    e.preventDefault();
    const msg = await save(t, Object.fromEntries(new FormData(e.currentTarget)));
    setError(msg);
    if (!msg && t) setEdit(false);
    if (!msg && !t) e.target.reset();
  };
  if (!edit)
    return (
      <li className={`rule-row flex items-baseline gap-4 py-3 ${t.active ? "" : "text-pencil"}`}>
        <span className={`font-medium ${t.active ? "text-pen" : "line-through"}`}>{t.procedure}</span>
        <span className="truncate text-sm text-pencil">{t.body.slice(0, 120)}…</span>
        <span className="ml-auto flex shrink-0 gap-4">
          <Active value={t.active} onChange={async (v) => setError(await save(t, { active: v }))} />
          <button onClick={() => setEdit(true)} className="link">Editar</button>
        </span>
        <Err msg={error} />
      </li>
    );
  return (
    <li className="rule-row py-4">
      <form onSubmit={submit} className="space-y-3">
        <label className="block"><span className="label">Procedimiento</span><input name="procedure" defaultValue={t?.procedure} className="field" required /></label>
        <label className="block"><span className="label">Texto del consentimiento</span>
          <textarea name="body" rows="8" defaultValue={t?.body} className="field resize-y font-normal leading-relaxed" required />
        </label>
        <p className="text-sm text-pencil">Marcadores: {"{paciente} {cedula} {procedimiento} {odontologo} {fecha}"}. Los consentimientos ya firmados conservan su texto original.</p>
        <Err msg={error} />
        <div className="flex gap-3">
          <button className="btn">{t ? "Guardar" : "Crear formato"}</button>
          {t && <button type="button" onClick={() => setEdit(false)} className="link">Cancelar</button>}
        </div>
      </form>
    </li>
  );
}

const TABS = { procedimientos: "Procedimientos y precios", insumos: "Insumos", consultorios: "Consultorios", consentimientos: "Formatos de consentimiento" };

// Administrador TI: parametrización de catálogos. Nada se borra (hay registros que los referencian): se desactiva.
export default function Catalogs() {
  const [tab, setTab] = useState("procedimientos");
  const [data, setData] = useState({ procedures: [], supplies: [], chairs: [], templates: [] });
  const load = () =>
    Promise.all(["/api/procedures/", "/api/supplies/", "/api/chairs/", "/api/consent-templates/"].map((u) => api(u))).then(
      ([procedures, supplies, chairs, templates]) => setData({ procedures, supplies, chairs, templates }),
    );
  useEffect(() => {
    load();
  }, []);
  const saveProc = useSave("/api/procedures/", load);
  const saveSupply = useSave("/api/supplies/", load);
  const saveChair = useSave("/api/chairs/", load);
  const saveTpl = useSave("/api/consent-templates/", load);

  return (
    <section className="sheet">
      <div className="border-b-2 border-print px-5 pt-4">
        <h1 className="text-xl font-semibold">Catálogos de la clínica</h1>
        <div role="tablist" className="mt-3 flex flex-wrap gap-1">
          {Object.entries(TABS).map(([k, v]) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
              className={`border-b-2 px-3 py-2 text-sm font-semibold ${tab === k ? "border-pen text-pen" : "border-transparent text-print hover:text-pen"}`}>{v}</button>
          ))}
        </div>
      </div>
      <ul className="px-5 pb-5">
        {tab === "procedimientos" && <>
          {data.procedures.map((p) => <ProcedureRow key={`${p.id}-${p.fee}-${p.active}-${p.recipe.length}`} p={p} supplies={data.supplies} save={saveProc} />)}
          <li className="pt-4"><h2 className="label-red">Nuevo procedimiento</h2></li>
          <ProcedureRow p={null} supplies={data.supplies} save={saveProc} />
        </>}
        {tab === "insumos" && <>
          {data.supplies.map((s) => <SupplyRow key={s.id} s={s} save={saveSupply} />)}
          <li className="pt-4"><h2 className="label-red">Nuevo insumo</h2><p className="text-sm text-pencil">El stock se registra en Inventario con una compra.</p></li>
          <SupplyRow s={null} save={saveSupply} />
        </>}
        {tab === "consultorios" && <>
          {data.chairs.map((c) => <ChairRow key={`${c.id}-${c.active}`} c={c} save={saveChair} />)}
          <li className="pt-4"><h2 className="label-red">Nuevo consultorio</h2></li>
          <ChairRow c={null} save={saveChair} />
        </>}
        {tab === "consentimientos" && <>
          {data.templates.map((t) => <TemplateRow key={`${t.id}-${t.active}`} t={t} save={saveTpl} />)}
          <li className="pt-4"><h2 className="label-red">Nuevo formato</h2></li>
          <TemplateRow t={null} save={saveTpl} />
        </>}
      </ul>
    </section>
  );
}
