// Review queue: who to see first, why, what is uncertain, and how long they have waited against their target.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AudioLines, FileImage, RefreshCw, Search } from "lucide-react";
import { api, type CaseListItem, type Priority } from "../api/client";
import { FlagCounts } from "../components/Flags";
import { TimeBar } from "../components/TimeBar";
import { ErrorNote, PRIORITY, PriorityBadge, Spinner } from "../components/ui";

type Lane = "open" | Priority | "overdue" | "finalized";
const REFRESH_MS = 20_000;

export default function Dashboard() {
  const [cases, setCases] = useState<CaseListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lane, setLane] = useState<Lane>("open");
  const [q, setQ] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    api
      .listCases()
      .then((c) => {
        setCases(c);
        setError(null);
        setUpdated(new Date());
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const open = useMemo(() => (cases ?? []).filter((c) => c.status !== "finalized"), [cases]);
  const counts = useMemo(() => {
    const by: Record<string, number> = { open: open.length, overdue: open.filter((c) => c.overdue).length, finalized: (cases ?? []).length - open.length };
    (["P1", "P2", "P3", "P4"] as Priority[]).forEach((p) => (by[p] = open.filter((c) => c.priority === p).length));
    return by;
  }, [cases, open]);

  const shown = useMemo(() => {
    let list = cases ?? [];
    if (lane === "open") list = open;
    else if (lane === "finalized") list = list.filter((c) => c.status === "finalized");
    else if (lane === "overdue") list = open.filter((c) => c.overdue);
    else list = open.filter((c) => c.priority === lane);
    const needle = q.trim().toLowerCase();
    if (needle) list = list.filter((c) => `${c.patient_name} ${c.chief_complaint ?? ""} ${c.id}`.toLowerCase().includes(needle));
    return list;
  }, [cases, open, lane, q]);

  const lanes: { key: Lane; label: string; tone?: string }[] = [
    { key: "open", label: "All open" },
    { key: "P1", label: "P1 Immediate", tone: PRIORITY.P1.text },
    { key: "P2", label: "P2 Very urgent", tone: PRIORITY.P2.text },
    { key: "P3", label: "P3 Urgent", tone: PRIORITY.P3.text },
    { key: "P4", label: "P4 Routine", tone: PRIORITY.P4.text },
    { key: "overdue", label: "Past target", tone: "text-p1" },
    { key: "finalized", label: "Reviewed" },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Review queue</h1>
          <p className="text-sm text-ink-soft">
            {counts.P1 > 0 ? (
              <span className="font-bold text-p1">
                {counts.P1} {counts.P1 === 1 ? "patient needs" : "patients need"} immediate review.{" "}
              </span>
            ) : null}
            Ordered by suggested priority, then by time waited against each priority's target.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-faint">
          {updated && <span>Updated {updated.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>}
          <button onClick={load} className="inline-flex items-center gap-1 rounded-md border border-rule bg-panel px-2 py-1 text-ink-soft hover:text-ink">
            <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Refresh
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1 rounded-lg border border-rule bg-panel p-1" role="tablist" aria-label="Filter queue">
          {lanes.map((l) => (
            <button
              key={l.key}
              role="tab"
              aria-selected={lane === l.key}
              onClick={() => setLane(l.key)}
              className={`rounded-md px-3 py-1.5 text-sm ${lane === l.key ? "bg-ink text-white" : `hover:bg-ward ${l.tone ?? "text-ink-soft"}`}`}
            >
              {l.label} <span className={`ml-1 font-bold ${lane === l.key ? "text-white" : ""}`}>{counts[l.key] ?? 0}</span>
            </button>
          ))}
        </div>
        <label className="relative ml-auto">
          <span className="sr-only">Search patients</span>
          <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-ink-faint" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or complaint" className="w-64 rounded-md border border-rule bg-panel py-1.5 pl-8 pr-2 text-sm" />
        </label>
      </div>

      {error && <ErrorNote>Could not load the queue: {error}. Is the backend running on port 8000?</ErrorNote>}
      {!cases && !error && <Spinner label="Loading queue" />}

      {cases && shown.length === 0 && (
        <div className="rounded-lg border border-dashed border-rule bg-panel p-10 text-center">
          <p className="font-bold">{lane === "open" ? "No patients waiting for review." : "No cases in this view."}</p>
          <p className="mt-1 text-sm text-ink-soft">
            New cases appear here as soon as they are submitted. <Link to="/intake" className="font-bold text-accent">Add a case</Link>
          </p>
        </div>
      )}

      {shown.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-rule bg-panel">
          <table className="w-full min-w-[960px] text-left text-sm">
            <thead className="border-b border-rule text-xs text-ink-soft">
              <tr>
                <th className="w-2 p-0" aria-hidden />
                <th className="px-3 py-2 font-normal">Priority</th>
                <th className="px-3 py-2 font-normal">Patient</th>
                <th className="px-3 py-2 font-normal">Main complaint and top reason</th>
                <th className="px-3 py-2 font-normal">Needs checking</th>
                <th className="px-3 py-2 font-normal">Complete</th>
                <th className="px-3 py-2 font-normal">Waiting</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => {
                const p = (c.final_priority ?? c.priority) as Priority | null;
                const m = p ? PRIORITY[p] : null;
                return (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/cases/${c.id}`)}
                    className={`cursor-pointer border-b border-rule last:border-0 hover:bg-ward/70 ${c.overdue ? "bg-p1-wash/40" : ""}`}
                  >
                    <td className={`w-2 p-0 ${m?.bg ?? "bg-rule"}`} aria-hidden />
                    <td className="px-3 py-3 align-top">
                      <PriorityBadge p={p} size="sm" showLabel={false} />
                      {c.final_priority && c.final_priority !== c.priority && <div className="mt-1 text-xs text-ink-faint">AI said {c.priority}</div>}
                    </td>
                    <td className="px-3 py-3 align-top">
                      <Link to={`/cases/${c.id}`} onClick={(e) => e.stopPropagation()} className="font-bold hover:text-accent">
                        {c.patient_name}
                      </Link>
                      <div className="text-xs text-ink-soft">
                        {c.age_years ?? "?"} y, {c.sex ?? "?"}, case {c.id}
                      </div>
                    </td>
                    <td className="max-w-md px-3 py-3 align-top">
                      <div className="flex items-center gap-1.5 font-bold">
                        {c.chief_complaint ?? <span className="font-normal text-ink-faint">Not stated</span>}
                        {c.source_kinds.includes("report") && <FileImage className="h-3.5 w-3.5 text-ink-faint" aria-label="has report" />}
                        {c.source_kinds.includes("voice") && <AudioLines className="h-3.5 w-3.5 text-ink-faint" aria-label="has voice note" />}
                      </div>
                      <div className="line-clamp-2 text-xs text-ink-soft">{c.top_reason}</div>
                    </td>
                    <td className="px-3 py-3 align-top">
                      <FlagCounts counts={c.flag_counts} />
                    </td>
                    <td className="px-3 py-3 align-top">
                      {c.completeness != null && (
                        <span className={`text-sm ${c.completeness < 0.6 ? "font-bold text-unclear" : "text-ink-soft"}`}>{Math.round(c.completeness * 100)}%</span>
                      )}
                    </td>
                    <td className="px-3 py-3 align-top">
                      <TimeBar waiting={c.waiting_minutes} target={c.target_minutes} priority={p} done={c.status === "finalized"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
