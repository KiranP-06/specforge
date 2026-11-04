export function QualityBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return <span className="badge">no score</span>;
  const cls = score >= 85 ? "ok" : score >= 65 ? "warn" : "err";
  return <span className={`badge ${cls}`} title="Blueprint Quality Score">BQS {score.toFixed(1)}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    done: "ok", baselined: "ok", approved: "ok", succeeded: "ok", in_progress: "info", generating: "info", draft: "",
    blocked: "err", failed: "err", rejected: "err", todo: "",
  };
  return <span className={`badge ${cls[status] ?? ""}`}>{status.replace("_", " ")}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  const cls = severity === "error" ? "err" : severity === "warning" ? "warn" : "info";
  return <span className={`badge ${cls}`}>{severity}</span>;
}

export function Bar({ value, ok }: { value: number; ok?: boolean }) {
  return <div className={`bar ${ok ? "ok" : ""}`} aria-label={`${value}%`}><span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}
