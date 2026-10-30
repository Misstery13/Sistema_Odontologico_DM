import { useEffect, useState } from "react";
import { api, fmtDateTime, formSubmit, getSession } from "../api.js";

export const ROLES = {
  odontologo: "Odontólogo",
  asistente: "Asistente dental",
  recepcion: "Recepción / caja",
  auditor: "Auditor / contador",
  admin: "Administrador TI",
};

function Row({ u, onChange }) {
  const [pwOpen, setPwOpen] = useState(false);
  const [error, setError] = useState("");
  const me = u.id === getSession().id;
  const run = async (fn) => {
    setError("");
    try {
      onChange(await fn());
    } catch (e) {
      setError(e.message);
    }
  };
  const patch = (body) => run(() => api(`/api/users/${u.id}/`, { method: "PATCH", body }));
  const resetPassword = formSubmit(async ({ password }) => {
    await run(() => api(`/api/users/${u.id}/reset-password/`, { method: "POST", body: { password } }));
    setPwOpen(false);
  }, setError);

  return (
    <tr className={`rule-row align-top ${u.is_active ? "" : "text-pencil"}`}>
      <td className="px-5 py-3">
        <p className={`font-medium ${u.is_active ? "text-pen" : "line-through"}`}>{[u.first_name, u.last_name].filter(Boolean).join(" ") || "—"}</p>
        <p className="text-sm text-pencil">{u.username}{me && " · tú"}</p>
      </td>
      <td className="px-3 py-3">
        <select value={u.role} disabled={me} onChange={(e) => patch({ role: e.target.value })} aria-label={`Rol de ${u.username}`} className="field py-1 text-sm">
          {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </td>
      <td className="px-3 py-3 text-sm">
        <p className={u.is_active ? "text-pen" : "font-semibold text-red"}>{u.is_active ? "Activo" : "Desactivado"}</p>
        {u.must_change_password && <p className="text-pencil">Contraseña temporal</p>}
        <p className={u.mfa_enabled ? "text-pencil" : "text-red"}>{u.mfa_enabled ? "MFA activo" : "MFA pendiente de enrolar"}</p>
      </td>
      <td className="px-3 py-3 text-sm text-pencil">{u.last_login ? fmtDateTime(u.last_login) : "Nunca"}</td>
      <td className="px-5 py-3 text-right text-sm">
        {!me && (
          <div className="flex flex-col items-end gap-1.5">
            <button onClick={() => patch({ is_active: !u.is_active })} className={u.is_active ? "font-medium text-red hover:underline" : "link"}>
              {u.is_active ? "Desactivar" : "Reactivar"}
            </button>
            <button onClick={() => setPwOpen(!pwOpen)} className="link">Contraseña temporal</button>
            {u.mfa_enabled && <button onClick={() => run(() => api(`/api/users/${u.id}/reset-mfa/`, { method: "POST" }))} className="link">Reiniciar MFA</button>}
          </div>
        )}
        {pwOpen && (
          <form onSubmit={resetPassword} className="mt-2 flex items-end justify-end gap-2">
            <input name="password" type="text" className="field w-44 text-sm" placeholder="Nueva temporal" autoComplete="off" required minLength={10} />
            <button className="btn py-1">Asignar</button>
          </form>
        )}
        {error && <p className="error mt-1" role="alert">{error}</p>}
      </td>
    </tr>
  );
}

// Administrador TI: usuarios de la clínica. No se borran (son autores de registros clínicos); se desactivan.
export default function Users() {
  const [users, setUsers] = useState(null);
  const [error, setError] = useState("");
  const load = () => api("/api/users/").then(setUsers);
  useEffect(() => {
    load();
  }, []);

  const create = formSubmit(async (data) => {
    await api("/api/users/", { method: "POST", body: { ...data, is_active: true } });
    load();
  }, setError);
  const replace = (u) => setUsers(users.map((x) => (x.id === u.id ? u : x)));

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
      <section className="sheet min-w-0">
        <div className="flex flex-wrap items-baseline gap-3 border-b-2 border-print px-5 py-4">
          <h1 className="text-xl font-semibold">Usuarios de la clínica</h1>
          <span className="text-sm text-pencil">{users?.filter((u) => u.is_active).length ?? 0} activos</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead>
              <tr className="border-b border-print">
                <th className="label px-5 py-2">Usuario</th>
                <th className="label px-3 py-2">Rol</th>
                <th className="label px-3 py-2">Estado</th>
                <th className="label px-3 py-2">Último ingreso</th>
                <th className="label px-5 py-2 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>{users?.map((u) => <Row key={u.id} u={u} onChange={replace} />)}</tbody>
          </table>
        </div>
        {users === null && <p className="px-5 py-6 text-pencil">Cargando usuarios…</p>}
      </section>

      <form onSubmit={create} className="sheet border-t-4 border-red">
        <div className="border-b border-dashed border-pencil/50 px-5 py-3"><h2 className="label-red">Nuevo usuario</h2></div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-4 px-5 py-5">
          <label><span className="label">Nombres</span><input name="first_name" className="field" /></label>
          <label><span className="label">Apellidos</span><input name="last_name" className="field" /></label>
          <label className="col-span-2"><span className="label">Usuario<span className="text-red"> *</span></span>
            <input name="username" className="field" required autoComplete="off" pattern="[\w.@+-]+" title="Letras, números y . @ + - _" />
          </label>
          <label className="col-span-2"><span className="label">Email</span><input name="email" type="email" className="field" /></label>
          <label className="col-span-2"><span className="label">Rol<span className="text-red"> *</span></span>
            <select name="role" className="field" defaultValue="recepcion">
              {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <label className="col-span-2"><span className="label">Contraseña temporal<span className="text-red"> *</span></span>
            <input name="password" type="text" className="field" required minLength={10} autoComplete="off" />
          </label>
          <p className="col-span-2 text-sm text-pencil">
            Entrégala en persona. En su primer ingreso deberá cambiarla y activar la verificación en dos pasos.
          </p>
          {error && <p className="error col-span-2" role="alert">{error}</p>}
          <button className="btn col-span-2">Crear usuario</button>
        </div>
      </form>
    </div>
  );
}
