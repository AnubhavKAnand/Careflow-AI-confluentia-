import { useEffect, useState } from "react";
import { Bot, Cog, User } from "lucide-react";
import { api, type AuditEntry } from "../api/client";

export const ACTION_LABELS: Record<string, string> = {
  consent_recorded: "Consent recorded",
  case_created: "Case created",
  source_uploaded: "File uploaded",
  report_processed: "Report read",
  voice_processed: "Voice note transcribed",
  patient_message_processed: "Message processed",
  followup_answer_processed: "Answers processed",
  extraction_completed: "Information extracted",
  suspicious_instruction_detected: "Suspicious instruction detected",
  triage_suggested: "Priority suggested",
  validation_completed: "Checks completed",
  note_drafted: "Note drafted",
  note_edited: "Note edited",
  followup_answered: "Follow-up answered",
  triage_approved: "Priority approved",
  priority_overridden: "Priority overridden",
  retriage_requested: "Re-triage requested",
  case_viewed: "Case viewed",
  source_file_viewed: "Original file viewed",
  login: "Signed in",
  login_failed: "Failed sign-in",
  consent_withdrawn: "Consent withdrawn",
  patient_data_erased: "Patient data erased",
  data_sent_external: "Data sent to external model",
  extraction_failed: "Extraction failed",
};

export function auditSummary(e: AuditEntry): string {
  const d = e.details ?? {};
  if (e.action === "triage_suggested") return `${d.priority}${(d.red_flags as string[])?.length ? `, flags: ${(d.red_flags as string[]).join(", ")}` : ""}`;
  if (e.action === "priority_overridden" || e.action === "triage_approved")
    return `AI ${d.ai_priority}, final ${d.final_priority}${d.reason_given ? ", reason recorded" : ""}`;
  if (e.action === "data_sent_external") {
    const calls = (d.calls as { provider: string; purpose: string; redactions: Record<string, number> }[]) ?? [];
    const red = calls.reduce((n, c) => n + Object.values(c.redactions ?? {}).reduce((a, b) => a + b, 0), 0);
    return `${calls.length} call(s) to ${[...new Set(calls.map((c) => c.provider))].join(", ")}; ${red} identifier(s) removed first`;
  }
  if (e.action === "patient_data_erased") return `${d.cases} case(s), ${d.sources} source(s), ${d.files} file(s) deleted`;
  if (e.action === "consent_withdrawn") return d.by_patient ? "by the patient with their code" : "recorded by staff";
  if (e.action === "suspicious_instruction_detected") return `${(d.findings as unknown[])?.length ?? 0} finding(s)`;
  if (e.action === "extraction_completed") return `${d.latency_ms} ms${d.fallback_used ? ", fallback used" : ""}`;
  if (e.action.endsWith("_processed") && d.avg_confidence != null) return `confidence ${Math.round(Number(d.avg_confidence) * 100)}%`;
  return "";
}

export function AuditTrail({ caseId, refreshKey }: { caseId: number; refreshKey: unknown }) {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [hideViews, setHideViews] = useState(true);
  useEffect(() => {
    api.audit(caseId).then(setRows).catch(() => setRows([]));
  }, [caseId, refreshKey]);
  if (!rows) return null;
  const shown = rows.filter((r) => !(hideViews && (r.action === "case_viewed" || r.action === "source_file_viewed")));
  return (
    <div>
      <label className="mb-2 flex items-center gap-2 text-xs text-ink-soft">
        <input type="checkbox" checked={hideViews} onChange={(e) => setHideViews(e.target.checked)} /> Hide views
      </label>
      <ol className="space-y-1.5 text-sm">
        {shown.map((r) => {
          const Icon = r.actor_type === "human" ? User : r.actor_type === "ai" ? Bot : Cog;
          return (
            <li key={r.id} className="grid grid-cols-[auto_1fr] gap-x-2">
              <Icon className={`mt-0.5 h-4 w-4 ${r.actor_type === "human" ? "text-accent" : "text-ink-faint"}`} aria-label={r.actor_type} />
              <div>
                <span className="font-bold">{ACTION_LABELS[r.action] ?? r.action}</span> <span className="text-ink-soft">{auditSummary(r)}</span>
                <div className="text-xs text-ink-faint">
                  {new Date(r.ts.endsWith("Z") || r.ts.includes("+") ? r.ts : r.ts + "Z").toLocaleString("en-IN")} by {r.actor}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
