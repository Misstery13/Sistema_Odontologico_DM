import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, formSubmit } from "../api.js";

const FIELDS = [
  ["cedula", "Cédula", "text", true],
  ["first_name", "Nombres", "text", true],
  ["last_name", "Apellidos", "text", true],
  ["birth_date", "Fecha de nacimiento", "date"],
  ["phone", "Teléfono", "tel"],
  ["email", "Email", "email"],
];

export default function Patients() {
  const [patients, setPatients] = useState([]);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  const load = () => api(`/api/patients/?q=${encodeURIComponent(q)}`).then(setPatients);
  useEffect(() => {
    load();
  }, [q]);

  const submit = formSubmit(async (data) => {
    if (!data.birth_date) delete data.birth_date;
    await api("/api/patients/", { method: "POST", body: data });
    load();
  }, setError);

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <section className="card md:col-span-2">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-lg font-semibold">Pacientes</h2>
          <input className="input ml-auto max-w-xs" placeholder="Buscar por nombre o cédula" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr><th className="py-1">Paciente</th><th>Cédula</th><th>Teléfono</th></tr>
          </thead>
          <tbody>
            {patients.map((p) => (
              <tr key={p.id} className="border-t border-slate-100">
                <td className="py-1.5">
                  <Link to={`/pacientes/${p.id}`} className="text-teal-700 hover:underline">{p.last_name}, {p.first_name}</Link>
                </td>
                <td>{p.cedula}</td>
                <td>{p.phone}</td>
              </tr>
            ))}
            {!patients.length && <tr><td colSpan="3" className="py-4 text-center text-slate-400">Sin pacientes</td></tr>}
          </tbody>
        </table>
      </section>

      <form onSubmit={submit} className="card space-y-2">
        <h2 className="text-lg font-semibold">Nuevo paciente</h2>
        {FIELDS.map(([name, label, type, required]) => (
          <div key={name}>
            <label className="label" htmlFor={name}>{label}</label>
            <input id={name} name={name} type={type} className="input" required={required} />
          </div>
        ))}
        <div>
          <label className="label" htmlFor="allergies">Alergias</label>
          <input id="allergies" name="allergies" className="input" />
        </div>
        <div>
          <label className="label" htmlFor="medical_history">Antecedentes médicos</label>
          <textarea id="medical_history" name="medical_history" rows="3" className="input" />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="btn w-full">Guardar</button>
      </form>
    </div>
  );
}
