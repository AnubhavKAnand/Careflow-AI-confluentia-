// Follow-up questions with inline answers. Answers are sent together and the case is re-triaged.
import { useState } from "react";
import { Bot, Check, Stethoscope, User, X } from "lucide-react";
import type { FollowUp } from "../api/client";
import { Button } from "./ui";

type Answer = { yes?: boolean; answer?: string };

const WHO = {
  patient: { label: "Ask the patient", icon: User },
  staff: { label: "For staff", icon: Stethoscope },
  clinician: { label: "For the clinician to verify", icon: Stethoscope },
};

export function FollowUps({
  items,
  onSubmit,
  disabled,
}: {
  items: FollowUp[];
  onSubmit: (answers: { question_id: string; answer?: string; yes?: boolean }[]) => Promise<void>;
  disabled?: boolean;
}) {
  const [answers, setAnswers] = useState<Record<string, Answer>>({});
  const [busy, setBusy] = useState(false);
  const answerable = (q: FollowUp) => q.origin === "rule" || q.origin === "ai";
  const filled = Object.entries(answers).filter(([, a]) => a.yes !== undefined || (a.answer && a.answer.trim()));

  if (!items.length) return <p className="text-sm text-ink-soft">No follow-up questions. The information needed for this complaint is complete.</p>;

  const groups = (["patient", "staff", "clinician"] as const).map((t) => ({ t, qs: items.filter((q) => q.target === t) })).filter((g) => g.qs.length);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await onSubmit(filled.map(([question_id, a]) => ({ question_id, ...a })));
          setAnswers({});
        } finally {
          setBusy(false);
        }
      }}
      className="space-y-4"
    >
      {groups.map(({ t, qs }) => {
        const W = WHO[t];
        return (
          <div key={t}>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-sm font-bold text-ink-soft">
              <W.icon className="h-4 w-4" aria-hidden /> {W.label}
            </h3>
            <ul className="space-y-2">
              {qs.map((q) => {
                const a = answers[q.id] ?? {};
                const set = (v: Answer) => setAnswers((s) => ({ ...s, [q.id]: { ...s[q.id], ...v } }));
                return (
                  <li key={q.id} className={`rounded-md border px-3 py-2 ${q.priority === "critical" ? "border-p2/50 bg-p2-wash/50" : "border-rule"}`}>
                    <div className="flex items-start gap-2">
                      <div className="flex-1">
                        <p className="text-sm font-bold">{q.text}</p>
                        {q.language !== "en" && <p className="text-xs text-ink-soft">{q.text_en}</p>}
                        <p className="mt-0.5 flex items-center gap-1 text-xs text-ink-faint">
                          {q.origin === "ai" && <Bot className="h-3.5 w-3.5 text-suspicious" aria-label="AI-suggested" />}
                          {q.priority === "critical" && <span className="font-bold text-p2">Could change the priority.</span>} {q.reason}
                        </p>
                      </div>
                      {answerable(q) && q.answer_type === "yes_no" && (
                        <div className="flex shrink-0 gap-1" role="group" aria-label="Answer">
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() => set({ yes: a.yes === true ? undefined : true })}
                            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-bold ${a.yes === true ? "border-accent bg-accent text-white" : "border-rule"}`}
                          >
                            <Check className="h-3.5 w-3.5" aria-hidden /> Yes
                          </button>
                          <button
                            type="button"
                            disabled={disabled}
                            onClick={() => set({ yes: a.yes === false ? undefined : false })}
                            className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs font-bold ${a.yes === false ? "border-ink bg-ink text-white" : "border-rule"}`}
                          >
                            <X className="h-3.5 w-3.5" aria-hidden /> No
                          </button>
                        </div>
                      )}
                    </div>
                    {answerable(q) && q.answer_type === "free_text" && (
                      <input
                        disabled={disabled}
                        value={a.answer ?? ""}
                        onChange={(e) => set({ answer: e.target.value })}
                        placeholder={q.target === "staff" ? "e.g. pulse 104, BP 132/84, SpO2 96%" : "Type the answer in any language"}
                        aria-label={`Answer: ${q.text_en}`}
                        className="mt-2 w-full rounded border border-rule px-2 py-1 text-sm"
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" busy={busy} disabled={disabled || filled.length === 0}>
          Save {filled.length || ""} answer{filled.length === 1 ? "" : "s"} and re-check priority
        </Button>
        {filled.length === 0 && <span className="text-xs text-ink-faint">Answer any question above to enable.</span>}
      </div>
    </form>
  );
}
