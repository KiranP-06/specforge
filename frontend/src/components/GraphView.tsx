import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

// Layered layout: one column per item type, edges drawn as curves.
const LAYERS = ["requirement", "story", "module", "api", "entity", "test", "risk"];
const COLORS: Record<string, string> = { requirement: "#2c5282", story: "#2f855a", module: "#6b46c1", api: "#c05621", entity: "#2b6cb0", test: "#0e7c86", risk: "#c53030" };
const COL_W = 170, ROW_H = 26, PAD = 40;

type G = Awaited<ReturnType<typeof api.graph>>;

export default function GraphView({ projectId }: { projectId: number }) {
  const [g, setG] = useState<G | null>(null);
  const [focus, setFocus] = useState<number | null>(null);
  useEffect(() => { api.graph(projectId).then(setG); }, [projectId]);

  const layout = useMemo(() => {
    if (!g) return null;
    const pos = new Map<number, { x: number; y: number }>();
    let maxRows = 0;
    LAYERS.forEach((t, col) => {
      const nodes = g.nodes.filter((n) => n.type === t).sort((a, b) => a.key.localeCompare(b.key));
      maxRows = Math.max(maxRows, nodes.length);
      nodes.forEach((n, row) => pos.set(n.id, { x: PAD + col * COL_W, y: PAD + row * ROW_H }));
    });
    return { pos, width: PAD * 2 + LAYERS.length * COL_W, height: PAD * 2 + maxRows * ROW_H };
  }, [g]);

  const related = useMemo(() => {
    if (!g || focus == null) return null;
    const s = new Set<number>([focus]);
    // everything reachable downstream and upstream of the focused node
    for (const dir of ["down", "up"] as const) {
      const stack = [focus];
      while (stack.length) {
        const cur = stack.pop()!;
        for (const e of g.edges) {
          const [from, to] = dir === "down" ? [e.source, e.target] : [e.target, e.source];
          if (from === cur && !s.has(to)) { s.add(to); stack.push(to); }
        }
      }
    }
    return s;
  }, [g, focus]);

  if (!g || !layout) return <p className="muted">Loading…</p>;
  return (
    <div className="grid">
      <p className="small muted" style={{ margin: 0 }}>Click a node to highlight everything it depends on and everything that depends on it. Orange nodes are stale.</p>
      <div className="graph-wrap">
        <svg width={layout.width} height={layout.height} role="img" aria-label="Blueprint graph">
          {LAYERS.map((t, col) => <text key={t} x={PAD + col * COL_W} y={18} style={{ fontWeight: 700, fill: COLORS[t] }}>{t.toUpperCase()}</text>)}
          {g.edges.map((e) => {
            const a = layout.pos.get(e.source), b = layout.pos.get(e.target);
            if (!a || !b) return null;
            const hl = related?.has(e.source) && related?.has(e.target);
            const x1 = a.x + 60, x2 = b.x - 4, mx = (x1 + x2) / 2;
            return <path key={e.id} className={`edge ${hl ? "hl" : ""}`} opacity={related && !hl ? 0.15 : 0.7} d={`M${x1},${a.y} C${mx},${a.y} ${mx},${b.y} ${x2},${b.y}`} />;
          })}
          {g.nodes.map((n) => {
            const p = layout.pos.get(n.id);
            if (!p) return null;
            const dim = related && !related.has(n.id);
            return (
              <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1} style={{ cursor: "pointer" }} onClick={() => setFocus(focus === n.id ? null : n.id)}>
                <title>{n.title}</title>
                <circle r={6} fill={n.stale ? "#e8a321" : COLORS[n.type]} stroke={focus === n.id ? "#e8a321" : "none"} strokeWidth={3} />
                <text x={10} y={4}>{n.key}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
