// "Why this priority": every reason with the priority it argues for, its reference, and links to evidence.
import type { Evidence, Reason, Source } from "../api/client";
import { EvidenceChip } from "./EvidenceChip";
import { PRIORITY } from "./ui";

const KIND_LABEL: Record<string, string> = {
  red_flag: "Warning sign",
  vitals: "Vital signs",
  suspicious: "Suspicious input",
  conflict: "Conflict",
  ai_signal: "Noticed by AI",
  learned: "Learned from past clinician decisions",
  uncertainty: "Data quality",
  default: "No warning signs",
};

export function Reasons({ reasons, sources, onSelect }: { reasons: Reason[]; sources: Source[]; onSelect: (ev: Evidence) => void }) {
  return (
    <ul className="space-y-2">
      {reasons.map((r, i) => {
        const m = PRIORITY[r.priority];
        const [title, ...rest] = r.text.split(": ");
        const hasTitle = r.kind === "red_flag" && rest.length > 0;
        return (
          <li key={i} className={`rounded-md border-l-4 ${m.border} ${m.wash} px-3 py-2`}>
            <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span className={`font-bold ${m.text}`}>{r.priority}</span>
              <span className="text-xs text-ink-soft">{KIND_LABEL[r.kind] ?? r.kind}</span>
            </div>
            <p className="text-sm">
              {hasTitle ? (
                <>
                  <span className="font-bold">{title}.</span> {rest.join(": ")}
                </>
              ) : (
                r.text
              )}
            </p>
            {(r.reference || r.evidence.length > 0) && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                {r.evidence
                  .filter((e, j, arr) => e.source_id !== null && arr.findIndex((x) => x.source_id === e.source_id && x.start === e.start) === j)
                  .slice(0, 6)
                  .map((e, j) => (
                    <EvidenceChip key={j} ev={e} sources={sources} onSelect={onSelect} />
                  ))}
                {r.reference && <span className="text-xs text-ink-faint">Based on {r.reference}</span>}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
