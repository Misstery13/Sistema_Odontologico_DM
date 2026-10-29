import { useState } from "react";
import { Brand, useAuth } from "../App.jsx";
import { api, formSubmit } from "../api.js";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState(() => {
    const reason = sessionStorage.getItem("logoutReason") || "";
    sessionStorage.removeItem("logoutReason");
    return reason;
  });
  const submit = formSubmit(async (data) => login(await api("/api/login/", { method: "POST", body: data })), setError);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="sheet w-full max-w-md border-t-4 border-red">
        <div className="flex items-baseline justify-between border-b border-dashed border-pencil/50 px-6 py-4">
          <Brand />
          <span className="label">Sistema de gestión clínica</span>
        </div>
        <div className="space-y-5 px-6 py-6">
          <h1 className="hand text-3xl">Ingresa a tu clínica</h1>
          <div>
            <label className="label" htmlFor="username">Usuario</label>
            <input id="username" name="username" className="field" autoComplete="username" required autoFocus />
          </div>
          <div>
            <label className="label" htmlFor="password">Contraseña</label>
            <input id="password" name="password" type="password" className="field" autoComplete="current-password" required />
          </div>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="btn w-full">Ingresar</button>
          <p className="text-sm text-pencil">Demo (clave odonto123): dra.lopez, recepcion, asistente, auditor, admin</p>
        </div>
      </form>
    </div>
  );
}
