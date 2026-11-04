import { useState, type FormEvent } from "react";
import { api } from "../api";
import { useSession } from "../App";

export default function Login() {
  const { setSession } = useSession();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const res = mode === "login" ? await api.login(email, password) : await api.register(email, name, password);
      setSession(res.access_token, res.user);
    } catch (err) {
      setError((err as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <div className="auth-wrap">
      <div className="card auth-card">
        <div className="logo" style={{ marginBottom: "1rem" }}><span className="logo-mark"><span /></span>SPECForge</div>
        <h1>{mode === "login" ? "Sign in" : "Create account"}</h1>
        <p className="muted small">Turn a project brief into a connected, self-checking blueprint.</p>
        <form className="stack" onSubmit={submit}>
          {mode === "register" && <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>}
          <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" /></label>
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required
            autoComplete={mode === "login" ? "current-password" : "new-password"} /></label>
          {error && <div className="alert err" role="alert">{error}</div>}
          <button className="primary" disabled={busy}>{busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}</button>
        </form>
        <p className="small muted" style={{ marginTop: "1rem" }}>
          {mode === "login" ? "New here? " : "Already have an account? "}
          <a href="#" onClick={(e) => { e.preventDefault(); setMode(mode === "login" ? "register" : "login"); setError(""); }}>
            {mode === "login" ? "Create an account" : "Sign in"}
          </a>
          {mode === "register" && <><br />The first account becomes the admin.</>}
        </p>
      </div>
    </div>
  );
}
