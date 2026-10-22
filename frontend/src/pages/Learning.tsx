// Shadow learning: how the learned agent is doing against real clinician decisions, whether it may
// graduate to recommendation mode, and a 6-month simulation that shows the learning curve.
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Circle, EyeOff, Lightbulb } from "lucide-react";
import { api, type LearningStatus, type Priority, type SimulationResult } from "../api/client";
import { LineChart } from "../components/LineChart";
import { Button, ErrorNote, Panel, PRIORITY, Spinner } from "../components/ui";
import { useAuth } from "../context/AuthContext";

const AGENT = "#00897d";
const RULES = "#6a5fd6";
const P: Priority[] = ["P1", "P2", "P3", "P4"];
const PATTERN_LABEL: Record<string, string> = {
  elderly_fever: "Fever in patients aged 65+",
  diabetic_gi: "Diabetes with vomiting or stomach pain",
  pregnant_headache: "Headache in pregnancy",
  child_fever_vomit: "Child under 5 with fever and vomiting",
  young_chest_pain: "Young adult, isolated chest pain, normal vitals",
};
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "not enough data" : `${Math.round(v * 100)}%`);

export default function Learning() {
  const { can } = useAuth();
  const [st, setSt] = useState<LearningStatus | null>(null);
  const [sim, setSim] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [cfg, setCfg] = useState({ weeks: 26, per_week: 20, seed: 7 });

  const load = useCallback(() => {
    api.learningStatus().then(setSt).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  if (!st) return error ? <ErrorNote>{error}</ErrorNote> : <Spinner label="Loading learning status" />;
  const m = st.metrics;
  const shadow = st.mode === "shadow";

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-bold">Shadow learning</h1>
          <p className="text-sm text-ink-soft">
            The learned agent studies clinicians' final decisions. In shadow mode it records its own guess for every case before the clinician decides, and nobody sees it.
            Only after it meets the criteria below, and a clinical lead switches it on, are its suggestions shown. Even then it can raise a priority but never lower one.
          </p>
        </div>
        <span className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-bold ${shadow ? "bg-ink text-white" : "bg-accent text-white"}`}>
          {shadow ? <EyeOff className="h-4 w-4" aria-hidden /> : <Lightbulb className="h-4 w-4" aria-hidden />}
          {shadow ? "Shadow mode: suggestions hidden" : "Recommendation mode: suggestions shown"}
        </span>
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Ready to show suggestions?">
          <ul className="space-y-2.5">
            {st.graduation.checks.map((c) => (
              <li key={c.id} className="flex items-start gap-2 text-sm">
                {c.met ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-p4" aria-label="met" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" aria-label="not met" />}
                <span className="flex-1">
                  {c.label}
                  <span className="block text-xs text-ink-soft">
                    Now: {c.id === "reviews" ? c.value : pct(c.value)}
                    {c.id === "under_triage" && m.rules_under_triage_last100 !== null && `; rules alone: ${pct(m.rules_under_triage_last100)}`}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-ink-soft">{st.graduation.note}</p>
          {can("learning:manage") ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {shadow ? (
                <>
                  <Button variant="primary" disabled={!st.graduation.ready} busy={busy === "on"} onClick={() => act("on", () => api.setLearningMode("recommend"))}>
                    Sign off and show suggestions
                  </Button>
                  {!st.graduation.ready && (
                    <Button variant="ghost" busy={busy === "force"} onClick={() => act("force", () => api.setLearningMode("recommend", true))} title="Recorded in the audit log as a forced switch">
                      Demo: switch on anyway
                    </Button>
                  )}
                </>
              ) : (
                <Button busy={busy === "off"} onClick={() => act("off", () => api.setLearningMode("shadow"))}>
                  Return to shadow mode
                </Button>
              )}
            </div>
          ) : (
            <p className="mt-3 text-xs text-ink-faint">Only a doctor (clinical lead) can change the mode.</p>
          )}
        </Panel>

        <Panel title="How it learns">
          <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-ink-soft">Clinician-reviewed cases</dt>
            <dd className="font-bold">{m.reviews}</dd>
            {m.synthetic_examples > 0 && (
              <>
                <dt className="text-ink-soft">Synthetic warm-up examples (never count toward sign-off)</dt>
                <dd className="font-bold">{m.synthetic_examples}</dd>
              </>
            )}
            <dt className="text-ink-soft">Agent agrees with clinicians (last 100)</dt>
            <dd className="font-bold">{pct(m.agreement_last100)}</dd>
            <dt className="text-ink-soft">Rules alone agree with clinicians (last 100)</dt>
            <dd className="font-bold">{pct(m.rules_agreement_last100)}</dd>
            <dt className="text-ink-soft">Clinicians changed the rules' priority</dt>
            <dd className="font-bold">{pct(m.clinician_changed_rules)}</dd>
          </dl>
          <h3 className="mt-4 text-sm font-bold">Scoring each decision</h3>
          <table className="mt-1 w-full text-sm">
            <tbody className="divide-y divide-rule">
              <tr>
                <td className="py-1">Same priority as the clinician</td>
                <td className="py-1 text-right font-bold">+{st.reward.agree}</td>
              </tr>
              <tr>
                <td className="py-1">More urgent than the clinician (per level)</td>
                <td className="py-1 text-right font-bold">{st.reward.over_triage_per_level}</td>
              </tr>
              <tr>
                <td className="py-1">Less urgent than the clinician (per level)</td>
                <td className="py-1 text-right font-bold text-p1">{st.reward.under_triage_per_level}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-2 text-xs text-ink-soft">
            Missing an urgent patient costs five times more than being over-cautious, so when unsure the agent leans towards the more urgent priority. It abstains when it has seen
            fewer than {st.model.min_training} cases or the case is unlike anything seen before. Erasing a patient's data removes their decisions from the model too: it is
            recomputed from the decisions that remain.
          </p>
        </Panel>
      </div>

      {(m.reviews > 0 || st.model.trained_on > 0) && (
        <div className="grid gap-4 lg:grid-cols-2">
          {m.curve.length >= 2 && (
            <Panel title="Live learning curve">
              <LineChart
                title="Agreement with clinicians, per 20 reviewed cases"
                xTitle="Reviewed cases"
                xLabels={m.curve.map((c) => String(c.upto))}
                series={[
                  { name: "Agent", color: AGENT, values: m.curve.map((c) => c.agent_agreement) },
                  { name: "Rules alone", color: RULES, dashed: true, values: m.curve.map((c) => c.rules_agreement) },
                ]}
              />
            </Panel>
          )}
          <Panel title="Agent suggestion versus clinician decision">
            <table className="w-full text-center text-sm">
              <caption className="mb-2 text-left text-xs text-ink-soft">Rows: what the agent said. Columns: what the clinician decided. The diagonal is agreement; right of it is under-triage.</caption>
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
                {P.map((a) => (
                  <tr key={a}>
                    <th className={`py-1 font-bold ${PRIORITY[a].text}`}>{a}</th>
                    {P.map((f) => {
                      const v = m.confusion[a]?.[f] ?? 0;
                      const under = P.indexOf(a) > P.indexOf(f);
                      return (
                        <td key={f} className={`py-1.5 ${a === f ? "bg-accent-wash font-bold" : under && v ? "bg-p1-wash text-p1" : ""}`}>
                          {v}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {st.top_features.P2 && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                {(["P1", "P2"] as Priority[]).map((p) => (
                  <div key={p}>
                    <h3 className="text-sm font-bold">Pushes towards {p}</h3>
                    <ul className="text-sm text-ink-soft">
                      {(st.top_features[p] ?? []).slice(0, 5).map((f) => (
                        <li key={f.feature}>{f.label}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
            {!shadow && (
              <p className="mt-3 text-xs text-ink-soft">
                Automation-bias check: agreement when the suggestion was visible {pct(m.automation_bias.agreement_when_visible)} ({m.automation_bias.visible_n} cases) versus on
                blind checks where it was hidden {pct(m.automation_bias.agreement_on_blind_checks)} ({m.automation_bias.blind_n}). A big gap means clinicians may be copying the AI.
              </p>
            )}
          </Panel>
        </div>
      )}

      <Panel
        title="Six months in shadow mode, simulated"
        action={
          can("learning:manage") && st.model.trained_on < st.model.min_training ? (
            <Button variant="ghost" busy={busy === "boot"} onClick={() => act("boot", () => api.bootstrap(300))}>
              Warm up live agent with 300 synthetic cases
            </Button>
          ) : undefined
        }
      >
        <p className="max-w-3xl text-sm text-ink-soft">
          Synthetic cases run through the real triage engine and are decided by a simulated clinician who mostly agrees with the rules but also applies local judgement the
          rules do not encode (for example, reviewing elderly patients with fever sooner), with some disagreement between clinicians. Nothing is stored.
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3 text-sm">
          {(
            [
              ["weeks", "Weeks", 4, 104],
              ["per_week", "Cases reviewed per week", 5, 100],
              ["seed", "Random seed", 1, 9999],
            ] as const
          ).map(([k, lab, min, max]) => (
            <label key={k}>
              <span className="block text-xs text-ink-soft">{lab}</span>
              <input
                type="number"
                min={min}
                max={max}
                value={cfg[k]}
                onChange={(e) => setCfg({ ...cfg, [k]: Number(e.target.value) })}
                className="w-28 rounded border border-rule px-2 py-1"
              />
            </label>
          ))}
          <Button
            variant="primary"
            busy={busy === "sim"}
            onClick={async () => {
              setBusy("sim");
              try {
                setSim(await api.simulate(cfg.weeks, cfg.per_week, cfg.seed));
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(null);
              }
            }}
          >
            Run simulation
          </Button>
        </div>

        {sim && (
          <div className="mt-5 space-y-5">
            <p className="text-sm">
              Over the last 100 cases the agent agreed with clinicians on <span className="font-bold">{pct(sim.final.agent_agreement_last100)}</span>, the rules alone on{" "}
              <span className="font-bold">{pct(sim.final.rules_agreement_last100)}</span>. It rated urgent patients as less urgent on{" "}
              <span className="font-bold">{pct(sim.final.agent_under_triage_last100)}</span> of them, against {pct(sim.final.rules_under_triage_last100)} for the rules alone.
            </p>
            <div className="grid gap-5 lg:grid-cols-2">
              <LineChart
                title="Agreement with the clinician's final priority"
                xTitle="Week"
                xLabels={sim.curve.map((c) => String(c.week))}
                series={[
                  { name: "Agent", color: AGENT, values: sim.curve.map((c) => c.agent_agreement) },
                  { name: "Rules alone", color: RULES, dashed: true, values: sim.curve.map((c) => c.rules_agreement) },
                ]}
              />
              <LineChart
                title="Urgent (P1/P2) patients rated as less urgent"
                xTitle="Week"
                xLabels={sim.curve.map((c) => String(c.week))}
                threshold={{ value: 0.1, label: "Sign-off limit (10%)" }}
                series={[
                  { name: "Agent", color: AGENT, values: sim.curve.map((c) => c.agent_under_triage) },
                  { name: "Rules alone", color: RULES, dashed: true, values: sim.curve.map((c) => c.rules_under_triage) },
                ]}
              />
            </div>
            <p className="text-xs text-ink-soft">In the first weeks the agent abstains (fewer than {st.model.min_training} cases seen), so its lines start later.</p>
            <div>
              <h3 className="mb-1 text-sm font-bold">Local judgement the rules miss (last 15 cases of each pattern)</h3>
              <table className="w-full text-sm">
                <thead className="text-xs text-ink-soft">
                  <tr>
                    <th className="py-1 text-left font-normal">Pattern</th>
                    <th className="py-1 text-left font-normal">Agent now says</th>
                    <th className="py-1 text-right font-normal">Agent matches clinician</th>
                    <th className="py-1 text-right font-normal">Rules match clinician</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {Object.entries(sim.patterns).map(([k, v]) => (
                    <tr key={k}>
                      <td className="py-1.5">{PATTERN_LABEL[k] ?? k}</td>
                      <td className={`py-1.5 font-bold ${v.agent_suggests ? PRIORITY[v.agent_suggests].text : ""}`}>{v.agent_suggests ?? "abstains"}</td>
                      <td className="py-1.5 text-right">{pct(v.agent)}</td>
                      <td className="py-1.5 text-right">{pct(v.rules)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-ink-soft">
                The last row is deliberate: clinicians call these P3 most of the time but P2 in about 30% of cases. Because missing an urgent case is penalised five times more, the
                agent does not learn to downgrade them.
              </p>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
