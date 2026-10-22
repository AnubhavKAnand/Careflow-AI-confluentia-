// Evaluation: how the system does on gold-labelled cases, led by the safety metric (urgent patients
// rated as less urgent), split into the development set and a held-out set that was never used for tuning.
import { useEffect, useMemo, useState } from "react";
import { api, type EvalResult, type EvaluationData, type Priority } from "../api/client";
import { ErrorNote, Panel, PRIORITY, PriorityBadge, Spinner } from "../components/ui";

const P: Priority[] = ["P1", "P2", "P3", "P4"];
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`);
const PROVIDER_LABEL: Record<string, string> = {
  rules: "Rules only (offline, no model)",
  ollama: "Local small model (Ollama)",
  gemini: "Gemini (cloud)",
  configured: "Configured chain",
  "ktas-rules": "Real ED data (KTAS): rules only",
  "ktas-ollama": "Real ED data (KTAS): local small model",
  "ktas-gemini": "Real ED data (KTAS): Gemini",
  "ktas-test-rules": "Real ED data, KTAS-test: rules only",
  "ktas-test-ollama": "Real ED data, KTAS-test: local small model",
};
const CATEGORY_LABEL: Record<string, string> = {
  urgent: "Urgent presentations",
  moderate: "Very urgent / urgent, not immediate",
  routine: "Routine",
  negation: "Denied symptoms",
  injection: "Instructions hidden in input",
  conflict: "Conflicting information",
  vague: "Vague or empty",
  regional: "Other Indian languages",
  "real-ed": "Real emergency-department visits (KTAS)",
  report: "Reports (images / PDF)",
};

export default function Evaluation() {
  const [data, setData] = useState<EvaluationData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  useEffect(() => {
    api
      .evaluation()
      .then((d) => {
        setData(d);
        // open on the synthetic-set results first; KTAS rows are further down the table
        const pref = ["ollama", "gemini", "rules", "ktas-test-ollama"];
        setSel(pref.map((n) => d.results.find((r) => r.name === n)).find(Boolean)?.name ?? d.results[0]?.name ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);
  const r: EvalResult | undefined = useMemo(() => data?.results.find((x) => x.name === sel), [data, sel]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <Spinner label="Loading evaluation" />;
  const m = r?.metrics;
  const holdout = m?.by_split?.holdout;
  const dev = m?.by_split?.dev;
  const nurse = m?.nurse_baseline;

  return (
    <div className="space-y-5">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold">Evaluation</h1>
        <p className="text-sm text-ink-soft">
          {data.dataset.n} gold-labelled cases ({data.dataset.by_split.dev ?? 0} development, {data.dataset.by_split.holdout ?? 0} held-out) in English, Hinglish, Hindi and other
          Indian languages, including reports, conflicting and tampered inputs. Expected priorities were set from case content using the triage guidance the rules are
          adapted from, not from system output.
        </p>
      </div>

      {data.results.length === 0 ? (
        <p className="rounded-lg border border-dashed border-rule bg-panel p-8 text-center text-ink-soft">
          No results yet. Run <code>python -m scripts.run_eval</code> in <code>backend/</code>.
        </p>
      ) : (
        <>
          <Panel title="Compare extraction setups">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="text-xs text-ink-soft">
                  <tr>
                    <th className="py-1.5 text-left font-normal">Setup</th>
                    <th className="py-1.5 text-right font-normal">Urgent rated less urgent</th>
                    <th className="py-1.5 text-right font-normal">Held-out: urgent rated less urgent</th>
                    <th className="py-1.5 text-right font-normal">Exact priority</th>
                    <th className="py-1.5 text-right font-normal">Within one level</th>
                    <th className="py-1.5 text-right font-normal">Weighted kappa</th>
                    <th className="py-1.5 text-right font-normal">Time per case (mean)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {[...data.results].sort((a, b) => Number(a.name.startsWith("ktas")) - Number(b.name.startsWith("ktas"))).map((x) => (
                    <tr key={x.name} className={x.name === sel ? "bg-accent-wash" : ""}>
                      <td className="py-2">
                        <button onClick={() => setSel(x.name)} className="text-left font-bold hover:text-accent">
                          {PROVIDER_LABEL[x.name] ?? x.name}
                        </button>
                        <div className="text-xs text-ink-faint">{x.models.join(", ")}</div>
                      </td>
                      <td className="py-2 text-right font-bold">{pct(x.metrics.under_triage_urgent)}</td>
                      <td className="py-2 text-right">{pct(x.metrics.by_split?.holdout?.under_triage_urgent)}</td>
                      <td className="py-2 text-right">{pct(x.metrics.accuracy)}</td>
                      <td className="py-2 text-right">{pct(x.metrics.within_one)}</td>
                      <td className="py-2 text-right">{x.metrics.weighted_kappa ?? "n/a"}</td>
                      <td className="py-2 text-right">{x.metrics.latency_ms.mean ?? "n/a"} ms</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.results.some((x) => x.name === "ollama") && (
              <p className="mt-3 rounded-md bg-unclear-wash px-3 py-2 text-sm">
                Only the offline rules baseline has been run here. Run <code>python -m scripts.run_eval --provider ollama</code> (and <code>--provider gemini</code>) to add the small
                model and cloud rows; they appear in this table automatically.
              </p>
            )}
          </Panel>

          {m && r && (
            <>
              <div className="grid gap-4 lg:grid-cols-3">
                <Panel title="Safety" className="lg:col-span-1">
                  <p className="text-sm text-ink-soft">Urgent patients (P1/P2) suggested as less urgent</p>
                  <p className={`text-4xl font-bold ${(m.under_triage_urgent ?? 0) > 0.05 ? "text-p1" : "text-p4"}`}>{pct(m.under_triage_urgent)}</p>
                  <p className="text-sm text-ink-soft">
                    {Math.round((m.under_triage_urgent ?? 0) * m.urgent_cases)} of {m.urgent_cases} urgent cases; {m.severe_under_triage} were two or more levels too low.
                  </p>
                  <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
                    <dt className="text-ink-soft">Over-triage (more urgent than needed)</dt>
                    <dd className="font-bold">{pct(m.over_triage)}</dd>
                    <dt className="text-ink-soft">Expected warning signs detected</dt>
                    <dd className="font-bold">{pct(m.red_flag_recall)}</dd>
                    <dt className="text-ink-soft">Routine cases raised to P1/P2</dt>
                    <dd className="font-bold">
                      {m.false_alarms_on_routine} of {m.routine_cases}
                    </dd>
                  </dl>
                </Panel>

                <Panel title={nurse ? "By set" : "Development versus held-out"} className="lg:col-span-2">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-ink-soft">
                      <tr>
                        <th className="py-1 text-left font-normal">Set</th>
                        <th className="py-1 text-right font-normal">Cases</th>
                        <th className="py-1 text-right font-normal">Exact</th>
                        <th className="py-1 text-right font-normal">Within one</th>
                        <th className="py-1 text-right font-normal">Urgent rated less urgent</th>
                        <th className="py-1 text-right font-normal">Kappa</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {[
                        ["Development (used while building)", dev],
                        ["Held-out (never used for tuning)", holdout],
                        ["Real ED visits (KTAS-dev, used for fixes)", m?.by_split?.["ktas-real"] ?? m?.by_split?.["ktas-dev"]],
                        ["Real ED visits (KTAS-test, never looked at)", m?.by_split?.["ktas-test"]],
                      ].map(([label, v]) =>
                        v ? (
                          <tr key={label as string}>
                            <td className="py-1.5">{label as string}</td>
                            <td className="py-1.5 text-right">{(v as NonNullable<typeof dev>).n}</td>
                            <td className="py-1.5 text-right">{pct((v as NonNullable<typeof dev>).accuracy)}</td>
                            <td className="py-1.5 text-right">{pct((v as NonNullable<typeof dev>).within_one)}</td>
                            <td className="py-1.5 text-right font-bold">{pct((v as NonNullable<typeof dev>).under_triage_urgent)}</td>
                            <td className="py-1.5 text-right">{(v as NonNullable<typeof dev>).weighted_kappa ?? "n/a"}</td>
                          </tr>
                        ) : null,
                      )}
                    </tbody>
                  </table>
                  {r.name === "rules" && holdout && dev && (holdout.accuracy ?? 0) < (dev.accuracy ?? 0) - 0.2 && (
                    <p className="mt-3 text-sm text-ink-soft">
                      The keyword safety net works on phrasings it knows and misses new ones (for example "tight pressure in the chest, clammy"). That gap is why the language model
                      is the primary extractor and the lexicon is only the backstop. Compare the held-out column once the small model has been run.
                    </p>
                  )}
                </Panel>
              </div>

              {nurse && (
                <Panel title="Real data: CareFlow versus the triage nurse">
                  <p className="mb-2 max-w-3xl text-sm text-ink-soft">
                    Real adult emergency-department visits from the public KTAS dataset (Moon et al., Korea). The expected priority is the expert panel's KTAS level
                    (levels 4 and 5 merged into P4). The nurse row is the triage nurse's own decision on the same patients, scored the same way. Diagnosis and outcome
                    columns are never shown to the system.
                  </p>
                  <table className="w-full text-sm">
                    <thead className="text-xs text-ink-soft">
                      <tr>
                        <th className="py-1 text-left font-normal">Who</th>
                        <th className="py-1 text-right font-normal">Cases</th>
                        <th className="py-1 text-right font-normal">Urgent rated less urgent</th>
                        <th className="py-1 text-right font-normal">Two+ levels too low</th>
                        <th className="py-1 text-right font-normal">Over-triage</th>
                        <th className="py-1 text-right font-normal">Exact</th>
                        <th className="py-1 text-right font-normal">Kappa</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {[
                        ["CareFlow (" + (PROVIDER_LABEL[r.name] ?? r.name) + ")", m],
                        ["Triage nurse (KTAS_RN)", nurse],
                      ].map(([label, v]) => {
                        const x = v as NonNullable<typeof nurse>;
                        return (
                          <tr key={label as string}>
                            <td className="py-1.5">{label as string}</td>
                            <td className="py-1.5 text-right">{x.n}</td>
                            <td className="py-1.5 text-right font-bold">{pct(x.under_triage_urgent)}</td>
                            <td className="py-1.5 text-right">{x.severe_under_triage}</td>
                            <td className="py-1.5 text-right">{pct(x.over_triage)}</td>
                            <td className="py-1.5 text-right">{pct(x.accuracy)}</td>
                            <td className="py-1.5 text-right">{x.weighted_kappa ?? "n/a"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="mt-2 text-xs text-ink-faint">
                    CareFlow is built to over-triage rather than under-triage, so expect a higher over-triage rate than the nurse; the clinician makes the final call either way.
                  </p>
                </Panel>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <Panel title="By kind of case">
                  <ul className="space-y-2">
                    {Object.entries(m.by_category).map(([k, v]) => (
                      <li key={k} className="text-sm">
                        <div className="flex justify-between">
                          <span>{CATEGORY_LABEL[k] ?? k}</span>
                          <span className="text-ink-soft">
                            {pct(v.accuracy)} of {v.n}
                            {v.under_triage > 0 && <span className="ml-2 font-bold text-p1">{v.under_triage} under</span>}
                          </span>
                        </div>
                        <div className="mt-1 h-2 rounded-full bg-rule" aria-hidden>
                          <div className="h-2 rounded-full bg-accent" style={{ width: `${Math.round((v.accuracy ?? 0) * 100)}%` }} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </Panel>

                <Panel title="Suggested versus expected priority">
                  <table className="w-full text-center text-sm">
                    <caption className="mb-2 text-left text-xs text-ink-soft">Rows: expected. Columns: suggested. Left of the diagonal is under-triage.</caption>
                    <thead>
                      <tr>
                        <th />
                        {P.map((p) => (
                          <th key={p} className={`py-1 font-bold ${PRIORITY[p].text}`}>
                            {p}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {P.map((g) => (
                        <tr key={g}>
                          <th className={`py-1 font-bold ${PRIORITY[g].text}`}>{g}</th>
                          {P.map((p) => {
                            const v = m.confusion[g]?.[p] ?? 0;
                            const under = P.indexOf(p) > P.indexOf(g);
                            return (
                              <td key={p} className={`py-1.5 ${g === p ? "bg-accent-wash font-bold" : under && v ? "bg-p1-wash font-bold text-p1" : ""}`}>
                                {v}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <h3 className="mt-4 text-sm font-bold">Flags</h3>
                  <table className="mt-1 w-full text-sm">
                    <thead className="text-xs text-ink-soft">
                      <tr>
                        <th className="py-1 text-left font-normal">Flag</th>
                        <th className="py-1 text-right font-normal">Found when expected</th>
                        <th className="py-1 text-right font-normal">Correct when raised</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {Object.entries(m.flag_types).map(([k, v]) => (
                        <tr key={k}>
                          <td className="py-1 capitalize">{k}</td>
                          <td className="py-1 text-right">
                            {pct(v.recall)} <span className="text-xs text-ink-faint">({v.tp}/{v.tp + v.fn})</span>
                          </td>
                          <td className="py-1 text-right">
                            {pct(v.precision)} <span className="text-xs text-ink-faint">({v.tp}/{v.tp + v.fp})</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Panel>
              </div>

              <Panel title={`Cases it got wrong (${m.misses.length}${m.misses.length > 60 ? ", first 60 shown, under-triage first" : ""})`}>
                {m.misses.length === 0 ? (
                  <p className="text-sm text-ink-soft">Every case matched its expected priority.</p>
                ) : (
                  <ul className="divide-y divide-rule">
                    {m.misses.slice(0, 60).map((x) => (
                      <li key={x.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2 text-sm">
                        <span className={`w-14 shrink-0 text-xs font-bold ${x.direction === "under" ? "text-p1" : "text-ink-soft"}`}>
                          {x.direction === "under" ? "Too low" : "Too high"}
                        </span>
                        <span className="w-20 shrink-0 font-bold">{x.id}</span>
                        <span className="flex items-center gap-1">
                          <PriorityBadge p={x.expected} size="sm" showLabel={false} /> expected, got <PriorityBadge p={x.got} size="sm" showLabel={false} />
                        </span>
                        <span className="text-ink-soft">
                          {CATEGORY_LABEL[x.category] ?? x.category}, {x.language}
                        </span>
                        {x.note && <span className="w-full pl-[8.5rem] text-xs text-ink-soft">{x.note}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <p className="text-xs text-ink-faint">
                {PROVIDER_LABEL[r.name] ?? r.name}: engine {r.engine_version}, dataset {r.dataset_version}, run {new Date(r.run_at).toLocaleString("en-IN")} on {r.machine.platform},{" "}
                {r.machine.cpus} CPUs.
              </p>
            </>
          )}
        </>
      )}
    </div>
  );
}
