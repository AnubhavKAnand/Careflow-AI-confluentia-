// Public page: a patient withdraws consent with the case number and code from their consent receipt.
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { Button, ErrorNote } from "../components/ui";

export default function Withdraw() {
  const [caseId, setCaseId] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-md space-y-4 p-6">
      <h1 className="text-2xl font-bold">Withdraw consent</h1>
      <p className="text-sm text-ink-soft">
        Enter the case number and code printed on your consent slip. Your information will stop being used and will be deleted by the clinic's data protection officer.
      </p>
      <p className="text-sm text-ink-soft" lang="hi">
        अपनी सहमति वापस लेने के लिए पर्ची पर छपा केस नंबर और कोड डालें। आपकी जानकारी का उपयोग बंद हो जाएगा और उसे हटा दिया जाएगा।
      </p>
      {done ? (
        <p role="status" className="rounded-md bg-p4-wash px-3 py-2 text-sm">
          {done}
        </p>
      ) : (
        <form
          className="space-y-3 rounded-lg border border-rule bg-panel p-5"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              const r = await api.publicWithdraw(Number(caseId), code);
              setDone(r.message);
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="block">
            <span className="text-sm">Case number</span>
            <input required inputMode="numeric" value={caseId} onChange={(e) => setCaseId(e.target.value.replace(/\D/g, ""))} className="mt-1 w-full rounded border border-rule px-2 py-1.5" />
          </label>
          <label className="block">
            <span className="text-sm">Code (for example K7MP-2QXA)</span>
            <input required value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} className="mt-1 w-full rounded border border-rule px-2 py-1.5 tracking-wider" />
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" variant="danger" busy={busy} disabled={!caseId || code.length < 4}>
            Withdraw my consent
          </Button>
        </form>
      )}
      <Link to="/login" className="text-sm text-accent">
        Staff sign in
      </Link>
    </div>
  );
}
