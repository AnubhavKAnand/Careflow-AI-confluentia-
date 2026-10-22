import type { ReactNode } from "react";
import { LoaderCircle } from "lucide-react";
import type { Priority } from "../api/client";

export const PRIORITY: Record<Priority, { label: string; text: string; bg: string; wash: string; border: string }> = {
  P1: { label: "Immediate", text: "text-p1", bg: "bg-p1", wash: "bg-p1-wash", border: "border-p1" },
  P2: { label: "Very urgent", text: "text-p2", bg: "bg-p2", wash: "bg-p2-wash", border: "border-p2" },
  P3: { label: "Urgent", text: "text-p3", bg: "bg-p3", wash: "bg-p3-wash", border: "border-p3" },
  P4: { label: "Routine", text: "text-p4", bg: "bg-p4", wash: "bg-p4-wash", border: "border-p4" },
};

export function PriorityBadge({ p, size = "md", showLabel = true }: { p: Priority | null; size?: "sm" | "md" | "lg"; showLabel?: boolean }) {
  if (!p) return <span className="text-ink-faint">pending</span>;
  const m = PRIORITY[p];
  const pad = size === "lg" ? "px-3 py-1.5 text-lg" : size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-0.5 text-sm";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md font-bold text-white ${m.bg} ${pad}`}>
      {p}
      {showLabel && <span className="font-normal opacity-95">{m.label}</span>}
    </span>
  );
}

/** Confidence as a small filled meter + number, coloured only when it is low. */
export function Confidence({ value, label }: { value: number | null | undefined; label?: string }) {
  if (value === null || value === undefined) return null;
  const pct = Math.round(value * 100);
  const low = value < 0.6;
  const mid = value < 0.8;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${low ? "text-p1" : mid ? "text-unclear" : "text-ink-faint"}`}
      title={`${label ?? "Confidence"}: ${pct}%`}
    >
      <span className="relative inline-block h-1.5 w-8 overflow-hidden rounded-full bg-rule">
        <span className={`absolute inset-y-0 left-0 ${low ? "bg-p1" : mid ? "bg-unclear" : "bg-accent"}`} style={{ width: `${pct}%` }} />
      </span>
      {pct}%
    </span>
  );
}

export function Panel({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-rule bg-panel ${className}`}>
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-2.5">
          <h2 className="text-base font-bold text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

type BtnVariant = "primary" | "secondary" | "danger" | "ghost";
export function Button({
  children,
  variant = "secondary",
  className = "",
  busy = false,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; busy?: boolean }) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent text-white hover:bg-accent-strong border-accent",
    secondary: "bg-panel text-ink border-rule hover:border-ink-faint",
    danger: "bg-p1 text-white border-p1 hover:brightness-95",
    ghost: "bg-transparent text-accent border-transparent hover:bg-accent-wash",
  };
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
    >
      {busy && <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-ink-soft" role="status">
      <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="rounded-md border border-p1/30 bg-p1-wash px-3 py-2 text-sm text-p1">{children}</div>;
}

export function minutes(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ${m % 60} min`;
  return `${Math.floor(h / 24)} days`;
}

export const SOURCE_KIND: Record<string, string> = {
  patient_message: "Patient message",
  intake_form: "Intake vitals",
  report: "Report",
  voice: "Voice note",
  followup_answer: "Follow-up answers",
};
