import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, is } from "../api.js";
import PatientForm from "../PatientForm.jsx";

export default function Patients() {
  const [patients, setPatients] = useState(null);
  const [q, setQ] = useState("");
  const [fresh, setFresh] = useState(null);

  const load = () => api(`/api/patients/?q=${encodeURIComponent(q)}`).then(setPatients);
  useEffect(() => {
    load();
  }, [q]);

  const create = async (data) => {
    const p = await api("/api/patients/", { method: "POST", body: data });
    setFresh(p.id);
    load();
  };

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_420px]">
      <section className="sheet">
        <div className="flex flex-wrap items-end gap-4 border-b-2 border-print px-5 py-4">
          <h1 className="text-xl font-semibold">Archivo de pacientes</h1>
          <label className="ml-auto w-full max-w-xs">
            <span className="label">Buscar</span>
            <input type="search" className="field" placeholder="Nombre, apellido o cédula" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
        </div>
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-print">
              <th className="label px-5 py-2">Paciente</th>
              <th className="label px-3 py-2">Cédula</th>
              <th className="label hidden px-3 py-2 sm:table-cell">Teléfono</th>
              <th className="label hidden px-5 py-2 md:table-cell">Alertas</th>
            </tr>
          </thead>
          <tbody>
            {patients?.map((p) => (
              <tr key={p.id} className="rule-row hover:bg-desk/50">
                <td className="px-5 py-2.5">
                  <Link to={`/pacientes/${p.id}`} className={`inline-block font-medium text-pen hover:underline ${p.id === fresh ? "write-in" : ""}`}>{p.last_name}, {p.first_name}</Link>
                </td>
                <td className="px-3 py-2.5 text-pen">{p.cedula}</td>
                <td className="hidden px-3 py-2.5 text-pen sm:table-cell">{p.phone}</td>
                <td className="hidden px-5 py-2.5 font-medium text-red md:table-cell">{p.alerts.join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {patients === null && <p className="px-5 py-6 text-pencil">Cargando archivo…</p>}
        {patients?.length === 0 && (
          <p className="px-5 py-8 text-pencil">
            {q ? `Ninguna ficha coincide con “${q}”.` : "Aún no hay fichas. Registra la primera con el formulario."}
          </p>
        )}
      </section>

      {is("recepcion", "odontologo") && (
        <section className="sheet border-t-4 border-red">
          <div className="border-b border-dashed border-pencil/50 px-5 py-3">
            <h2 className="label-red">Nueva ficha clínica</h2>
          </div>
          <PatientForm onSave={create} />
        </section>
      )}
    </div>
  );
}
