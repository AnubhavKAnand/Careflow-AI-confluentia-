// Past cases already decided by clinicians that look like this one. No names; links open the case.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type SimilarCase } from "../api/client";
import { PriorityBadge } from "./ui";

export function SimilarCases({ caseId, refreshKey }: { caseId: number; refreshKey: unknown }) {
  const [data, setData] = useState<{ summary: string | null; cases: SimilarCase[] } | null>(null);
  useEffect(() => {
    api.similar(caseId).then(setData).catch(() => setData({ summary: null, cases: [] }));
  }, [caseId, refreshKey]);
  if (!data) return null;
  if (!data.cases.length) return <p className="text-sm text-ink-soft">No similar cases have been finalized yet.</p>;
  return (
    <div className="space-y-2">
      {data.summary && <p className="text-sm font-bold">{data.summary}</p>}
      <ul className="divide-y divide-rule rounded-md border border-rule">
        {data.cases.map((c) => (
          <li key={c.case_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
            <PriorityBadge p={c.final_priority} size="sm" showLabel={false} />
            <Link to={`/cases/${c.case_id}`} className="font-bold hover:text-accent">
              Case {c.case_id}
            </Link>
            <span className="text-ink-soft">{[c.chief_complaint, c.age_band].filter(Boolean).join(", ")}</span>
            {c.changed_by_clinician && <span className="text-xs text-ink-soft">(rules said {c.rules_priority})</span>}
            <span className="ml-auto text-xs text-ink-faint">{Math.round(c.similarity * 100)}% alike</span>
            <span className="w-full text-xs text-ink-soft">In common: {c.shared.join(", ")}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
