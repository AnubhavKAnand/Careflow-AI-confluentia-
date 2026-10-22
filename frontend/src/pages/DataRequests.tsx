// Data protection officer: patients who withdrew consent, and permanent erasure of their data.
import { useCallback, useEffect, useState } from "react";
import { api, type ErasureRequest } from "../api/client";
import { Button, ErrorNote, Spinner } from "../components/ui";

export default function DataRequests() {
  const [rows, setRows] = useState<ErasureRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  const load = useCallback(() => {
    api.erasureRequests().then(setRows).catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-2xl font-bold">Data requests</h1>
        <p className="text-sm text-ink-soft">
          Patients who withdrew consent. Their cases are already hidden and no longer processed. Erasing deletes uploaded files, messages, transcripts, extracted
          data, notes and the patient record; the audit log keeps only a record that erasure happened.
        </p>
      </div>
      {done && (
        <p role="status" className="rounded-md bg-p4-wash px-3 py-2 text-sm">
          {done}
        </p>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      {!rows && !error && <Spinner />}
      {rows && rows.length === 0 && <p className="rounded-lg border border-dashed border-rule bg-panel p-8 text-center text-ink-soft">No pending requests.</p>}
      {rows && rows.length > 0 && (
        <ul className="space-y-3">
          {rows.map((r) => (
            <li key={r.patient_id} className="rounded-lg border border-rule bg-panel p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="text-sm">
                  <p className="font-bold">
                    Patient {r.patient_id}, case{r.case_ids.length === 1 ? "" : "s"} {r.case_ids.join(", ")}
                  </p>
                  <p className="text-ink-soft">
                    Withdrawn {new Date(r.withdrawn_at.endsWith("Z") ? r.withdrawn_at : r.withdrawn_at + "Z").toLocaleString("en-IN")} by{" "}
                    {r.withdrawn_by === "patient" ? "the patient (self-service code)" : r.withdrawn_by}
                    {r.reason ? `. Reason: ${r.reason}` : ""}
                  </p>
                  <p className="text-ink-soft">{r.files} uploaded file{r.files === 1 ? "" : "s"} will be deleted.</p>
                </div>
                {confirming !== r.patient_id && (
                  <Button variant="danger" onClick={() => (setConfirming(r.patient_id), setTyped(""))}>
                    Erase data
                  </Button>
                )}
              </div>
              {confirming === r.patient_id && (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md bg-p1-wash p-3 text-sm">
                  <label htmlFor={`confirm-${r.patient_id}`}>This cannot be undone. Type ERASE to confirm:</label>
                  <input id={`confirm-${r.patient_id}`} value={typed} onChange={(e) => setTyped(e.target.value)} className="w-28 rounded border border-rule px-2 py-1" />
                  <Button
                    variant="danger"
                    busy={busy}
                    disabled={typed !== "ERASE"}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        const res = await api.erase(r.patient_id);
                        setDone(`Patient ${r.patient_id} erased: ${res.cases} case(s), ${res.sources} source(s), ${res.files} file(s) deleted.`);
                        setConfirming(null);
                        load();
                      } catch (e) {
                        setError((e as Error).message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Erase permanently
                  </Button>
                  <Button variant="ghost" onClick={() => setConfirming(null)}>
                    Cancel
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
