import { useState } from "react";
import { Brand, useAuth } from "../App.jsx";
import { api, formSubmit } from "../api.js";

// RNF-05: usuario y contraseña, luego el código de la app autenticadora (en el primer ingreso, enrolamiento con QR)
export default function Login() {
  const { login } = useAuth();
  const [challenge, setChallenge] = useState(null); // { mfa: "setup" | "verify", ticket, secret?, qr? }
  const [error, setError] = useState(() => {
    const reason = sessionStorage.getItem("logoutReason") || "";
    sessionStorage.removeItem("logoutReason");
    return reason;
  });

  const credentials = formSubmit(async (data) => {
    const r = await api("/api/login/", { method: "POST", body: data });
    r.token ? login(r) : setChallenge(r);
  }, setError);
  const verify = formSubmit(async ({ code }) => {
    try {
      login(await api("/api/login/mfa/", { method: "POST", body: { ticket: challenge.ticket, code } }));
    } catch (e) {
      if (e.message.includes("venció")) setChallenge(null);
      throw e;
    }
  }, setError);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={challenge ? verify : credentials} className="sheet w-full max-w-md border-t-4 border-red">
        <div className="flex items-baseline justify-between border-b border-dashed border-pencil/50 px-6 py-4">
          <Brand />
          <span className="label">Sistema de gestión clínica</span>
        </div>
        {!challenge ? (
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
            <button className="btn w-full">Continuar</button>
            <p className="text-sm text-pencil">
              Demo (clave odonto123): dra.lopez, recepcion, asistente, auditor, admin. Código de verificación: <code>python tests/totp.py</code>
            </p>
          </div>
        ) : (
          <div className="space-y-5 px-6 py-6">
            {challenge.mfa === "setup" ? (
              <>
                <h1 className="hand text-3xl">Activa la verificación en dos pasos</h1>
                <p className="text-sm">
                  Escanea el código con Google Authenticator, Microsoft Authenticator o Authy. Desde ahora te pedirá un código cada vez que ingreses.
                </p>
                <img src={challenge.qr} alt="Código QR para la app autenticadora" className="mx-auto h-48 w-48" />
                <p className="text-center text-xs text-pencil">
                  ¿No puedes escanear? Ingresa esta clave: <code className="break-all font-semibold text-pen">{challenge.secret}</code>
                </p>
              </>
            ) : (
              <>
                <h1 className="hand text-3xl">Verificación en dos pasos</h1>
                <p className="text-sm">Escribe el código de 6 dígitos que muestra tu app autenticadora.</p>
              </>
            )}
            <div>
              <label className="label" htmlFor="code">Código</label>
              <input id="code" name="code" className="field text-2xl tracking-[0.4em]" inputMode="numeric" autoComplete="one-time-code"
                pattern="[0-9]{6}" maxLength={6} required autoFocus />
            </div>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="btn w-full">Verificar e ingresar</button>
            <button type="button" onClick={() => { setChallenge(null); setError(""); }} className="link">Volver</button>
          </div>
        )}
      </form>
    </div>
  );
}
