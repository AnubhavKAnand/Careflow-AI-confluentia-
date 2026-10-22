// A small "where did this come from" link. Clicking it opens the source in the viewer and highlights the span.
import { AudioLines, FileImage, FileText, Keyboard, Languages, Link2Off } from "lucide-react";
import type { Evidence, Source } from "../api/client";

const ICON: Record<string, typeof FileText> = {
  report: FileImage,
  voice: AudioLines,
  patient_message: Keyboard,
  intake_form: FileText,
  followup_answer: Keyboard,
};

export function fmtTime(s: number): string {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function EvidenceChip({
  ev,
  sources,
  onSelect,
  active,
}: {
  ev: Evidence | null | undefined;
  sources: Source[];
  onSelect: (ev: Evidence) => void;
  active?: boolean;
}) {
  if (!ev) return null;
  if (ev.origin === "form" && ev.source_id === null) return <span className="text-xs text-ink-faint">registration</span>;
  if (ev.grounded === false) {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-p1" title="This could not be found in the source text">
        <Link2Off className="h-3.5 w-3.5" aria-hidden /> not found in source
      </span>
    );
  }
  if (ev.source_id === null) return null;
  const src = sources.find((s) => s.id === ev.source_id);
  const Icon = ICON[src?.kind ?? ""] ?? FileText;
  const where =
    ev.locator?.start_s !== undefined ? ` at ${fmtTime(ev.locator.start_s)}` : ev.locator?.page ? ` p.${ev.locator.page}` : "";
  return (
    <button
      type="button"
      onClick={() => onSelect(ev)}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs font-bold transition-colors ${
        active ? "bg-accent text-white" : "bg-accent-wash text-accent hover:bg-accent hover:text-white"
      }`}
      title={ev.quote ? `“${ev.quote}”` : undefined}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {ev.source_id}
      {where}
      {ev.in_translation && <Languages className="h-3.5 w-3.5" aria-label="from translation" />}
    </button>
  );
}
