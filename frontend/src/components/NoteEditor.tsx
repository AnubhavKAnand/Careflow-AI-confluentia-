// Clinician decision: edit the draft note, then approve the suggested priority or override it with a reason.
import { useEffect, useState } from "react";
import { Lock } from "lucide-react";
import type { CaseDetail, Priority } from "../api/client";
import { Button, PRIORITY, PriorityBadge } from "./ui";

export function NoteEditor({
  detail,
  canReview,
  onSave,
  onReview,
}: {
  detail: CaseDetail;
  canReview: boolean;
  onSave: (content: string) => Promise<void>;
  onReview: (b: { action: "approve" | "override"; final_priority: Priority; reason?: string; note_content?: string }) => Promise<void>;
}) {
  const note = detail.note;
  const ai = detail.triage?.priority ?? null;
  const finalized = detail.status === "finalized";
  const [text, setText] = useState(note?.content ?? "");
  const [choice, setChoice] = useState<Priority | null>(ai);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"save" | "review" | null>(null);

  useEffect(() => {
    setText(note?.content ?? "");
    setChoice(detail.final_priority ?? ai);
  }, [note?.id, ai, detail.final_priority]);

  const dirty = text !== (note?.content ?? "");
  const override = choice !== null && choice !== ai;

  if (finalized) {
    return (
      <div className="space-y-3">
        <p className="flex items-center gap-2 text-sm">
          <Lock className="h-4 w-4 text-ink-soft" aria-hidden /> Finalized with priority <PriorityBadge p={detail.final_priority} size="sm" />
          {detail.final_priority !== ai && <span className="text-ink-soft">(AI suggested {ai})</span>}
        </p>
        <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-md border border-rule bg-ward/60 p-3 font-sans text-sm">{note?.content}</pre>
        <p className="text-xs text-ink-faint">
          Version {note?.version}, approved by {note?.author}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-1 flex items-center justify-between text-xs text-ink-soft">
          <label htmlFor="note">
            Triage note, version {note?.version} by {note?.author_type === "ai" ? "AI (draft)" : note?.author}
          </label>
          {dirty && <span className="font-bold text-p2">Unsaved changes</span>}
        </div>
        <textarea
          id="note"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!canReview}
          rows={18}
          className="w-full rounded-md border border-rule bg-panel p-3 text-sm leading-relaxed disabled:bg-ward/60"
        />
        {canReview && (
          <Button
            className="mt-2"
            disabled={!dirty}
            busy={busy === "save"}
            onClick={async () => {
              setBusy("save");
              try {
                await onSave(text);
              } finally {
                setBusy(null);
              }
            }}
          >
            Save as new version
          </Button>
        )}
      </div>

      {canReview ? (
        <fieldset className="space-y-3 rounded-md border border-rule p-3">
          <legend className="px-1 text-sm font-bold">Final priority</legend>
          {detail.learning_mode === "shadow" && (
            <p className="text-xs text-ink-soft">Shadow learning is on: your decision teaches the learned agent. Its own guess for this case is hidden from you so it cannot sway you.</p>
          )}
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Final priority">
            {(["P1", "P2", "P3", "P4"] as Priority[]).map((p) => (
              <button
                key={p}
                type="button"
                role="radio"
                aria-checked={choice === p}
                onClick={() => setChoice(p)}
                className={`rounded-md border-2 px-3 py-1.5 text-sm font-bold ${
                  choice === p ? `${PRIORITY[p].bg} border-transparent text-white` : `${PRIORITY[p].border} ${PRIORITY[p].text} bg-panel`
                }`}
              >
                {p} {PRIORITY[p].label}
                {p === ai && <span className="ml-1 font-normal opacity-80">(AI)</span>}
              </button>
            ))}
          </div>
          {override && (
            <div>
              <label htmlFor="reason" className="text-sm font-bold">
                Why are you changing the AI's suggestion? <span className="font-normal text-ink-soft">Required. This helps the system learn.</span>
              </label>
              <input
                id="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. Pain is reproducible on palpation; vitals normal on re-check"
                className="mt-1 w-full rounded border border-rule px-2 py-1.5 text-sm"
              />
            </div>
          )}
          <Button
            variant={override ? "danger" : "primary"}
            disabled={!choice || (override && !reason.trim())}
            busy={busy === "review"}
            onClick={async () => {
              if (!choice) return;
              setBusy("review");
              try {
                await onReview({
                  action: override ? "override" : "approve",
                  final_priority: choice,
                  reason: override ? reason.trim() : undefined,
                  note_content: dirty ? text : undefined,
                });
              } finally {
                setBusy(null);
              }
            }}
          >
            {override ? `Override to ${choice} and finalize` : `Approve ${choice ?? ""} and finalize`}
          </Button>
        </fieldset>
      ) : (
        <p className="rounded-md bg-ward px-3 py-2 text-sm text-ink-soft">Only doctors and nurses can edit or finalize the triage note. Switch role in the top bar to review.</p>
      )}
    </div>
  );
}
