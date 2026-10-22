// One case: the suggested priority and why, the structured summary, flags, follow-up questions and
// the clinician's decision on the left; the original sources (with the selected evidence highlighted) on the right.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Cpu, EyeOff, FilePlus2, Lightbulb, RotateCw, TriangleAlert, UserX } from "lucide-react";
import { api, type CaseDetail as Detail, type Evidence } from "../api/client";
import { AuditTrail } from "../components/AuditTrail";
import { FlagList } from "../components/Flags";
import { FollowUps } from "../components/FollowUps";
import { NoteEditor } from "../components/NoteEditor";
import { Reasons } from "../components/Reasons";
import { SimilarCases } from "../components/SimilarCases";
import { SourceViewer } from "../components/SourceViewer";
import { Summary } from "../components/Summary";
import { Button, ErrorNote, Panel, PRIORITY, PriorityBadge, Spinner, minutes } from "../components/ui";
import { useNavigate } from "react-router-dom";

export default function CaseDetail() {
  const { id } = useParams();
  const caseId = Number(id);
  const navigate = useNavigate();
  const [withdrawing, setWithdrawing] = useState(false);
  const [withdrawReason, setWithdrawReason] = useState("");
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .getCase(caseId)
      .then((x) => {
        setD(x);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [caseId]);

  useEffect(load, [load]);
  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(null), 4000);
    return () => window.clearTimeout(t);
  }, [toast]);

  const select = (ev: Evidence) => {
    setEvidence(ev);
    if (ev.source_id !== null) setSourceId(ev.source_id);
  };
  const apply = (x: Detail, msg: string) => {
    const before = d?.triage?.priority;
    setD(x);
    const after = x.triage?.priority;
    setToast(before && after && before !== after ? `${msg} Priority changed from ${before} to ${after}.` : msg);
  };
  const run = async (key: string, fn: () => Promise<Detail>, msg: string) => {
    setBusy(key);
    setError(null);
    try {
      apply(await fn(), msg);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (error && !d) return <ErrorNote>Could not load case {caseId}: {error}</ErrorNote>;
  if (!d) return <Spinner label="Loading case" />;

  const t = d.triage;
  const ex = d.extraction;
  const p = d.final_priority ?? t?.priority ?? null;
  const finalized = d.status === "finalized";
  const waited = Math.floor((Date.now() - new Date(d.created_at.endsWith("Z") ? d.created_at : d.created_at + "Z").getTime()) / 60000);
  const flags = t?.validation?.flags ?? [];
  const can = (perm: string) => d.permissions.includes(perm);
  const canReview = can("triage:finalize");
  const clinicalHidden = !can("case:read_sources");
  const critical = flags.filter((f) => f.severity === "critical");

  return (
    <div className="space-y-4">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-ink-soft hover:text-ink">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Review queue
      </Link>

      <header className={`flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border-l-8 bg-panel px-5 py-4 ${p ? PRIORITY[p].border : "border-rule"}`}>
        <div>
          <h1 className="text-2xl font-bold">{d.patient.name}</h1>
          <p className="text-sm text-ink-soft">
            {d.patient.age_years ?? "?"} years, {d.patient.sex ?? "sex not stated"}, case {d.id}. Waiting {minutes(waited)}.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <PriorityBadge p={p} size="lg" />
          <div className="text-sm">
            {finalized ? (
              <span className="font-bold">Finalized by clinician{d.final_priority !== t?.priority && ` (AI suggested ${t?.priority})`}</span>
            ) : (
              <>
                <div className="font-bold">AI suggestion, awaiting review</div>
                <div className="text-ink-soft">{t?.target_minutes === 0 ? "Review immediately" : `Review within ${t?.target_minutes} min`}</div>
              </>
            )}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {t?.validation && (
            <span className="text-sm text-ink-soft" title="Share of the information this complaint needs">
              Information complete: <span className={`font-bold ${t.validation.completeness < 0.6 ? "text-unclear" : "text-ink"}`}>{Math.round(t.validation.completeness * 100)}%</span>
            </span>
          )}
          {can("consent:withdraw") && !d.withdrawn && (
            <Button variant="ghost" onClick={() => setWithdrawing((w) => !w)}>
              <UserX className="h-4 w-4" aria-hidden /> Withdraw consent
            </Button>
          )}
          {!finalized && !d.withdrawn && (
            <>
              {can("case:upload") && (
              <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-rule px-3 py-1.5 text-sm font-bold hover:border-ink-faint">
                <FilePlus2 className="h-4 w-4 text-accent" aria-hidden /> {busy === "upload" ? "Reading file" : "Add report or audio"}
                <input
                  type="file"
                  multiple
                  accept="image/*,application/pdf,audio/*"
                  className="sr-only"
                  disabled={busy !== null}
                  onChange={(e) => {
                    const files = Array.from(e.target.files ?? []);
                    e.target.value = "";
                    if (files.length) void run("upload", () => api.addSources(d.id, files), "File added and case re-checked.");
                  }}
                />
              </label>
              )}
              {can("case:retriage") && (
                <Button busy={busy === "retriage"} disabled={busy !== null} onClick={() => run("retriage", () => api.retriage(d.id), "Case re-checked.")}>
                  <RotateCw className="h-4 w-4" aria-hidden /> Re-check
                </Button>
              )}
            </>
          )}
        </div>
      </header>

      {withdrawing && (
        <div className="space-y-2 rounded-lg border border-p1/40 bg-p1-wash p-4 text-sm">
          <p className="font-bold">Record that the patient withdraws consent?</p>
          <p>Processing stops at once and the case leaves the queue. The data protection officer then erases the data. This cannot be undone from here.</p>
          <input
            value={withdrawReason}
            onChange={(e) => setWithdrawReason(e.target.value)}
            placeholder="Optional reason, e.g. patient asked at the desk"
            className="w-full rounded border border-rule bg-panel px-2 py-1.5"
            maxLength={300}
          />
          <div className="flex gap-2">
            <Button
              variant="danger"
              busy={busy === "withdraw"}
              onClick={async () => {
                setBusy("withdraw");
                try {
                  await api.withdraw(d.id, withdrawReason.trim() || undefined);
                  navigate("/", { replace: true });
                } catch (e) {
                  setError((e as Error).message);
                  setBusy(null);
                }
              }}
            >
              Withdraw consent
            </Button>
            <Button variant="ghost" onClick={() => setWithdrawing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
      {d.withdrawn && (
        <p className="rounded-md bg-p1-wash px-4 py-2 text-sm font-bold text-p1">The patient withdrew consent. This case is read-only and waiting for erasure.</p>
      )}
      {clinicalHidden && (
        <p className="flex items-center gap-2 rounded-md bg-missing-wash px-4 py-2 text-sm">
          <EyeOff className="h-4 w-4" aria-hidden /> Patient messages, reports, transcripts and the clinical note are hidden for your role. You can see the priority and status.
        </p>
      )}
      {toast && (
        <div role="status" className="rounded-md bg-ink px-4 py-2 text-sm text-white">
          {toast}
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {critical.length > 0 && !finalized && (
        <div className="flex items-start gap-2 rounded-md border border-suspicious/40 bg-suspicious-wash px-4 py-2.5 text-sm">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-suspicious" aria-hidden />
          <span>
            <span className="font-bold">Check before relying on this summary:</span> {critical.map((f) => f.text).join(" ")}
          </span>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-7">
          {d.agent && (
            <section className="rounded-lg border border-accent/40 bg-accent-wash px-4 py-3" aria-label="Learned suggestion">
              <h2 className="flex items-center gap-2 font-bold">
                <Lightbulb className="h-4 w-4 text-accent" aria-hidden /> Learned suggestion:{" "}
                {d.agent.abstained ? <span className="font-normal">no suggestion (case unlike past decisions)</span> : <PriorityBadge p={d.agent.predicted} size="sm" />}
              </h2>
              {!d.agent.abstained && (
                <p className="mt-1 text-sm">
                  Based on {d.agent.model_version} past clinician decisions; confidence {Math.round(d.agent.confidence * 100)}%. Main reasons:{" "}
                  {d.agent.explanation.map((e) => e.label).join(", ") || "general pattern"}.
                  {d.agent.predicted && d.agent.predicted !== d.agent.rules_priority && (
                    <span className="text-ink-soft">
                      {" "}
                      The rules suggested {d.agent.rules_priority}.
                      {["P1", "P2", "P3", "P4"].indexOf(d.agent.predicted) > ["P1", "P2", "P3", "P4"].indexOf(d.agent.rules_priority) &&
                        " A learned suggestion never lowers the rules' priority; it is shown for your judgement only."}
                    </span>
                  )}
                </p>
              )}
            </section>
          )}

          {t && (
            <Panel title="Why this priority">
              <Reasons reasons={t.reasons} sources={d.sources} onSelect={select} />
            </Panel>
          )}

          {ex && t && (
            <Panel
              title="Patient summary"
              action={
                <span className="inline-flex items-center gap-1 text-xs text-ink-faint">
                  <Cpu className="h-3.5 w-3.5" aria-hidden /> {d.extraction_provider ?? "rules"}
                  {d.extraction_latency_ms != null && `, ${(d.extraction_latency_ms / 1000).toFixed(1)} s`}
                </span>
              }
            >
              <Summary ex={ex} triage={t} sel={{ onSelect: select, sources: d.sources, active: evidence }} />
            </Panel>
          )}

          <Panel title="Missing, unclear, conflicting or suspicious">
            <FlagList flags={flags} onSelectSource={(sid) => setSourceId(sid)} />
          </Panel>

          {can("case:read_clinical") && (
            <Panel title="Similar past decisions">
              <SimilarCases caseId={d.id} refreshKey={d.note?.id ?? 0} />
            </Panel>
          )}

          {!finalized && !d.withdrawn && can("case:answer") && (
            <Panel title="Follow-up questions">
              <FollowUps
                items={t?.validation?.followups ?? []}
                disabled={busy !== null}
                onSubmit={async (answers) => {
                  await run("answers", () => api.answer(d.id, answers), `Saved ${answers.length} answer${answers.length === 1 ? "" : "s"} and re-checked.`);
                }}
              />
            </Panel>
          )}

          {d.note && (
          <Panel title={finalized ? "Final triage note" : "Triage note and decision"}>
            <NoteEditor
              detail={d}
              canReview={canReview}
              onSave={async (content) => {
                await run("note", () => api.saveNote(d.id, content), "Note saved as a new version.");
              }}
              onReview={async (b) => {
                await run("review", () => api.review(d.id, b), b.action === "override" ? `Overridden to ${b.final_priority} and finalized.` : `Approved ${b.final_priority} and finalized.`);
              }}
            />
          </Panel>
          )}
          {!d.note && can("case:read") && !can("case:read_clinical") && (
            <p className="text-sm text-ink-soft">The triage note is visible to doctors and nurses only.</p>
          )}

          {can("audit:read") && (
          <details className="rounded-lg border border-rule bg-panel">
            <summary className="cursor-pointer px-4 py-2.5 font-bold">Activity log</summary>
            <div className="border-t border-rule p-4">
              <AuditTrail caseId={d.id} refreshKey={d.note?.id ?? 0} />
            </div>
          </details>
          )}
        </div>

        {!clinicalHidden && (
        <aside className="lg:col-span-5">
          <div className="overflow-hidden rounded-lg border border-rule bg-panel lg:sticky lg:top-20 lg:h-[calc(100vh-7rem)]">
            <div className="border-b border-rule px-4 py-2.5">
              <h2 className="font-bold">Sources</h2>
              <p className="text-xs text-ink-soft">Click any source tag on the left to see exactly where a fact came from.</p>
            </div>
            <div className="h-[calc(100%-3.75rem)]">
              <SourceViewer sources={d.sources} selectedId={sourceId} evidence={evidence} onSelectSource={(sid) => setSourceId(sid)} />
            </div>
          </div>
        </aside>
        )}
      </div>
    </div>
  );
}
