// Structured summary of the patient: complaint, symptoms (reported / denied), timeline, vitals, labs, history.
import type { Evidence, Extraction, Source, Triage } from "../api/client";
import { EvidenceChip } from "./EvidenceChip";
import { Confidence } from "./ui";

const VITALS: { key: string; label: string; unit: string }[] = [
  { key: "spo2", label: "SpO2", unit: "%" },
  { key: "pulse", label: "Pulse", unit: "/min" },
  { key: "resp_rate", label: "Breathing", unit: "/min" },
  { key: "systolic_bp", label: "BP", unit: "mmHg" },
  { key: "temperature_c", label: "Temp", unit: "°C" },
  { key: "consciousness", label: "ACVPU", unit: "" },
];

type Sel = { onSelect: (ev: Evidence) => void; sources: Source[]; active: Evidence | null };

function same(a: Evidence | null | undefined, b: Evidence | null) {
  return !!a && !!b && a.source_id === b.source_id && a.start === b.start && a.end === b.end;
}

export function Summary({ ex, triage, sel }: { ex: Extraction; triage: Triage; sel: Sel }) {
  const reported = ex.symptoms.filter((s) => !s.negated);
  const denied = ex.symptoms.filter((s) => s.negated);
  const chip = (ev: Evidence | null | undefined) => <EvidenceChip ev={ev} sources={sel.sources} onSelect={sel.onSelect} active={same(ev, sel.active)} />;
  const v = ex.vitals;
  const bp = v.systolic_bp?.value != null ? `${v.systolic_bp.value}/${v.diastolic_bp?.value ?? "?"}` : null;

  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-sm text-ink-soft">Main complaint</h3>
        <p className="flex flex-wrap items-center gap-2 text-lg font-bold">
          {ex.chief_complaint.value ?? <span className="font-normal text-ink-faint">Not clearly stated</span>}
          {chip(ex.chief_complaint.evidence)}
        </p>
        <p className="text-sm text-ink-soft">
          {ex.age_years.value ?? "age ?"} years, {ex.sex.value ?? "sex not stated"}
          {ex.pregnancy_status.value === "pregnant" && <span className="ml-2 font-bold text-p2">Pregnant</span>}
        </p>
      </div>

      <div>
        <h3 className="mb-1.5 text-sm text-ink-soft">Symptoms reported</h3>
        {reported.length === 0 ? (
          <p className="text-sm text-ink-faint">None extracted</p>
        ) : (
          <ul className="divide-y divide-rule rounded-md border border-rule">
            {reported.map((s, i) => (
              <li key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                <span className="font-bold">{s.name}</span>
                <span className="text-ink-soft">{[s.severity, s.progression, s.duration, s.onset && `onset ${s.onset}`, s.body_site].filter(Boolean).join(", ")}</span>
                <span className="ml-auto flex items-center gap-2">
                  <Confidence value={s.confidence} />
                  {chip(s.evidence)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {denied.length > 0 && (
          <p className="mt-2 text-sm text-ink-soft">
            <span className="font-bold">Denied:</span>{" "}
            {denied.map((s, i) => (
              <span key={i} className="mr-2 inline-flex items-center gap-1">
                {s.name} {chip(s.evidence)}
              </span>
            ))}
          </p>
        )}
      </div>

      {ex.timeline.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-sm text-ink-soft">How it started and changed</h3>
          <ol className="relative ml-2 space-y-2 border-l-2 border-rule pl-4">
            {ex.timeline.map((t, i) => (
              <li key={i} className="text-sm">
                <span className="absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full border-2 border-panel bg-accent" aria-hidden />
                <span className="font-bold">{t.when}</span> <span className="text-ink-soft">{t.event}</span> {chip(t.evidence)}
              </li>
            ))}
          </ol>
        </div>
      )}

      <div>
        <h3 className="mb-1.5 text-sm text-ink-soft">
          Vital signs
          {triage.news2 && (
            <span className="ml-2 font-bold text-ink">
              NEWS2 {triage.news2.total} ({triage.news2.band}
              {triage.news2.partial ? `, ${triage.news2.params_present} of 7 measured` : ""})
            </span>
          )}
        </h3>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {VITALS.map(({ key, label, unit }) => {
            const val = key === "systolic_bp" ? bp : v[key]?.value;
            const present = val !== null && val !== undefined;
            return (
              <div key={key} className={`rounded-md border px-2 py-1.5 ${present ? "border-rule" : "border-dashed border-rule"}`}>
                <div className="text-xs text-ink-soft">{label}</div>
                {present ? (
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-bold">
                      {String(val)}
                      <span className="text-xs font-normal text-ink-soft"> {unit}</span>
                    </span>
                    {chip(v[key]?.evidence)}
                  </div>
                ) : (
                  <div className="text-sm text-ink-faint">not measured</div>
                )}
              </div>
            );
          })}
        </div>
        {triage.news2?.note && <p className="mt-1 text-xs text-ink-soft">{triage.news2.note}</p>}
      </div>

      {ex.labs.length > 0 && (
        <div>
          <h3 className="mb-1.5 text-sm text-ink-soft">Lab results</h3>
          <table className="w-full text-sm">
            <tbody className="divide-y divide-rule">
              {ex.labs.map((l, i) => (
                <tr key={i}>
                  <td className="py-1.5 pr-2">{l.name}</td>
                  <td className="py-1.5 pr-2 font-bold">
                    {typeof l.value === "number" ? l.value.toLocaleString("en-IN") : l.value} <span className="font-normal text-ink-soft">{l.unit}</span>
                  </td>
                  <td className="py-1.5 pr-2 text-xs text-ink-soft">{l.reference_range}</td>
                  <td className="py-1.5 text-right">
                    <span className="inline-flex items-center gap-2">
                      <Confidence value={l.confidence} />
                      {chip(l.evidence)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(ex.medical_history.length > 0 || ex.medications.length > 0 || ex.allergies.length > 0) && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          {[
            ["History", ex.medical_history],
            ["Medicines", ex.medications],
            ["Allergies", ex.allergies],
          ].map(([label, items]) =>
            (items as Extraction["medications"]).length ? (
              <div key={label as string} className="contents">
                <dt className="text-ink-soft">{label as string}</dt>
                <dd>
                  {(items as Extraction["medications"]).map((m, i) => (
                    <span key={i} className="mr-2 inline-flex items-center gap-1">
                      {String(m.value)} {chip(m.evidence)}
                    </span>
                  ))}
                </dd>
              </div>
            ) : null,
          )}
        </dl>
      )}
    </div>
  );
}
