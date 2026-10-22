// Audit log: every action by people, the AI and the system, with a tamper check over the hash chain.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Bot, Cog, ShieldCheck, ShieldX, User } from "lucide-react";
import { api, type AuditEntry } from "../api/client";
import { ACTION_LABELS, auditSummary } from "../components/AuditTrail";
import { Button, ErrorNote, Spinner } from "../components/ui";

export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actorType, setActorType] = useState("");
  const [action, setAction] = useState("");
  const [caseId, setCaseId] = useState("");
  const [verify, setVerify] = useState<Awaited<ReturnType<typeof api.verifyAudit>> | null>(null);
  const [checking, setChecking] = useState(false);

  const load = useCallback(() => {
    setRows(null);
    api
      .auditLog({ actor_type: actorType, action, case_id: caseId ? Number(caseId) : undefined, limit: 500 })
      .then(setRows)
      .catch((e) => setError(e.message));
  }, [actorType, action, caseId]);
  useEffect(load, [load]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Audit log</h1>
          <p className="text-sm text-ink-soft">Append-only record of actions by staff, the AI and the system. Entries hold ids and counts, never patient text.</p>
        </div>
        <div className="flex items-center gap-3">
          {verify &&
            (verify.ok ? (
              <span className="inline-flex items-center gap-1.5 text-sm font-bold text-p4">
                <ShieldCheck className="h-4 w-4" aria-hidden /> Intact: {verify.entries} entries verified
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 text-sm font-bold text-p1">
                <ShieldX className="h-4 w-4" aria-hidden /> {verify.detail}
              </span>
            ))}
          <Button
            busy={checking}
            onClick={async () => {
              setChecking(true);
              try {
                setVerify(await api.verifyAudit());
              } finally {
                setChecking(false);
              }
            }}
          >
            Check for tampering
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 rounded-lg border border-rule bg-panel p-3 text-sm">
        <label>
          Who{" "}
          <select value={actorType} onChange={(e) => setActorType(e.target.value)} className="ml-1 rounded border border-rule px-2 py-1">
            <option value="">Everyone</option>
            <option value="human">Staff</option>
            <option value="ai">AI</option>
            <option value="system">System</option>
          </select>
        </label>
        <label>
          Action{" "}
          <select value={action} onChange={(e) => setAction(e.target.value)} className="ml-1 rounded border border-rule px-2 py-1">
            <option value="">All actions</option>
            {Object.entries(ACTION_LABELS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          Case{" "}
          <input value={caseId} onChange={(e) => setCaseId(e.target.value.replace(/\D/g, ""))} placeholder="any" className="ml-1 w-20 rounded border border-rule px-2 py-1" />
        </label>
      </div>

      {error && <ErrorNote>{error}</ErrorNote>}
      {!rows && !error && <Spinner />}
      {rows && (
        <div className="overflow-x-auto rounded-lg border border-rule bg-panel">
          <table className="w-full min-w-[820px] text-left text-sm">
            <thead className="border-b border-rule text-xs text-ink-soft">
              <tr>
                <th className="px-3 py-2 font-normal">Time</th>
                <th className="px-3 py-2 font-normal">By</th>
                <th className="px-3 py-2 font-normal">Action</th>
                <th className="px-3 py-2 font-normal">Case</th>
                <th className="px-3 py-2 font-normal">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {rows.map((r) => {
                const Icon = r.actor_type === "human" ? User : r.actor_type === "ai" ? Bot : Cog;
                return (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap px-3 py-2 text-ink-soft">{new Date(r.ts.endsWith("Z") || r.ts.includes("+") ? r.ts : r.ts + "Z").toLocaleString("en-IN")}</td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <Icon className="h-4 w-4 text-ink-faint" aria-label={r.actor_type} /> {r.actor}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-bold">{ACTION_LABELS[r.action] ?? r.action}</td>
                    <td className="px-3 py-2">{r.case_id ? <Link to={`/cases/${r.case_id}`} className="text-accent">{r.case_id}</Link> : r.patient_id ? `patient ${r.patient_id}` : ""}</td>
                    <td className="px-3 py-2 text-ink-soft">{auditSummary(r)}</td>
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
