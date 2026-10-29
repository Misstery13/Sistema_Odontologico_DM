import { useState } from "react";
import { useAuth } from "../App.jsx";
import { api, formSubmit } from "../api.js";

export default function Login() {
  const { login } = useAuth();
  const [error, setError] = useState("");
  const submit = formSubmit(async (data) => login(await api("/api/login/", { method: "POST", body: data })), setError);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-3">
        <h1 className="text-xl font-semibold">🦷 Sistema Odontológico</h1>
        <div>
          <label className="label" htmlFor="username">Usuario</label>
          <input id="username" name="username" className="input" required autoFocus />
        </div>
        <div>
          <label className="label" htmlFor="password">Contraseña</label>
          <input id="password" name="password" type="password" className="input" required />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="btn w-full">Ingresar</button>
        <p className="text-xs text-slate-500">Demo: dra.lopez / odonto123</p>
      </form>
    </div>
  );
}
