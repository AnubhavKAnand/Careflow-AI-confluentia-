// The queue's signature element: how much of the review-time target has been used.
// Fills toward the target; past the target it turns crimson and shows how far over it is.
import type { Priority } from "../api/client";
import { minutes } from "./ui";

export function TimeBar({ waiting, target, priority, done }: { waiting: number; target: number | null; priority: Priority | null; done?: boolean }) {
  if (done) return <span className="text-sm text-ink-faint">Reviewed</span>;
  if (target === null || priority === null) return <span className="text-sm text-ink-faint">{minutes(waiting)}</span>;
  // P1 has a 0-minute target: treat its window as 5 minutes so the bar is still meaningful
  const window = Math.max(target, 5);
  const ratio = waiting / window;
  const over = waiting > target;
  const pct = Math.min(100, Math.round(ratio * 100));
  const colour = over ? "bg-p1" : ratio > 0.75 ? "bg-p2" : "bg-accent";
  return (
    <div className="w-36" title={`Waiting ${minutes(waiting)}; target ${target === 0 ? "immediate" : minutes(target)}`}>
      <div className="flex items-baseline justify-between text-xs">
        <span className={over ? "font-bold text-p1" : "text-ink-soft"}>{minutes(waiting)}</span>
        <span className="text-ink-faint">{over ? `${minutes(waiting - target)} over` : target === 0 ? "now" : `of ${minutes(target)}`}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-rule" aria-hidden>
        <div className={`h-full ${colour}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
