import { useEffect, useState } from "react";
import { api } from "../api.js";

const ACTIONS = { list: "Consulta de lista", read: "Consulta", create: "Alta", update: "Modificación" };
const MODELS = { Patient: "Paciente", ClinicalNote: "Nota SOEP", Treatment: "Tratamiento", Tooth: "Odontograma" };

// RNF-06: quién consultó o modificó qué historia clínica, cuándo y desde dónde
export default function Audit() {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    api("/api/audit/").then(setRows);
  }, []);
  return (
    <section className="sheet">
      <div className="flex flex-wrap items-baseline gap-3 border-b-2 border-print px-5 py-4">
        <h1 className="text-xl font-semibold">Auditoría de historias clínicas</h1>
        <span className="text-sm text-pencil">Últimos 300 registros · inmutable</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-b border-print">
              {["Fecha y hora", "Usuario", "Acción", "Registro", "IP"].map((h) => <th key={h} className="label px-5 py-2">{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.id} className="rule-row">
                <td className="px-5 py-2 text-pen" title={r.timestamp}>{new Date(r.timestamp).toLocaleString("es-EC")}</td>
                <td className="px-5 py-2 text-pen">{r.user_name}</td>
                <td className="px-5 py-2 text-pen">{ACTIONS[r.action] || r.action}</td>
                <td className="px-5 py-2 text-pen">{MODELS[r.model] || r.model}{r.object_id && <span className="text-pencil">{r.action === "list" ? " del paciente" : ""} #{r.object_id}</span>}</td>
                <td className="px-5 py-2 text-pencil">{r.ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows === null && <p className="px-5 py-6 text-pencil">Cargando registros…</p>}
      {rows?.length === 0 && <p className="px-5 py-8 text-pencil">Sin actividad registrada.</p>}
    </section>
  );
}
