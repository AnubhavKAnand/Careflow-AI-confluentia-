import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { Activity } from "lucide-react";
import { Button, ErrorNote } from "../components/ui";
import { useAuth } from "../context/AuthContext";

const DEMO = [
  { username: "dr.mehra", label: "Doctor", detail: "Reviews and finalizes triage" },
  { username: "sr.thomas", label: "Nurse", detail: "Reviews and finalizes triage" },
  { username: "desk.ravi", label: "Intake desk", detail: "Registers patients, uploads reports, records answers" },
  { username: "admin", label: "Data protection officer", detail: "Consent, erasure, audit log; no clinical text" },
];

export default function Login() {
  const { user, login, notice } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? "/"} replace />;

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-md space-y-5">
        <div className="flex items-center gap-2 text-2xl font-bold text-accent">
          <Activity className="h-6 w-6" aria-hidden /> CareFlow
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError(null);
            try {
              await login(username, password);
            } catch (err) {
              setError((err as Error).message);
              setBusy(false);
            }
          }}
          className="space-y-3 rounded-lg border border-rule bg-panel p-5"
        >
          <h1 className="text-lg font-bold">Sign in</h1>
          {notice && <p className="rounded-md bg-unclear-wash px-3 py-2 text-sm">{notice}</p>}
          <label className="block">
            <span className="text-sm">Username</span>
            <input autoComplete="username" required value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-full rounded border border-rule px-2 py-1.5" />
          </label>
          <label className="block">
            <span className="text-sm">Password</span>
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full rounded border border-rule px-2 py-1.5" />
          </label>
          {error && <ErrorNote>{error}</ErrorNote>}
          <Button type="submit" variant="primary" busy={busy} className="w-full">
            Sign in
          </Button>
        </form>

        <div className="rounded-lg border border-dashed border-rule p-4 text-sm">
          <p className="mb-2 text-ink-soft">
            Demo accounts (password <span className="font-bold text-ink">careflow-demo</span> unless changed in <code>backend/.env</code>):
          </p>
          <ul className="space-y-1">
            {DEMO.map((d) => (
              <li key={d.username}>
                <button type="button" onClick={() => setUsername(d.username)} className="text-left hover:text-accent">
                  <span className="font-bold">{d.label}</span> <span className="text-ink-soft">({d.username}): {d.detail}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <p className="text-center text-sm text-ink-soft">
          Patient who wants to withdraw consent? <Link to="/withdraw" className="font-bold text-accent">Withdraw here</Link>
        </p>
      </div>
    </div>
  );
}
