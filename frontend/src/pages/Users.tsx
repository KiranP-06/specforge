import { useEffect, useState } from "react";
import { api, type Role, type User } from "../api";

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api.users().then(setUsers).catch((e) => setError(e.message)); }, []);

  async function change(u: User, role: Role) {
    try {
      const updated = await api.setRole(u.id, role);
      setUsers((us) => us.map((x) => (x.id === u.id ? updated : x)));
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <div className="container grid">
      <h1>Team & roles</h1>
      <p className="muted small">Analysts generate and edit blueprints. Reviewers approve items and create baselines. Admins do everything.</p>
      {error && <div className="alert err">{error}</div>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Role</th></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td><td>{u.email}</td>
                <td>
                  <select value={u.role} onChange={(e) => change(u, e.target.value as Role)} style={{ width: "auto" }}>
                    <option value="admin">admin</option><option value="analyst">analyst</option><option value="reviewer">reviewer</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
