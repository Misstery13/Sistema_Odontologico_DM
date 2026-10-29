import { useEffect, useState } from "react";
import { api, fmtDateTime, is } from "../api.js";

// RF-04: 6 sitios por pieza (MV, V, DV vestibular; ML, L, DL lingual). MG positivo = recesión; NIC = PS + MG.
const SITES = ["MV", "V", "DV", "ML", "L", "DL"];
const UPPER = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28];
const LOWER = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38];
const blank = () => ({ pd: Array(6).fill(0), gm: Array(6).fill(0), bleeding: Array(6).fill(false), mobility: 0, furcation: 0 });

// mismo cálculo que el backend (PerioExam.summary) para verlo mientras se carga
export function summarize(teeth) {
  const sites = Object.values(teeth).flatMap((t) => t.pd.map((pd, i) => [pd, t.gm[i], t.bleeding[i]]));
  if (!sites.length) return null;
  return {
    teeth: Object.keys(teeth).length,
    bleeding_pct: Math.round((1000 * sites.filter((s) => s[2]).length) / sites.length) / 10,
    deep_sites: sites.filter((s) => s[0] >= 4).length,
    mean_cal: Math.round((100 * sites.reduce((a, s) => a + s[0] + s[1], 0)) / sites.length) / 100,
  };
}

function Summary({ s }) {
  if (!s) return null;
  const item = (label, value, warn) => (
    <div><dt className="label">{label}</dt><dd className={`hand text-2xl ${warn ? "text-red" : ""}`}>{value}</dd></div>
  );
  return (
    <dl className="flex flex-wrap gap-x-8 gap-y-2">
      {item("Piezas", s.teeth)}
      {item("Sangrado al sondaje", `${s.bleeding_pct}%`, s.bleeding_pct > 10)}
      {item("Sitios PS ≥ 4 mm", s.deep_sites, s.deep_sites > 0)}
      {item("NIC promedio", `${s.mean_cal} mm`, s.mean_cal >= 3)}
    </dl>
  );
}

const num = "w-9 border-0 border-b border-rule bg-transparent py-0.5 text-center text-sm font-medium text-pen focus:border-pen focus:outline-none disabled:text-print";

function ArchTable({ title, numbers, teeth, set, readOnly }) {
  const update = (n, key, i, value) => {
    const t = { ...teeth[n] };
    if (i === null) t[key] = value;
    else t[key] = t[key].map((v, j) => (j === i ? value : v));
    set({ ...teeth, [n]: t });
  };
  const cells = (n, key, from, kind) =>
    [0, 1, 2].map((k) => {
      const i = from + k, t = teeth[n];
      if (kind === "bool")
        return (
          <td key={key + i} className="px-0.5 text-center">
            <input type="checkbox" checked={t.bleeding[i]} disabled={readOnly} onChange={(e) => update(n, "bleeding", i, e.target.checked)}
              aria-label={`Sangrado ${SITES[i]} pieza ${n}`} className="h-4 w-4 accent-red" />
          </td>
        );
      if (kind === "cal") return <td key={key + i} className={`px-1 text-center text-sm ${t.pd[i] + t.gm[i] >= 3 ? "font-semibold text-red" : "text-pencil"}`}>{t.pd[i] + t.gm[i]}</td>;
      const [lo, hi] = key === "pd" ? [0, 15] : [-10, 15];
      return (
        <td key={key + i} className="px-0.5">
          <input type="number" min={lo} max={hi} value={t[key][i]} disabled={readOnly} aria-label={`${key === "pd" ? "PS" : "MG"} ${SITES[i]} pieza ${n}`}
            onChange={(e) => update(n, key, i, Math.max(lo, Math.min(hi, parseInt(e.target.value || "0", 10))))}
            className={`${num} ${key === "pd" && t.pd[i] >= 4 ? "!text-red" : ""}`} />
        </td>
      );
    });
  const present = numbers.filter((n) => teeth[n]);
  const th = (label, span = 3) => <th colSpan={span} className="label px-1 py-1 text-center">{label}</th>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px]">
        <caption className="label-red py-2 text-left">{title}</caption>
        <thead>
          <tr className="border-b border-print">
            {th("Pieza", 1)}{th("Mov.", 1)}{th("Furca", 1)}
            {th("PS vest.")}{th("MG vest.")}{th("Sangr. vest.")}{th("NIC vest.")}
            {th("PS ling.")}{th("MG ling.")}{th("Sangr. ling.")}{th("NIC ling.")}
          </tr>
        </thead>
        <tbody>
          {present.map((n) => (
            <tr key={n} className="rule-row">
              <th className="px-1 py-1 text-sm font-semibold">{n}</th>
              {["mobility", "furcation"].map((k) => (
                <td key={k} className="px-0.5">
                  <select value={teeth[n][k]} disabled={readOnly} onChange={(e) => update(n, k, null, Number(e.target.value))} aria-label={`${k === "mobility" ? "Movilidad" : "Furca"} pieza ${n}`}
                    className="border-0 border-b border-rule bg-transparent text-sm text-pen disabled:text-print">
                    {[0, 1, 2, 3].map((v) => <option key={v}>{v}</option>)}
                  </select>
                </td>
              ))}
              {cells(n, "pd", 0)}{cells(n, "gm", 0)}{cells(n, "b", 0, "bool")}{cells(n, "c", 0, "cal")}
              {cells(n, "pd", 3)}{cells(n, "gm", 3)}{cells(n, "b", 3, "bool")}{cells(n, "c", 3, "cal")}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Perio({ patient, teeth: odontogram }) {
  const [exams, setExams] = useState(null);
  const [open, setOpen] = useState(null); // examen visible
  const [draft, setDraft] = useState(null);
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const load = () => api(`/api/perio/?patient=${patient.id}`).then(setExams);
  useEffect(() => {
    load();
  }, [patient.id]);

  const start = () => {
    // las piezas extraídas no se sondean
    const present = [...UPPER, ...LOWER].filter((n) => odontogram[n]?.state !== "extraido");
    setDraft(Object.fromEntries(present.map((n) => [n, blank()])));
    setNotes("");
    setOpen(null);
  };
  const save = async () => {
    setError("");
    try {
      const exam = await api("/api/perio/", { method: "POST", body: { patient: patient.id, teeth: draft, notes } });
      setDraft(null);
      setOpen(exam.id);
      load();
    } catch (e) {
      setError(e.message);
    }
  };
  const shown = exams?.find((e) => e.id === open);

  return (
    <section className="sheet">
      <div className="flex flex-wrap items-baseline gap-3 border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Periodontograma</h2>
        <span className="text-sm text-pencil">PS: profundidad al sondaje · MG: margen gingival (+ recesión) · NIC = PS + MG, en mm</span>
        {is("odontologo") && !draft && <button onClick={start} className="btn ml-auto">Nuevo periodontograma</button>}
      </div>

      {draft && (
        <div className="space-y-4 border-b-2 border-print px-5 py-5">
          <Summary s={summarize(draft)} />
          <ArchTable title="Arcada superior" numbers={UPPER} teeth={draft} set={setDraft} />
          <ArchTable title="Arcada inferior" numbers={LOWER} teeth={draft} set={setDraft} />
          <label className="block"><span className="label">Observaciones</span>
            <textarea rows="2" className="field resize-y" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="flex gap-3">
            <button onClick={save} className="btn">Firmar y guardar</button>
            <button onClick={() => setDraft(null)} className="link">Descartar</button>
          </div>
        </div>
      )}

      <ul className="px-5">
        {exams?.map((e) => (
          <li key={e.id} className="rule-row py-3">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-semibold text-pen">{fmtDateTime(e.created_at)}</span>
              <span className="hand text-lg">{e.author_name}</span>
              <span className="text-xs text-pencil" title={e.signature}>Firma {e.signature.slice(0, 12)}…</span>
              <button onClick={() => setOpen(open === e.id ? null : e.id)} className="link ml-auto">{open === e.id ? "Ocultar" : "Ver detalle"}</button>
            </div>
            <div className="mt-2"><Summary s={e.summary} /></div>
            {shown?.id === e.id && (
              <div className="mt-3 space-y-3">
                <ArchTable title="Arcada superior" numbers={UPPER} teeth={e.teeth} readOnly />
                <ArchTable title="Arcada inferior" numbers={LOWER} teeth={e.teeth} readOnly />
                {e.notes && <p className="hand text-lg">{e.notes}</p>}
              </div>
            )}
          </li>
        ))}
        {exams?.length === 0 && !draft && <li className="py-6 text-pencil">Sin periodontogramas registrados.</li>}
      </ul>
    </section>
  );
}
