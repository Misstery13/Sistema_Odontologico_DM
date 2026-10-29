import { createContext, useContext, useEffect, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { getSession, is, STAFF } from "./api.js";
import Login from "./pages/Login.jsx";
import Patients from "./pages/Patients.jsx";
import PatientDetail from "./pages/PatientDetail.jsx";
import Appointments from "./pages/Appointments.jsx";
import Cash from "./pages/Cash.jsx";
import Audit from "./pages/Audit.jsx";
import Inventory from "./pages/Inventory.jsx";
import Reports from "./pages/Reports.jsx";

const IDLE_MS = 15 * 60 * 1000; // RNF-05: el backend también invalida el token
const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export default function App() {
  const [session, setSession] = useState(getSession);
  const login = (s) => {
    localStorage.setItem("session", JSON.stringify(s));
    setSession(s);
  };
  const logout = (reason) => {
    localStorage.removeItem("session");
    if (reason) sessionStorage.setItem("logoutReason", reason);
    setSession(null);
  };
  const home = is(...STAFF) ? "/pacientes" : "/reportes";

  return (
    <AuthContext.Provider value={{ session, login, logout }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={session ? <Navigate to="/" /> : <Login />} />
          <Route element={session ? <Layout /> : <Navigate to="/login" />}>
            <Route index element={<Navigate to={home} />} />
            <Route path="pacientes" element={<Patients />} />
            <Route path="pacientes/:id" element={<PatientDetail />} />
            <Route path="citas" element={<Appointments />} />
            <Route path="caja" element={<Cash />} />
            <Route path="auditoria" element={<Audit />} />
            <Route path="inventario" element={<Inventory />} />
            <Route path="reportes" element={<Reports />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  );
}

export const Brand = () => <span className="text-sm font-bold uppercase tracking-[0.14em] text-red">Odonto DM</span>;

const ROLE_LABEL = { admin: "Administrador TI", recepcion: "Recepción", odontologo: "Odontología", asistente: "Asistente dental", auditor: "Auditoría" };

function Layout() {
  const { session, logout } = useAuth();

  useEffect(() => {
    let timer;
    const reset = () => {
      clearTimeout(timer);
      timer = setTimeout(() => logout("Sesión cerrada tras 15 minutos de inactividad."), IDLE_MS);
    };
    const events = ["pointerdown", "keydown", "scroll", "pointermove"];
    events.forEach((e) => addEventListener(e, reset, { passive: true }));
    reset();
    return () => {
      clearTimeout(timer);
      events.forEach((e) => removeEventListener(e, reset));
    };
  }, []);

  const link = ({ isActive }) =>
    `py-1 text-[15px] font-medium underline-offset-[10px] ${isActive ? "text-pen underline decoration-2" : "text-print hover:text-pen"}`;
  return (
    <div className="min-h-screen">
      <header className="border-b-4 border-red bg-card print:hidden">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
          <Brand />
          <nav className="flex flex-wrap gap-x-6 gap-y-1">
            {is(...STAFF) && <NavLink to="/citas" className={link}>Agenda</NavLink>}
            {is(...STAFF) && <NavLink to="/pacientes" className={link}>Pacientes</NavLink>}
            {is("recepcion", "auditor", "admin") && <NavLink to="/caja" className={link}>Caja</NavLink>}
            {is("asistente", "odontologo", "auditor", "admin") && <NavLink to="/inventario" className={link}>Inventario</NavLink>}
            {is("auditor", "admin") && <NavLink to="/reportes" className={link}>Reportes</NavLink>}
            {is("auditor", "admin") && <NavLink to="/auditoria" className={link}>Auditoría</NavLink>}
          </nav>
          <div className="ml-auto flex items-baseline gap-4">
            <span className="label hidden sm:inline">{session.clinic} · {ROLE_LABEL[session.role]}</span>
            <span className="hand text-lg">{session.user}</span>
            <button onClick={() => logout()} className="link">Salir</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
