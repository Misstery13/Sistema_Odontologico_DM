import { useState } from "react";
import { useAuth } from "../App.jsx";
import { api, formSubmit } from "../api.js";

// cambio de contraseña propio; obligatorio cuando el administrador asignó una temporal
export default function Account() {
  const { session, login } = useAuth();
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const forced = session.must_change_password;

  const submit = formSubmit(async (data) => {
    if (data.new_password !== data.confirm) throw new Error("Las contraseñas nuevas no coinciden");
    await api("/api/password/", { method: "POST", body: { current_password: data.current_password, new_password: data.new_password } });
    login({ ...session, must_change_password: false });
    setDone(true);
  }, setError);

  return (
    <form onSubmit={submit} className="sheet mx-auto max-w-md border-t-4 border-red">
      <div className="border-b border-dashed border-pencil/50 px-6 py-3"><h1 className="label-red">Cambiar contraseña</h1></div>
      <div className="space-y-4 px-6 py-6">
        {forced && <p className="text-sm font-medium text-red">Tu contraseña es temporal. Cámbiala para continuar.</p>}
        {done && <p className="text-sm font-medium text-pen" role="status">Contraseña actualizada.</p>}
        {[["current_password", "Contraseña actual", "current-password"], ["new_password", "Nueva contraseña", "new-password"], ["confirm", "Repite la nueva", "new-password"]].map(([name, label, ac]) => (
          <label key={name} className="block"><span className="label">{label}</span>
            <input name={name} type="password" className="field" autoComplete={ac} required minLength={name === "current_password" ? 1 : 10} />
          </label>
        ))}
        <p className="text-sm text-pencil">Mínimo 10 caracteres; no puede ser una contraseña común ni parecerse a tu usuario.</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="btn w-full">Guardar contraseña</button>
      </div>
    </form>
  );
}
