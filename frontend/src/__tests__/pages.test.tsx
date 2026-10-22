// Smoke tests: render pages for each role against real API responses captured from the seeded backend.
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fx from "./fixtures.json";
import { AppRoutes } from "../App";
import { AuthProvider } from "../context/AuthContext";

const F = fx as Record<string, unknown>;
type Role = "doctor" | "intake" | "admin";

function mockApi(role: Role) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      let body: unknown = {};
      if (u.startsWith("/api/health")) body = F.health;
      else if (u.startsWith("/api/auth/me")) body = F[`user_${role}`];
      else if (u.startsWith("/api/auth/login")) body = { access_token: "t", user: F.user_doctor };
      else if (u.startsWith("/api/audit/verify")) body = F.verify;
      else if (u.startsWith("/api/audit")) body = F[`audit_${role}`] ?? [];
      else if (u.startsWith("/api/privacy/requests")) body = F.requests;
      else if (u.startsWith("/api/learning/status")) body = F[`learning_${role}`];
      else if (u.startsWith("/api/learning/simulate")) body = F.simulation;
      else if (u.startsWith("/api/evaluation")) body = F.evaluation;
      else if (u.endsWith("/similar")) body = F.similar1;
      else if (u.startsWith("/api/cases/999")) body = F.case_rec_doctor;
      else if (u.startsWith("/api/sources/")) return new Response(new Blob(["x"]), { status: 200 });
      else if (u.startsWith("/api/cases?") || u === "/api/cases") body = F[`list_${role}`];
      else {
        const m = u.match(/\/api\/cases\/(\d+)/);
        body = m ? F[`case${m[1]}_${role}`] : {};
      }
      void init;
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

function signIn(role: Role) {
  sessionStorage.setItem("careflow.session", JSON.stringify({ token: "t", user: F[`user_${role}`] }));
  mockApi(role);
}

beforeEach(() => {
  sessionStorage.clear();
  Element.prototype.scrollIntoView = vi.fn();
  URL.createObjectURL = vi.fn(() => "blob:x");
  URL.revokeObjectURL = vi.fn();
});
afterEach(cleanup);

function at(path: string) {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  );
}

describe("authentication", () => {
  it("redirects to sign-in when signed out", async () => {
    mockApi("doctor");
    at("/");
    await screen.findByRole("heading", { name: "Sign in" });
  });

  it("public withdrawal page needs no sign-in", async () => {
    mockApi("doctor");
    at("/withdraw");
    await screen.findByRole("heading", { name: "Withdraw consent" });
  });
});

describe("doctor", () => {
  beforeEach(() => signIn("doctor"));

  it("dashboard lists cases with P1 first and filters by lane", async () => {
    at("/");
    await waitFor(() => expect(screen.getAllByRole("row").length).toBeGreaterThan(5));
    expect(screen.getAllByRole("row")[1].textContent).toContain("P1");
    fireEvent.click(screen.getByRole("tab", { name: /P4 Routine/ }));
    await waitFor(() => expect(screen.getAllByRole("row").slice(1).every((r) => r.textContent!.includes("P4"))).toBe(true));
  });

  it.each([1, 11, 14, 15])("case %i renders summary, flags, questions, note and sources", async (id) => {
    at(`/cases/${id}`);
    await screen.findByText("Why this priority");
    expect(screen.getByText("Patient summary")).toBeTruthy();
    expect(screen.getByText("Follow-up questions")).toBeTruthy();
    expect(screen.getByRole("tablist", { name: "Sources" })).toBeTruthy();
    expect((screen.getByLabelText(/Triage note/) as HTMLTextAreaElement).value).toContain("TRIAGE NOTE");
    expect(screen.getByText("Activity log")).toBeTruthy();
  });

  it("clicking a source tag highlights the evidence", async () => {
    at("/cases/1");
    await screen.findByText("Why this priority");
    fireEvent.click(screen.getAllByTitle(/“/)[0]);
    await waitFor(() => expect(document.querySelector("mark.evidence")).not.toBeNull());
  });

  it("override requires a reason", async () => {
    at("/cases/11");
    await screen.findByText("Why this priority");
    fireEvent.click(screen.getByRole("radio", { name: /P2 Very urgent/ }));
    const btn = screen.getByRole("button", { name: /Override to P2/ }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Why are you changing/), { target: { value: "Platelets rechecked" } });
    expect(btn.disabled).toBe(false);
  });

  it("audit log page verifies the chain", async () => {
    at("/audit");
    await screen.findByRole("heading", { name: "Audit log" });
    fireEvent.click(screen.getByRole("button", { name: /Check for tampering/ }));
    await screen.findByText(/Intact/);
  });

  it("case page offers similar past decisions and the shadow-mode note", async () => {
    at("/cases/1");
    await screen.findByText("Similar past decisions");
    expect(screen.getByText(/Shadow learning is on/)).toBeTruthy();
    expect(screen.queryByLabelText("Learned suggestion")).toBeNull(); // blind in shadow mode
  });

  it("recommendation mode shows the learned suggestion with reasons", async () => {
    at("/cases/999");
    const card = await screen.findByLabelText("Learned suggestion");
    expect(card.textContent).toContain("P2");
    expect(card.textContent).toMatch(/past clinician decisions/);
  });

  it("learning page shows graduation checks and runs the simulation", async () => {
    at("/learning");
    await screen.findByRole("heading", { name: "Shadow learning" });
    expect(screen.getByText("Ready to show suggestions?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run simulation" }));
    expect((await screen.findAllByText("Agreement with the clinician's final priority")).length).toBeGreaterThan(0);
    expect(screen.getByText("Headache in pregnancy")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Show table" })[0]);
    expect(screen.getAllByRole("table").length).toBeGreaterThan(1);
  });

  it("evaluation page leads with the safety metric and lists misses", async () => {
    at("/evaluation");
    await screen.findByRole("heading", { name: "Evaluation" });
    expect(screen.getByText("Urgent patients (P1/P2) suggested as less urgent")).toBeTruthy();
    expect(screen.getByText("Held-out (never used for tuning)")).toBeTruthy();
    expect(screen.getByText(/Cases it got wrong/)).toBeTruthy();
  });

  it("data requests page is not available to doctors", async () => {
    at("/privacy");
    await screen.findByText(/does not have access/);
  });
});

describe("intake desk", () => {
  beforeEach(() => signIn("intake"));

  it("sees questions but no clinical note, audit or finalize", async () => {
    at("/cases/1");
    await screen.findByText("Why this priority");
    expect(screen.getByText("Follow-up questions")).toBeTruthy();
    expect(screen.queryByLabelText(/Triage note/)).toBeNull();
    expect(screen.queryByText("Activity log")).toBeNull();
    expect(screen.getByText(/visible to doctors and nurses only/)).toBeTruthy();
  });

  it("intake needs consent before submit", async () => {
    at("/intake");
    const submit = (await screen.findByRole("button", { name: /Submit for triage/ })) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test" } });
    fireEvent.change(screen.getByPlaceholderText(/patient's own words/), { target: { value: "fever" } });
    expect(submit.disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(submit.disabled).toBe(false);
  });
});

describe("data protection officer", () => {
  beforeEach(() => signIn("admin"));

  it("sees priority but no clinical text", async () => {
    at("/cases/11");
    await screen.findByText(/hidden for your role/);
    expect(screen.queryByText("Patient summary")).toBeNull();
    expect(screen.queryByRole("tablist", { name: "Sources" })).toBeNull();
  });

  it("erasure needs typed confirmation", async () => {
    at("/privacy");
    fireEvent.click(await screen.findByRole("button", { name: "Erase data" }));
    const btn = screen.getByRole("button", { name: "Erase permanently" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Type ERASE/), { target: { value: "ERASE" } });
    expect(btn.disabled).toBe(false);
  });
});
