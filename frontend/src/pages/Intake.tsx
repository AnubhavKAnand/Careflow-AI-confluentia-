// New case: consent first, then the patient's own words, optional vitals, reports and voice notes.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileUp, Trash2 } from "lucide-react";
import { api, type CaseDetail, type PatientIn, type VitalsIn } from "../api/client";
import { VoiceRecorder } from "../components/VoiceRecorder";
import { Button, ErrorNote, Panel } from "../components/ui";

const CONSENT_EN =
  "I agree that my health information (messages, reports and voice notes) can be processed by this system to help clinic staff decide who to see first. A doctor or nurse will review it. I can ask for my data to be withdrawn or deleted at any time.";
const CONSENT_HI =
  "मैं सहमत हूँ कि मेरी स्वास्थ्य जानकारी (संदेश, रिपोर्ट और आवाज़ संदेश) इस सिस्टम द्वारा प्रोसेस की जा सकती है ताकि क्लिनिक स्टाफ़ तय कर सके कि पहले किसे देखना है। डॉक्टर या नर्स इसकी समीक्षा करेंगे। मैं कभी भी अपना डेटा वापस लेने या हटाने के लिए कह सकता/सकती हूँ।";

const VITAL_FIELDS: { key: keyof VitalsIn; label: string; unit: string; step?: string }[] = [
  { key: "spo2", label: "SpO2", unit: "%" },
  { key: "pulse", label: "Pulse", unit: "/min" },
  { key: "resp_rate", label: "Breathing rate", unit: "/min" },
  { key: "temperature_c", label: "Temperature", unit: "°C", step: "0.1" },
  { key: "systolic_bp", label: "BP systolic", unit: "mmHg" },
  { key: "diastolic_bp", label: "BP diastolic", unit: "mmHg" },
];

export default function Intake() {
  const navigate = useNavigate();
  const [patient, setPatient] = useState<PatientIn>({ name: "", age_years: null, sex: null, preferred_language: "hi-en" });
  const [consent, setConsent] = useState(false);
  const [message, setMessage] = useState("");
  const [vitals, setVitals] = useState<Record<string, string>>({});
  const [consciousness, setConsciousness] = useState<string>("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<CaseDetail | null>(null);

  const canSubmit = consent && patient.name.trim() && (message.trim() || files.length);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    const v: VitalsIn = {};
    VITAL_FIELDS.forEach(({ key }) => {
      const raw = vitals[key];
      if (raw && !Number.isNaN(Number(raw))) (v as Record<string, number>)[key] = Number(raw);
    });
    if (consciousness) v.consciousness = consciousness as VitalsIn["consciousness"];
    try {
      const d = await api.intake(
        { patient: { ...patient, name: patient.name.trim() }, consent_given: consent, message: message.trim() || undefined, vitals: Object.keys(v).length ? v : undefined },
        files,
      );
      setCreated(d);
      setBusy(false);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  if (created?.receipt) {
    const r = created.receipt;
    return (
      <div className="mx-auto max-w-xl space-y-4">
        <h1 className="text-2xl font-bold">Case {r.case_id} submitted</h1>
        <p className="text-sm text-ink-soft">
          Suggested priority: <span className="font-bold text-ink">{created.triage?.priority}</span>. A clinician will review it. Give the patient this consent slip.
        </p>
        <section className="rounded-lg border-2 border-dashed border-ink-faint bg-panel p-5" aria-label="Consent slip">
          <h2 className="font-bold">Consent slip / सहमति पर्ची</h2>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-ink-soft">Case number</dt>
            <dd className="text-lg font-bold">{r.case_id}</dd>
            <dt className="text-ink-soft">Code</dt>
            <dd className="text-lg font-bold tracking-widest">{r.access_code}</dd>
            <dt className="text-ink-soft">Consent</dt>
            <dd>
              Version {r.consent_version}, {new Date(r.consent_at.endsWith("Z") || r.consent_at.includes("+") ? r.consent_at : r.consent_at + "Z").toLocaleString("en-IN")}
            </dd>
          </dl>
          <p className="mt-3 text-sm">To withdraw consent and have your data deleted, ask at the desk or visit the clinic's withdrawal page with this number and code.</p>
          <p className="text-sm text-ink-soft" lang="hi">
            सहमति वापस लेने और अपना डेटा हटवाने के लिए डेस्क पर पूछें या इस नंबर और कोड के साथ क्लिनिक का वापसी पेज खोलें।
          </p>
        </section>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => navigate(`/cases/${created.id}`)}>
            Open case
          </Button>
          <Button onClick={() => window.print()}>Print slip</Button>
          <Button variant="ghost" onClick={() => window.location.reload()}>
            New case
          </Button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold">New case</h1>
        <p className="text-sm text-ink-soft">Fill in what you have. Reports, voice notes and vitals are optional; missing details become follow-up questions.</p>
      </div>

      <Panel title="Consent">
        <label className="flex items-start gap-3">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-1 h-5 w-5 accent-[var(--color-accent)]" />
          <span className="space-y-2 text-sm">
            <span className="block">{CONSENT_EN}</span>
            <span className="block text-ink-soft" lang="hi">
              {CONSENT_HI}
            </span>
          </span>
        </label>
        {!consent && <p className="mt-2 text-xs text-ink-faint">Nothing is processed until the patient agrees.</p>}
      </Panel>

      <Panel title="Patient">
        <div className="grid gap-3 sm:grid-cols-4">
          <label className="sm:col-span-2">
            <span className="text-sm">Name</span>
            <input required value={patient.name} onChange={(e) => setPatient({ ...patient, name: e.target.value })} className="mt-1 w-full rounded border border-rule px-2 py-1.5" />
          </label>
          <label>
            <span className="text-sm">Age (years)</span>
            <input
              type="number"
              min={0}
              max={120}
              value={patient.age_years ?? ""}
              onChange={(e) => setPatient({ ...patient, age_years: e.target.value === "" ? null : Number(e.target.value) })}
              className="mt-1 w-full rounded border border-rule px-2 py-1.5"
            />
          </label>
          <label>
            <span className="text-sm">Sex</span>
            <select value={patient.sex ?? ""} onChange={(e) => setPatient({ ...patient, sex: (e.target.value || null) as PatientIn["sex"] })} className="mt-1 w-full rounded border border-rule px-2 py-1.5">
              <option value="">Not stated</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="sm:col-span-2">
            <span className="text-sm">Language for questions</span>
            <select value={patient.preferred_language ?? ""} onChange={(e) => setPatient({ ...patient, preferred_language: e.target.value })} className="mt-1 w-full rounded border border-rule px-2 py-1.5">
              <option value="hi-en">Hinglish (Roman script)</option>
              <option value="hi">Hindi (देवनागरी)</option>
              <option value="en">English</option>
            </select>
          </label>
        </div>
      </Panel>

      <Panel title="What is the problem?">
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          placeholder="In the patient's own words, any language. For example: Subah se seene mein dard hai aur pasina aa raha hai."
          className="w-full rounded border border-rule p-2"
        />
        <div className="mt-3 space-y-3">
          <VoiceRecorder onRecorded={(f) => setFiles((fs) => [...fs, f])} />
          <label className="inline-flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-ink-faint bg-ward/50 px-3 py-2 text-sm hover:border-accent">
            <FileUp className="h-4 w-4 text-accent" aria-hidden />
            Add reports (photo or PDF) or audio files
            <input
              type="file"
              multiple
              accept="image/*,application/pdf,audio/*"
              className="sr-only"
              onChange={(e) => {
                const picked = Array.from(e.target.files ?? []);
                setFiles((fs) => [...fs, ...picked]);
                e.target.value = "";
              }}
            />
          </label>
          {files.length > 0 && (
            <ul className="space-y-1">
              {files.map((f, i) => (
                <li key={i} className="flex items-center justify-between rounded border border-rule px-2 py-1 text-sm">
                  <span>
                    {f.name} <span className="text-ink-faint">({Math.ceil(f.size / 1024)} KB)</span>
                  </span>
                  <button type="button" onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))} className="text-ink-faint hover:text-p1" aria-label={`Remove ${f.name}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>

      <Panel title="Vitals, if measured">
        <div className="grid gap-3 sm:grid-cols-3">
          {VITAL_FIELDS.map(({ key, label, unit, step }) => (
            <label key={key}>
              <span className="text-sm">
                {label} <span className="text-ink-faint">{unit}</span>
              </span>
              <input
                type="number"
                step={step ?? "1"}
                value={vitals[key] ?? ""}
                onChange={(e) => setVitals({ ...vitals, [key]: e.target.value })}
                className="mt-1 w-full rounded border border-rule px-2 py-1.5"
              />
            </label>
          ))}
          <label>
            <span className="text-sm">Responsiveness (ACVPU)</span>
            <select value={consciousness} onChange={(e) => setConsciousness(e.target.value)} className="mt-1 w-full rounded border border-rule px-2 py-1.5">
              <option value="">Not assessed</option>
              <option value="A">A: Alert</option>
              <option value="C">C: New confusion</option>
              <option value="V">V: Responds to voice</option>
              <option value="P">P: Responds to pain</option>
              <option value="U">U: Unresponsive</option>
            </select>
          </label>
        </div>
      </Panel>

      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" busy={busy} disabled={!canSubmit}>
          {busy ? "Reading inputs and checking priority" : "Submit for triage"}
        </Button>
        {!canSubmit && <span className="text-sm text-ink-faint">Needs consent, a name, and a message or file.</span>}
      </div>
    </form>
  );
}
