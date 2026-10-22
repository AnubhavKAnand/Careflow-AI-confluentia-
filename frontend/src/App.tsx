import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { AuthProvider, useAuth } from "./context/AuthContext";
import AuditLog from "./pages/AuditLog";
import CaseDetail from "./pages/CaseDetail";
import Dashboard from "./pages/Dashboard";
import DataRequests from "./pages/DataRequests";
import Evaluation from "./pages/Evaluation";
import Intake from "./pages/Intake";
import Learning from "./pages/Learning";
import Login from "./pages/Login";
import Withdraw from "./pages/Withdraw";

export function RequireAuth({ children, perm }: { children: ReactNode; perm?: string }) {
  const { user, ready, can } = useAuth();
  const location = useLocation();
  if (!ready) return <Spinner label="Checking your session" />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (perm && !can(perm)) return <p className="p-6 text-ink-soft">Your role does not have access to this page.</p>;
  return <>{children}</>;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="login" element={<Login />} />
      <Route path="withdraw" element={<Withdraw />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="intake" element={<RequireAuth perm="case:create"><Intake /></RequireAuth>} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="learning" element={<RequireAuth perm="learning:read"><Learning /></RequireAuth>} />
        <Route path="evaluation" element={<RequireAuth perm="evaluation:read"><Evaluation /></RequireAuth>} />
        <Route path="audit" element={<RequireAuth perm="audit:read"><AuditLog /></RequireAuth>} />
        <Route path="privacy" element={<RequireAuth perm="data:erase"><DataRequests /></RequireAuth>} />
        <Route path="*" element={<p className="p-6">Page not found.</p>} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
