// Signed-in user. The token lives in sessionStorage (cleared when the tab closes; a shared clinic
// computer does not keep someone signed in) and is sent as a bearer token on every request.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, setToken, setUnauthorizedHandler, type User } from "../api/client";

interface Ctx {
  user: User | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: (reason?: string) => void;
  can: (perm: string) => boolean;
  notice: string | null;
}

const AuthContext = createContext<Ctx | null>(null);
const KEY = "careflow.session";

function readStored(): { token: string; user: User } | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const stored = readStored();
  if (stored) setToken(stored.token);
  const [user, setUser] = useState<User | null>(stored?.user ?? null);
  const [ready, setReady] = useState(!stored);
  const [notice, setNotice] = useState<string | null>(null);

  const logout = useCallback((reason?: string) => {
    setToken(null);
    setUser(null);
    setNotice(reason ?? null);
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => logout("Your session ended. Please sign in again."));
    if (stored) {
      api
        .me()
        .then((u) => setUser(u))
        .catch(() => logout("Your session ended. Please sign in again."))
        .finally(() => setReady(true));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (username: string, password: string) => {
    const r = await api.login(username, password);
    setToken(r.access_token);
    setUser(r.user);
    setNotice(null);
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ token: r.access_token, user: r.user }));
    } catch {
      /* storage blocked: stays signed in for this page only */
    }
  };

  return (
    <AuthContext.Provider value={{ user, ready, login, logout, can: (p) => !!user?.permissions.includes(p), notice }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
