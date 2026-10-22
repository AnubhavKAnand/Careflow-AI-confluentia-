import { CircleHelp, FileQuestion, ShieldAlert, Split } from "lucide-react";
import type { Flag, FlagType } from "../api/client";

export const FLAG_META: Record<FlagType, { label: string; icon: typeof ShieldAlert; text: string; wash: string }> = {
  suspicious: { label: "Suspicious", icon: ShieldAlert, text: "text-suspicious", wash: "bg-suspicious-wash" },
  conflicting: { label: "Conflicting", icon: Split, text: "text-conflicting", wash: "bg-conflicting-wash" },
  unclear: { label: "Unclear", icon: CircleHelp, text: "text-unclear", wash: "bg-unclear-wash" },
  missing: { label: "Missing", icon: FileQuestion, text: "text-missing", wash: "bg-missing-wash" },
};
const ORDER: FlagType[] = ["suspicious", "conflicting", "unclear", "missing"];

/** Compact counts for the queue row. */
export function FlagCounts({ counts }: { counts: Partial<Record<FlagType, number>> }) {
  const shown = ORDER.filter((t) => (counts[t] ?? 0) > 0);
  if (!shown.length) return <span className="text-xs text-ink-faint">none</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((t) => {
        const m = FLAG_META[t];
        const Icon = m.icon;
        return (
          <span key={t} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-bold ${m.wash} ${m.text}`} title={`${counts[t]} ${m.label.toLowerCase()}`}>
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {counts[t]}
            <span className="sr-only">{m.label}</span>
          </span>
        );
      })}
    </div>
  );
}

/** Full flags panel on the case page, grouped by type. */
export function FlagList({ flags, onSelectSource }: { flags: Flag[]; onSelectSource: (id: number) => void }) {
  const visible = flags.filter((f) => f.severity !== "info");
  if (!visible.length) return <p className="text-sm text-ink-soft">Nothing missing, unclear, conflicting or suspicious was found.</p>;
  return (
    <div className="space-y-4">
      {ORDER.map((type) => {
        const items = visible.filter((f) => f.type === type);
        if (!items.length) return null;
        const m = FLAG_META[type];
        const Icon = m.icon;
        return (
          <div key={type}>
            <h3 className={`mb-1.5 flex items-center gap-1.5 text-sm font-bold ${m.text}`}>
              <Icon className="h-4 w-4" aria-hidden /> {m.label} ({items.length})
            </h3>
            <ul className="space-y-1.5">
              {items.map((f, i) => (
                <li key={i} className={`rounded-md px-3 py-2 text-sm ${m.wash} ${f.severity === "critical" ? "border-l-4 border-current " + m.text : ""}`}>
                  <span className="text-ink">{f.text}</span>
                  {f.source_ids.length > 0 && (
                    <span className="ml-2 whitespace-nowrap">
                      {f.source_ids.map((sid) => (
                        <button key={sid} onClick={() => onSelectSource(sid)} className="mr-1 text-xs font-bold text-accent underline-offset-2 hover:underline">
                          source {sid}
                        </button>
                      ))}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
