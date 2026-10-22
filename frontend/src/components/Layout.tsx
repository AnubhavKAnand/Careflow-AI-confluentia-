import { useEffect, useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { Activity, LogOut, Plus } from "lucide-react";
import { api, type Health } from "../api/client";
import { useAuth } from "../context/AuthContext";

const ROLE_LABEL: Record<string, string> = { doctor: "Doctor", nurse: "Nurse", intake: "Intake desk", admin: "Data protection officer" };

export function Layout() {
  const { user, logout, can } = useAuth();
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);
  const model = health?.providers.find((p) => p.available)?.name ?? (health ? "rules only" : "offline");
  const nav = [
    { to: "/", label: "Review queue", show: can("case:read") },
    { to: "/learning", label: "Learning", show: can("learning:read") },
    { to: "/evaluation", label: "Evaluation", show: can("evaluation:read") },
    { to: "/audit", label: "Audit log", show: can("audit:read") },
    { to: "/privacy", label: "Data requests", show: can("data:erase") },
  ].filter((n) => n.show);

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-20 border-b border-rule bg-panel/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2.5">
          <Link to="/" className="flex items-center gap-2 text-lg font-bold text-accent">
            <Activity className="h-5 w-5" aria-hidden /> CareFlow
          </Link>
          <nav className="flex gap-1 text-sm">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === "/"}
                className={({ isActive }) => `rounded-md px-3 py-1.5 ${isActive ? "bg-accent-wash font-bold text-accent" : "text-ink-soft hover:text-ink"}`}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-xs text-ink-faint md:inline" title="Model used for extraction">
              Model: {model}
            </span>
            {health?.security_warnings?.length ? (
              <span className="hidden text-xs font-bold text-p2 lg:inline" title={health.security_warnings.join(" ")}>
                Dev secret in use
              </span>
            ) : null}
            {user && (
              <span className="text-right text-sm leading-tight">
                <span className="block font-bold">{user.full_name}</span>
                <span className="block text-xs text-ink-soft">{ROLE_LABEL[user.role] ?? user.role}</span>
              </span>
            )}
            {can("case:create") && (
              <Link to="/intake" className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-bold text-white hover:bg-accent-strong">
                <Plus className="h-4 w-4" aria-hidden /> New case
              </Link>
            )}
            <button onClick={() => logout()} className="inline-flex items-center gap-1 rounded-md border border-rule px-2 py-1.5 text-sm text-ink-soft hover:text-ink" title="Sign out">
              <LogOut className="h-4 w-4" aria-hidden />
              <span className="sr-only md:not-sr-only">Sign out</span>
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-5">
        <Outlet />
      </main>
      <footer className="border-t border-rule px-4 py-3 text-center text-xs text-ink-faint">
        Decision support only. CareFlow suggests a review order; a qualified healthcare professional makes every triage decision.
      </footer>
    </div>
  );
}
