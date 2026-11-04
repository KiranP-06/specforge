import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { api, auth, type User } from "./api";
import Login from "./pages/Login";
import Projects from "./pages/Projects";
import ProjectView from "./pages/ProjectView";
import Users from "./pages/Users";

interface Session { user: User | null; setSession: (token: string, user: User) => void; logout: () => void }
const SessionCtx = createContext<Session>({ user: null, setSession: () => {}, logout: () => {} });
export const useSession = () => useContext(SessionCtx);

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!auth.token);
  const navigate = useNavigate();

  useEffect(() => {
    if (!auth.token) return;
    api.me().then(setUser).catch(() => { auth.token = null; }).finally(() => setLoading(false));
  }, []);

  const setSession = useCallback((token: string, u: User) => { auth.token = token; setUser(u); }, []);
  const logout = useCallback(() => { auth.token = null; setUser(null); navigate("/login"); }, [navigate]);

  if (loading) return <div className="container muted">Loading…</div>;

  return (
    <SessionCtx.Provider value={{ user, setSession, logout }}>
      {user && (
        <header className="topbar">
          <Link to="/" className="logo"><span className="logo-mark"><span /></span>SPECForge</Link>
          <span className="muted small hide-sm">Brief → Blueprint → Delivery</span>
          <span className="spacer" />
          {user.role === "admin" && <Link to="/users">Team</Link>}
          <span className="badge">{user.role}</span>
          <span className="small hide-sm">{user.name}</span>
          <button className="ghost" onClick={logout}>Sign out</button>
        </header>
      )}
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" /> : <Login />} />
        <Route path="/" element={user ? <Projects /> : <Navigate to="/login" />} />
        <Route path="/projects/:id" element={user ? <ProjectView /> : <Navigate to="/login" />} />
        <Route path="/users" element={user?.role === "admin" ? <Users /> : <Navigate to="/" />} />
        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </SessionCtx.Provider>
  );
}
