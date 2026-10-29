import { createContext, useContext, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes } from "react-router-dom";
import { getSession } from "./api.js";
import Login from "./pages/Login.jsx";
import Patients from "./pages/Patients.jsx";
import PatientDetail from "./pages/PatientDetail.jsx";
import Appointments from "./pages/Appointments.jsx";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

export default function App() {
  const [session, setSession] = useState(getSession);
  const login = (s) => {
    localStorage.setItem("session", JSON.stringify(s));
    setSession(s);
  };
  const logout = () => {
    localStorage.removeItem("session");
    setSession(null);
  };

  return (
    <AuthContext.Provider value={{ session, login, logout }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={session ? <Navigate to="/" /> : <Login />} />
          <Route element={session ? <Layout /> : <Navigate to="/login" />}>
            <Route index element={<Navigate to="/pacientes" />} />
            <Route path="pacientes" element={<Patients />} />
            <Route path="pacientes/:id" element={<PatientDetail />} />
            <Route path="citas" element={<Appointments />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  );
}

function Layout() {
  const { session, logout } = useAuth();
  const link = ({ isActive }) => `px-3 py-1 rounded ${isActive ? "bg-teal-700" : "hover:bg-teal-700/60"}`;
  return (
    <div className="min-h-screen">
      <header className="bg-teal-600 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-3">
          <span className="mr-4 font-semibold">🦷 {session.clinic}</span>
          <NavLink to="/pacientes" className={link}>Pacientes</NavLink>
          <NavLink to="/citas" className={link}>Agenda</NavLink>
          <span className="ml-auto text-sm opacity-90">{session.user}</span>
          <button onClick={logout} className="rounded px-2 py-1 text-sm hover:bg-teal-700">Salir</button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4">
        <Outlet />
      </main>
    </div>
  );
}
