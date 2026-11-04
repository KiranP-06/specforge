// Thin typed client for the SPECForge REST API.

export type Role = "admin" | "analyst" | "reviewer";
export interface User { id: number; email: string; name: string; role: Role }
export interface Quality {
  score: number; coverage: number; consistency: number; clarity: number; linkage: number;
  ml_backend?: string; auto_repaired?: number; iterations?: { iteration: number; issues: number; score: number }[];
}
export interface ProjectSummary { id: number; name: string; description: string; status: string; quality_score: number | null; baseline_version: number; updated_at: string }
export interface Project extends ProjectSummary { brief_text: string; brief_filename: string | null; quality_breakdown: Quality | null; owner_id: number }
export interface Job { id: number; kind: string; status: "queued" | "running" | "succeeded" | "failed"; stage: string; progress: number; error: string | null; result: any }
export type ItemType = "requirement" | "story" | "module" | "entity" | "api" | "test" | "risk" | "stakeholder" | "constraint";
export type Status = "todo" | "in_progress" | "done" | "blocked";
export interface Item {
  id: number; project_id: number; key: string; type: ItemType; title: string; description: string; data: Record<string, any>;
  status: Status; review_state: "draft" | "approved" | "rejected"; stale: boolean; stale_reason: string | null; origin: string; version: number; updated_at: string;
}
export interface Finding { id: number; item_id: number | null; related_item_id: number | null; layer: string; kind: string; severity: "error" | "warning" | "info"; message: string; score: number | null }
export interface Impact { id: number; key: string; type: string; title: string; relation: string; depth: number; path: string[] }
export interface TraceRow { id: number; key: string; title: string; kind: string; priority: string; status: string; stale: boolean; storys: string[]; modules: string[]; apis: string[]; entitys: string[]; tests: string[]; risks: string[] }
export interface Baseline { id: number; version: number; quality_score: number | null; note: string; created_at: string }
export interface Version { id: number; version: number; snapshot: any; change_note: string; created_at: string }
export interface Comment { id: number; author_id: number; body: string; created_at: string }

const TOKEN_KEY = "specforge.token";
export const auth = {
  get token(): string | null { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set token(v: string | null) { try { if (v) localStorage.setItem(TOKEN_KEY, v); else localStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

export class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (auth.token) headers.set("Authorization", `Bearer ${auth.token}`);
  if (init.body && !(init.body instanceof FormData) && !(init.body instanceof URLSearchParams)) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && !path.includes("/auth/")) { auth.token = null; window.location.assign("/login"); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const b = await res.json(); msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail); } catch { /* not json */ }
    throw new ApiError(res.status, msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

const j = (body: unknown) => JSON.stringify(body);

export const api = {
  register: (email: string, name: string, password: string) => request<{ access_token: string; user: User }>("/api/auth/register", { method: "POST", body: j({ email, name, password }) }),
  login: (email: string, password: string) => request<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password }) }),
  me: () => request<User>("/api/auth/me"),
  users: () => request<User[]>("/api/users"),
  setRole: (id: number, role: Role) => request<User>(`/api/users/${id}/role`, { method: "PATCH", body: j({ role }) }),
  meta: () => request<{ version: string; llm_provider: string; ml_backend: string }>("/api/meta"),

  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (name: string, description: string, brief_text: string) => request<Project>("/api/projects", { method: "POST", body: j({ name, description, brief_text }) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  uploadBrief: (id: number, file?: File, text?: string) => {
    const fd = new FormData();
    if (file) fd.append("file", file); else fd.append("text", text ?? "");
    return request<Project>(`/api/projects/${id}/brief`, { method: "POST", body: fd });
  },
  generate: (id: number) => request<Job>(`/api/projects/${id}/generate`, { method: "POST" }),
  check: (id: number) => request<Job>(`/api/projects/${id}/check`, { method: "POST" }),
  job: (id: number) => request<Job>(`/api/jobs/${id}`),
  jobs: (pid: number) => request<Job[]>(`/api/projects/${pid}/jobs`),
  dashboard: (pid: number) => request<any>(`/api/projects/${pid}/dashboard`),
  items: (pid: number, type?: string) => request<Item[]>(`/api/projects/${pid}/items${type ? `?type=${type}` : ""}`),
  findings: (pid: number) => request<Finding[]>(`/api/projects/${pid}/findings`),
  trace: (pid: number) => request<TraceRow[]>(`/api/projects/${pid}/trace`),
  graph: (pid: number) => request<{ nodes: { id: number; key: string; type: string; title: string; stale: boolean; status: string }[]; edges: { id: number; source: number; target: number; relation: string }[] }>(`/api/projects/${pid}/graph`),
  baselines: (pid: number) => request<Baseline[]>(`/api/projects/${pid}/baselines`),
  baseline: (pid: number, note: string) => request<Baseline>(`/api/projects/${pid}/baselines`, { method: "POST", body: j({ note }) }),
  diff: (pid: number) => request<{ baseline_version: number; added: string[]; removed: string[]; changed: string[] }>(`/api/projects/${pid}/diff`),
  createItem: (pid: number, body: { type: ItemType; title: string; description?: string; link_from?: number[] }) => request<Item>(`/api/projects/${pid}/items`, { method: "POST", body: j(body) }),

  updateItem: (id: number, body: Partial<Pick<Item, "title" | "description" | "status" | "data">> & { change_note?: string }) =>
    request<{ item: Item; impacted: Impact[] }>(`/api/items/${id}`, { method: "PATCH", body: j(body) }),
  deleteItem: (id: number) => request<void>(`/api/items/${id}`, { method: "DELETE" }),
  impact: (id: number) => request<Impact[]>(`/api/items/${id}/impact`),
  acknowledge: (id: number) => request<Item>(`/api/items/${id}/acknowledge`, { method: "POST" }),
  review: (id: number, state: "approved" | "rejected" | "draft", comment = "") => request<Item>(`/api/items/${id}/review`, { method: "POST", body: j({ state, comment }) }),
  links: (id: number) => request<{ upstream: any[]; downstream: any[] }>(`/api/items/${id}/links`),
  versions: (id: number) => request<Version[]>(`/api/items/${id}/versions`),
  comments: (id: number) => request<Comment[]>(`/api/items/${id}/comments`),
  addComment: (id: number, body: string) => request<Comment>(`/api/items/${id}/comments`, { method: "POST", body: j({ body }) }),

  async download(pid: number, fmt: string) {
    const res = await fetch(`/api/projects/${pid}/export/${fmt}`, { headers: { Authorization: `Bearer ${auth.token}` } });
    if (!res.ok) throw new ApiError(res.status, "Export failed");
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? `blueprint.${fmt}`;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  },
};

export async function pollJob(id: number, onUpdate: (j: Job) => void): Promise<Job> {
  for (;;) {
    const job = await api.job(id);
    onUpdate(job);
    if (job.status === "succeeded" || job.status === "failed") return job;
    await new Promise((r) => setTimeout(r, 800));
  }
}
