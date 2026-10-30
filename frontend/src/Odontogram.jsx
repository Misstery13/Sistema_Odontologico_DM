import { useEffect, useState } from "react";
import { api, is } from "./api.js";

// RF-03: catálogo visual — rojo = patología / requerido, azul = existente / realizado
export const SURFACE_BRUSHES = { caries: "Caries", restauracion: "Restauración", sellante: "Sellante", limpiar: "Sin hallazgo" };
export const TOOTH_STATES = {
  sano: "Sano",
  endodoncia_requerida: "Endodoncia requerida",
  endodoncia: "Endodoncia realizada",
  implante: "Implante",
  protesis_fija: "Prótesis fija / corona",
  protesis_removible: "Prótesis removible",
  exodoncia_indicada: "Exodoncia indicada",
  extraido: "Extraído",
};
const SURFACE_NAMES = { M: "mesial", D: "distal", O: "oclusal/incisal", V: "vestibular", L: "lingual/palatino" };
const FILL = { caries: "var(--color-red)", restauracion: "var(--color-pen)", sellante: "url(#sellante)" };

const range = (q, n) => Array.from({ length: n }, (_, i) => q * 10 + i + 1);
// vista del odontólogo: el lado derecho del paciente queda a la izquierda
const ARCHES = {
  permanente: [[...range(1, 8).reverse(), ...range(2, 8)], [...range(4, 8).reverse(), ...range(3, 8)]],
  temporal: [[...range(5, 5).reverse(), ...range(6, 5)], [...range(8, 5).reverse(), ...range(7, 5)]],
};

// nomenclatura Universal (ADA): permanentes 1-32, temporales A-T
export const universal = (n) => {
  const q = Math.floor(n / 10), d = n % 10;
  if (q <= 4) return String({ 1: 9 - d, 2: 8 + d, 3: 25 - d, 4: 24 + d }[q]);
  return "ABCDEFGHIJKLMNOPQRST"[{ 5: 5 - d, 6: 4 + d, 7: 15 - d, 8: 14 + d }[q]];
};

// qué superficie anatómica ocupa cada lado del dibujo según cuadrante
const sides = (n) => {
  const q = Math.floor(n / 10);
  const upper = [1, 2, 5, 6].includes(q), viewerLeft = [1, 4, 5, 8].includes(q);
  return { top: upper ? "V" : "L", bottom: upper ? "L" : "V", left: viewerLeft ? "D" : "M", right: viewerLeft ? "M" : "D", center: "O" };
};
const POLY = {
  top: "2,2 38,2 27,13 13,13",
  bottom: "13,27 27,27 38,38 2,38",
  left: "2,2 13,13 13,27 2,38",
  right: "38,2 38,38 27,27 27,13",
  center: "13,13 27,13 27,27 13,27",
};
const PEN = "var(--color-pen)", RED = "var(--color-red)";
const OVERLAY = {
  endodoncia_requerida: <path d="M20 0V40" stroke={RED} strokeWidth="3.5" />,
  endodoncia: <path d="M20 0V40" stroke={PEN} strokeWidth="3.5" />,
  implante: <path d="M20 3V37M13 10H27M13 18H27M13 26H27" stroke={PEN} strokeWidth="2.5" fill="none" />,
  protesis_fija: <circle cx="20" cy="20" r="18.5" fill="none" stroke={PEN} strokeWidth="3" />,
  protesis_removible: <path d="M0 16.5H40M0 23.5H40" stroke={PEN} strokeWidth="2.5" />,
  exodoncia_indicada: <path d="M3 3L37 37M37 3L3 37" stroke={RED} strokeWidth="3.5" />,
  extraido: <path d="M3 3L37 37M37 3L3 37" stroke={PEN} strokeWidth="3.5" />,
};

export function ToothGlyph({ n, tooth, onSurface, size = 40 }) {
  const map = sides(n);
  const t = tooth || { state: "sano", surfaces: {} };
  return (
    <svg viewBox="0 0 40 40" width={size ?? "100%"} height={size ?? undefined} aria-hidden="true" className="block">
      <g opacity={t.state === "extraido" ? 0.3 : 1}>
        {Object.entries(POLY).map(([side, points]) => (
          <polygon key={side} points={points} fill={FILL[t.surfaces?.[map[side]]] || "white"} stroke="var(--color-print)" strokeWidth="1"
            onClick={onSurface && ((e) => { e.stopPropagation(); onSurface(map[side]); })} className={onSurface ? "cursor-pointer hover:opacity-70" : ""} />
        ))}
      </g>
      {OVERLAY[t.state]}
    </svg>
  );
}

export function Legend() {
  const sample = (props) => <ToothGlyph n={11} size={20} {...props} />;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-pencil">
      {Object.entries(SURFACE_BRUSHES).filter(([k]) => k !== "limpiar").map(([k, v]) => (
        <span key={k} className="flex items-center gap-1">{sample({ tooth: { state: "sano", surfaces: { O: k } } })}{v}</span>
      ))}
      {Object.entries(TOOTH_STATES).filter(([k]) => k !== "sano").map(([k, v]) => (
        <span key={k} className="flex items-center gap-1">{sample({ tooth: { state: k, surfaces: {} } })}{v}</span>
      ))}
    </div>
  );
}

// hallazgos pendientes de tratar (lo que el catálogo marca en rojo)
export const pendingFindings = (teeth) =>
  Object.entries(teeth).flatMap(([n, t]) => [
    ...(Object.entries(t.surfaces || {}).some(([, v]) => v === "caries")
      ? [`Pieza ${n} · caries ${Object.entries(t.surfaces).filter(([, v]) => v === "caries").map(([s]) => s).join("")}`]
      : []),
    ...(["endodoncia_requerida", "exodoncia_indicada"].includes(t.state) ? [`Pieza ${n} · ${TOOTH_STATES[t.state].toLowerCase()}`] : []),
  ]);

export default function Odontogram({ patientId, teeth, setTeeth }) {
  const [dentition, setDentition] = useState("permanente");
  const [notation, setNotation] = useState("fdi");
  const [brush, setBrush] = useState({ kind: "surface", value: "caries" });
  const [error, setError] = useState("");
  const canEdit = is("odontologo");
  const url = `/api/patients/${patientId}/odontogram/`;
  const apply = (list) => setTeeth(Object.fromEntries(list.map((t) => [t.number, t])));

  useEffect(() => {
    api(url).then(apply);
  }, [url]);

  const save = async (n, change) => {
    const current = teeth[n] || { state: "sano", surfaces: {} };
    setError("");
    try {
      apply(await api(url, { method: "POST", body: { number: n, ...current, ...change } }));
    } catch (e) {
      setError(e.message);
    }
  };
  const paintSurface = (n, surface) => {
    if (brush.kind !== "surface") return paintTooth(n);
    const surfaces = { ...(teeth[n]?.surfaces || {}) };
    if (brush.value === "limpiar" || surfaces[surface] === brush.value) delete surfaces[surface];
    else surfaces[surface] = brush.value;
    save(n, { surfaces });
  };
  const paintTooth = (n) => (brush.kind === "tooth" ? save(n, { state: brush.value }) : paintSurface(n, "O"));

  const chip = (kind, value, label) => {
    const on = brush.kind === kind && brush.value === value;
    return (
      <button key={value} onClick={() => setBrush({ kind, value })} aria-pressed={on}
        className={`flex items-center gap-1.5 rounded-[3px] border px-2 py-1 text-sm ${on ? "border-pen bg-rule/60 font-semibold text-pen" : "border-rule text-print hover:border-pen"}`}>
        <ToothGlyph n={11} size={16} tooth={kind === "surface" ? { state: "sano", surfaces: value === "limpiar" ? {} : { O: value } } : { state: value, surfaces: {} }} />
        {label}
      </button>
    );
  };
  const toggle = (value, set, options) => (
    <div className="flex rounded-[3px] border border-pen" role="group">
      {options.map(([k, label]) => (
        <button key={k} onClick={() => set(k)} aria-pressed={value === k}
          className={`px-3 py-1 text-sm font-semibold ${value === k ? "bg-pen text-white" : "text-pen hover:bg-rule/50"}`}>{label}</button>
      ))}
    </div>
  );

  return (
    <section className="sheet">
      <div className="flex flex-wrap items-center gap-3 border-b-2 border-print px-5 py-4">
        <h2 className="text-xl font-semibold">Odontograma</h2>
        <div className="ml-auto flex flex-wrap gap-3">
          {toggle(dentition, setDentition, [["permanente", "Permanente"], ["temporal", "Temporal"]])}
          {toggle(notation, setNotation, [["fdi", "FDI"], ["universal", "Universal"]])}
        </div>
      </div>
      {canEdit && (
        <div className="space-y-2 border-b border-rule px-5 py-3">
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Hallazgo por superficie">
            <span className="label mr-1 w-20">Superficie</span>
            {Object.entries(SURFACE_BRUSHES).map(([k, v]) => chip("surface", k, v))}
          </div>
          <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Condición de la pieza">
            <span className="label mr-1 w-20">Pieza</span>
            {Object.entries(TOOTH_STATES).map(([k, v]) => chip("tooth", k, v))}
          </div>
        </div>
      )}
      <div className="overflow-x-auto px-5 py-5">
        {ARCHES[dentition].map((row, i) => (
          // grilla fluida: la arcada completa entra en el ancho de una tablet junto al sillón (RNF-07)
          <div key={i} className={`mx-auto grid gap-1 ${dentition === "temporal"
            ? "max-w-[620px] min-w-[360px] grid-cols-[repeat(5,minmax(0,1fr))_14px_repeat(5,minmax(0,1fr))]"
            : "max-w-[1000px] min-w-[560px] grid-cols-[repeat(8,minmax(0,1fr))_14px_repeat(8,minmax(0,1fr))]"} ${i ? "mt-3 border-t border-print pt-3" : ""}`}>
            {row.map((n, j) => {
              const t = teeth[n];
              const label = notation === "fdi" ? n : universal(n);
              const findings = Object.entries(t?.surfaces || {}).map(([s, v]) => `${SURFACE_NAMES[s]} ${SURFACE_BRUSHES[v].toLowerCase()}`);
              return (
                <button key={n} onClick={() => paintTooth(n)} disabled={!canEdit}
                  aria-label={`Pieza ${label}: ${TOOTH_STATES[t?.state || "sano"]}${findings.length ? `; ${findings.join(", ")}` : ""}`}
                  className={`flex flex-col items-center gap-1 rounded-[3px] p-0.5 enabled:hover:bg-rule/40 ${j === row.length / 2 ? (dentition === "temporal" ? "col-start-7" : "col-start-10") : ""} ${i ? "flex-col-reverse" : ""}`}>
                  <span className="text-xs font-semibold">{label}</span>
                  <ToothGlyph n={n} tooth={t} onSurface={canEdit ? (s) => paintSurface(n, s) : null} size={null} />
                </button>
              );
            })}
          </div>
        ))}
        <svg width="0" height="0" className="absolute">
          <defs>
            <pattern id="sellante" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="5" height="5" fill="white" /><rect width="2" height="5" fill="var(--color-pen)" />
            </pattern>
          </defs>
        </svg>
      </div>
      <div className="border-t border-rule px-5 py-3">
        {canEdit && <p className="mb-2 text-sm text-pencil">Con un hallazgo de superficie, marca la cara del diente; con una condición de pieza, marca el diente completo.</p>}
        {error && <p className="error mb-2">{error}</p>}
        <Legend />
      </div>
    </section>
  );
}
