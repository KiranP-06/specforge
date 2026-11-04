import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type Item, type ItemType } from "../api";
import { useSession } from "../App";
import ItemDrawer from "./ItemDrawer";
import { StatusBadge } from "./Badges";

const TYPES: { type: ItemType; label: string }[] = [
  { type: "requirement", label: "Requirements" }, { type: "story", label: "Stories" }, { type: "module", label: "Modules" },
  { type: "api", label: "APIs" }, { type: "entity", label: "Entities" }, { type: "test", label: "Tests" }, { type: "risk", label: "Risks" },
  { type: "stakeholder", label: "Stakeholders" }, { type: "constraint", label: "Constraints" },
];

export default function BlueprintPanel({ projectId, onChanged }: { projectId: number; onChanged: () => void }) {
  const { user } = useSession();
  const [items, setItems] = useState<Item[]>([]);
  const [type, setType] = useState<ItemType>("requirement");
  const [selected, setSelected] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const [onlyStale, setOnlyStale] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  const load = useCallback(() => api.items(projectId).then(setItems), [projectId]);
  useEffect(() => { load(); }, [load]);

  const counts = useMemo(() => items.reduce<Record<string, number>>((m, i) => ({ ...m, [i.type]: (m[i.type] ?? 0) + 1 }), {}), [items]);
  const staleCount = items.filter((i) => i.stale).length;
  const visible = items.filter((i) => (onlyStale ? i.stale : i.type === type) &&
    (!filter || `${i.key} ${i.title} ${i.description}`.toLowerCase().includes(filter.toLowerCase())));
  const selectedItem = items.find((i) => i.id === selected) ?? null;

  async function add() {
    if (!newTitle.trim()) return;
    const it = await api.createItem(projectId, { type, title: newTitle.trim() });
    setNewTitle(""); await load(); setSelected(it.id); onChanged();
  }

  return (
    <div className="layout-split">
      <div className="grid" style={{ gap: ".75rem" }}>
        <div className="row">
          {TYPES.filter((t) => counts[t.type]).map((t) => (
            <button key={t.type} className={!onlyStale && type === t.type ? "primary" : ""} onClick={() => { setType(t.type); setOnlyStale(false); }}>
              {t.label} <span className="muted">({counts[t.type]})</span>
            </button>
          ))}
          {staleCount > 0 && <button className={onlyStale ? "primary" : ""} onClick={() => setOnlyStale(true)}>⚠ Needs review ({staleCount})</button>}
        </div>
        <input placeholder="Filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="list">
          {visible.map((i) => (
            <div key={i.id} className={`list-item ${i.stale ? "stale" : ""} ${selected === i.id ? "selected" : ""}`} onClick={() => setSelected(i.id)}>
              <div className="row small">
                <span className="badge key">{i.key}</span>
                {i.data.kind && <span className="badge">{i.data.kind}{i.data.category && i.data.category !== "functional" ? ` · ${i.data.category}` : ""}</span>}
                {i.data.priority && <span className="badge">{i.data.priority}</span>}
                {i.type === "risk" && <span className="badge warn">exposure {i.data.exposure}</span>}
                <StatusBadge status={i.status} />
                {i.review_state !== "draft" && <StatusBadge status={i.review_state} />}
                {i.origin !== "generated" && <span className="badge info">{i.origin}</span>}
                {i.stale && <span className="badge warn">stale</span>}
                <span className="spacer" /><span className="muted">v{i.version}</span>
              </div>
              <div>{i.title}</div>
            </div>
          ))}
          {visible.length === 0 && <p className="muted">Nothing here.</p>}
        </div>
        {user?.role !== "reviewer" && !onlyStale && (
          <div className="row">
            <input placeholder={`Add a ${type} manually…`} value={newTitle} onChange={(e) => setNewTitle(e.target.value)} style={{ flex: 1, width: "auto" }}
              onKeyDown={(e) => e.key === "Enter" && add()} />
            <button onClick={add}>Add</button>
          </div>
        )}
      </div>
      <div className="drawer">
        {selectedItem ? (
          <ItemDrawer key={selectedItem.id} item={selectedItem} onChanged={() => { load(); onChanged(); }} onSelect={setSelected} />
        ) : <div className="card muted">Select an item to view its links, edit it, see change impact, history and comments.</div>}
      </div>
    </div>
  );
}
