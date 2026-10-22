// API client + types mirroring backend/app/schemas. Authenticated with a bearer token from /api/auth/login.

export type Priority = "P1" | "P2" | "P3" | "P4";
export type Role = "doctor" | "nurse" | "intake" | "admin";

export interface Health {
  status: string;
  engine_version: string;
  providers: { name: string; available: boolean }[];
  final_fallback: string;
  security_warnings?: string[];
  external_documents_allowed?: boolean;
}

export interface CaseListItem {
  id: number;
  patient_name: string;
  age_years: number | null;
  sex: string | null;
  status: string;
  priority: Priority | null;
  priority_label: string | null;
  final_priority: Priority | null;
  chief_complaint: string | null;
  red_flag_count: number;
  top_reason: string | null;
  uncertain: boolean;
  sort_score: number;
  queue_score: number;
  created_at: string;
  waiting_minutes: number;
  overdue: boolean;
  target_minutes: number | null;
  completeness: number | null;
  flag_counts: Partial<Record<FlagType, number>>;
  critical_flags: number;
  source_kinds: string[];
}

export interface Evidence {
  source_id: number | null;
  quote: string | null;
  start: number | null;
  end: number | null;
  grounded: boolean | null;
  origin: string;
  in_translation: boolean;
  locator: { page?: number; bbox?: number[]; start_s?: number; end_s?: number } | null;
  source_confidence: number | null;
}

export interface Value<T = unknown> {
  value: T | null;
  confidence: number;
  evidence: Evidence | null;
}

export interface Symptom {
  name: string;
  canonical_id: string | null;
  negated: boolean;
  onset: string | null;
  duration: string | null;
  severity: string | null;
  progression: string | null;
  body_site: string | null;
  confidence: number;
  evidence: Evidence | null;
}

export interface LabResult {
  name: string;
  canonical_id: string | null;
  value: number | string | null;
  unit: string | null;
  reference_range: string | null;
  abnormal_flag: string | null;
  confidence: number;
  evidence: Evidence | null;
}

export interface Extraction {
  chief_complaint: Value<string>;
  age_years: Value<number>;
  sex: Value<string>;
  pregnancy_status: Value<string>;
  symptoms: Symptom[];
  vitals: Record<string, Value<number | string | boolean>>;
  labs: LabResult[];
  medical_history: Value<string>[];
  medications: Value<string>[];
  allergies: Value<string>[];
  timeline: { when: string; event: string; evidence: Evidence | null }[];
  urgency_signals: { signal: string; evidence: Evidence | null }[];
  uncertainties: string[];
  provider: string | null;
  fallback_used: boolean;
}

export interface Reason {
  kind: string;
  text: string;
  priority: Priority;
  rule_id: string | null;
  reference: string | null;
  evidence: Evidence[];
}

export type FlagType = "suspicious" | "conflicting" | "unclear" | "missing";

export interface Flag {
  type: FlagType;
  severity: "info" | "warning" | "critical";
  text: string;
  source_ids: number[];
  ref: string | null;
}

export interface FollowUp {
  id: string;
  text: string;
  text_en: string;
  language: string;
  target: "patient" | "staff" | "clinician";
  priority: "critical" | "important" | "nice";
  reason: string;
  origin: string;
  answer_type: "yes_no" | "free_text";
  symptom: string | null;
}

export interface Triage {
  priority: Priority;
  priority_label: string;
  target_minutes: number;
  sort_score: number;
  reasons: Reason[];
  red_flags: { rule_id: string; label: string; priority: Priority; rationale: string; reference: string | null; evidence: Evidence[] }[];
  news2: { total: number; band: string; partial: boolean; applicable: boolean; note: string | null; params_present: number } | null;
  data_quality: { avg_confidence: number; uncertain: boolean; notes: string[] };
  validation: {
    flags: Flag[];
    followups: FollowUp[];
    completeness: number;
    missing: { id: string; label: string; priority: string }[];
  } | null;
  engine_version: string;
}

export interface SourceReading {
  engine?: string;
  avg_confidence?: number;
  legibility?: string;
  pages?: number;
  lines?: { text: string; confidence: number; page: number; bbox: number[] | null; char_start: number; char_end: number }[];
  segments?: { text: string; start_s: number; end_s: number; confidence: number; char_start: number; char_end: number }[];
  duration_s?: number;
  quality_flags?: { kind: string; detail: string; severity: string }[];
  translation_engine?: string;
  filename?: string;
}

export interface Source {
  id: number;
  kind: string;
  label: string | null;
  original_text: string;
  language: string | null;
  language_confidence: number | null;
  translated_text: string | null;
  translation_confidence: number | null;
  mime: string | null;
  processing_status: string;
  has_file: boolean;
  reading: SourceReading;
}

export interface Note {
  id: number;
  version: number;
  content: string;
  status: string;
  author: string;
  author_type: string;
  created_at: string;
}

export interface CaseDetail {
  id: number;
  status: string;
  patient: { id: number; name: string; age_years: number | null; sex: string | null; preferred_language: string | null; consent_at: string | null };
  sources: Source[];
  extraction: Extraction | null;
  extraction_provider: string | null;
  extraction_latency_ms: number | null;
  triage: Triage | null;
  note: Note | null;
  final_priority: Priority | null;
  created_at: string;
  permissions: string[];
  withdrawn: boolean;
  learning_mode: "shadow" | "recommend";
  agent: {
    predicted: Priority | null;
    confidence: number;
    abstained: boolean;
    rules_priority: Priority;
    model_version: number;
    explanation: { feature: string; label: string; weight: number }[];
  } | null;
  receipt: { case_id: number; access_code: string; consent_version: string; consent_at: string; withdraw_url: string } | null;
}

export interface User {
  username: string;
  full_name: string;
  role: Role;
  permissions: string[];
}

export interface SimilarCase {
  case_id: number;
  similarity: number;
  final_priority: Priority;
  rules_priority: Priority;
  changed_by_clinician: boolean;
  chief_complaint: string | null;
  age_band: string | null;
  shared: string[];
  reviewed_at: string;
}

export interface GraduationCheck {
  id: string;
  label: string;
  value: number | null;
  target: number;
  met: boolean;
}

export interface LearningStatus {
  mode: "shadow" | "recommend";
  changed_at: string;
  changed_by: string | null;
  model: { trained_on: number; features: number; min_training: number };
  reward: { agree: number; over_triage_per_level: number; under_triage_per_level: number };
  metrics: {
    reviews: number;
    synthetic_examples: number;
    agreement_last100: number | null;
    rules_agreement_last100: number | null;
    under_triage_last100: number | null;
    rules_under_triage_last100: number | null;
    coverage_last100: number | null;
    clinician_changed_rules: number | null;
    confusion: Record<Priority, Record<Priority, number>>;
    curve: { upto: number; agent_agreement: number | null; rules_agreement: number | null; coverage: number | null }[];
    automation_bias: { agreement_when_visible: number | null; agreement_on_blind_checks: number | null; visible_n: number; blind_n: number };
  };
  graduation: { checks: GraduationCheck[]; ready: boolean; note: string };
  top_features: Partial<Record<Priority, { feature: string; label: string; weight: number }[]>>;
  blind_check_share: number;
}

export interface SimulationResult {
  weeks: number;
  per_week: number;
  seed: number;
  curve: {
    week: number;
    agent_agreement: number | null;
    rules_agreement: number | null;
    coverage: number | null;
    agent_under_triage: number | null;
    rules_under_triage: number | null;
    n: number;
  }[];
  final: Record<string, number | null>;
  patterns: Record<string, { agent: number | null; rules: number | null; agent_suggests: Priority | null }>;
  top_p2_features: { feature: string; label: string; weight: number }[];
}

export interface EvalMetrics {
  n: number;
  scored: number;
  errors: number;
  accuracy: number | null;
  within_one: number | null;
  under_triage: number | null;
  under_triage_urgent: number | null;
  urgent_cases: number;
  severe_under_triage: number;
  over_triage: number | null;
  weighted_kappa: number | null;
  confusion: Record<Priority, Record<Priority, number>>;
  by_category: Record<string, { n: number; accuracy: number | null; under_triage: number }>;
  by_language: Record<string, { n: number; accuracy: number | null; under_triage: number }>;
  red_flag_recall: number | null;
  false_alarms_on_routine: number;
  routine_cases: number;
  flag_types: Record<string, { tp: number; fn: number; fp: number; recall: number | null; precision: number | null }>;
  latency_ms: { mean: number | null; p50: number | null; p95: number | null };
  extraction_ms: { mean: number | null; p50: number | null; p95: number | null };
  fallbacks: number;
  misses: { id: string; category: string; language: string; expected: Priority; got: Priority; direction: "under" | "over"; reasons: string[]; note: string | null }[];
  by_split: Record<string, { n: number; accuracy: number | null; within_one: number | null; under_triage_urgent: number | null; urgent_cases: number; severe_under_triage: number; weighted_kappa: number | null; red_flag_recall: number | null }> | null;
  nurse_baseline?: {
    n: number; accuracy: number | null; within_one: number | null; under_triage_urgent: number | null; urgent_cases: number;
    severe_under_triage: number; over_triage: number | null; weighted_kappa: number | null; confusion: Record<string, Record<string, number>>;
  } | null;
}

export interface EvalResult {
  name: string;
  provider: string;
  models: string[];
  engine_version: string;
  dataset_version: string;
  run_at: string;
  machine: { platform: string; python: string; cpus: number };
  metrics: EvalMetrics;
}

export interface EvaluationData {
  dataset: { version: string; description: string; n: number; by_split: Record<string, number>; by_category: Record<string, number> };
  results: EvalResult[];
}

export interface ErasureRequest {
  patient_id: number;
  case_ids: number[];
  withdrawn_at: string;
  withdrawn_by: string;
  reason: string | null;
  files: number;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  actor_type: "human" | "ai" | "system";
  action: string;
  case_id: number | null;
  details: Record<string, unknown> | null;
  patient_id: number | null;
  hash: string | null;
}

export interface PatientIn {
  name: string;
  age_years?: number | null;
  sex?: "male" | "female" | "other" | null;
  phone?: string | null;
  preferred_language?: string | null;
}

export interface VitalsIn {
  spo2?: number;
  pulse?: number;
  resp_rate?: number;
  systolic_bp?: number;
  diastolic_bp?: number;
  temperature_c?: number;
  consciousness?: "A" | "C" | "V" | "P" | "U";
  on_oxygen?: boolean;
}

// ---------------------------------------------------------------- transport
let token: string | null = null;
let onUnauthorized: (() => void) | null = null;
export function setToken(t: string | null) {
  token = t;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData;
  const res = await fetch(path, {
    ...init,
    headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...authHeaders(), ...(init.headers || {}) },
  });
  if (res.status === 401 && token && !path.startsWith("/api/auth/login")) onUnauthorized?.();
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  me: () => request<User>("/api/auth/me"),
  withdraw: (caseId: number, reason?: string) =>
    request<{ withdrawn: boolean }>(`/api/cases/${caseId}/withdraw`, { method: "POST", body: JSON.stringify({ reason }) }),
  publicWithdraw: (case_id: number, access_code: string) =>
    request<{ withdrawn: boolean; message: string }>("/api/public/withdraw", { method: "POST", body: JSON.stringify({ case_id, access_code }) }),
  erasureRequests: () => request<ErasureRequest[]>("/api/privacy/requests"),
  erase: (patientId: number) => request<Record<string, number | boolean>>(`/api/patients/${patientId}`, { method: "DELETE" }),
  auditLog: (filters: Record<string, string | number | undefined>) => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));
    return request<AuditEntry[]>(`/api/audit?${q}`);
  },
  similar: (caseId: number) => request<{ summary: string | null; cases: SimilarCase[] }>(`/api/cases/${caseId}/similar`),
  learningStatus: () => request<LearningStatus>("/api/learning/status"),
  setLearningMode: (mode: "shadow" | "recommend", force = false) =>
    request<{ mode: string }>("/api/learning/mode", { method: "POST", body: JSON.stringify({ mode, force }) }),
  simulate: (weeks: number, per_week: number, seed: number) =>
    request<SimulationResult>("/api/learning/simulate", { method: "POST", body: JSON.stringify({ weeks, per_week, seed }) }),
  bootstrap: (n: number) => request<{ added: number }>(`/api/learning/bootstrap?n=${n}`, { method: "POST" }),
  evaluation: () => request<EvaluationData>("/api/evaluation"),
  verifyAudit: () => request<{ ok: boolean; entries: number; broken_at_id?: number; detail?: string; head?: string }>("/api/audit/verify"),
  listCases: (status?: string) => request<CaseListItem[]>(`/api/cases${status ? `?status=${status}` : ""}`),
  getCase: (id: number) => request<CaseDetail>(`/api/cases/${id}`),
  audit: (caseId: number) => request<AuditEntry[]>(`/api/audit?case_id=${caseId}`),

  intake: (payload: { patient: PatientIn; consent_given: boolean; message?: string; vitals?: VitalsIn }, files: File[]) => {
    const fd = new FormData();
    fd.append("payload", JSON.stringify(payload));
    files.forEach((f) => fd.append("files", f, f.name));
    return request<CaseDetail>("/api/cases/intake", { method: "POST", body: fd });
  },
  addSources: (id: number, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    return request<CaseDetail>(`/api/cases/${id}/sources`, { method: "POST", body: fd });
  },
  answer: (id: number, answers: { question_id: string; answer?: string; yes?: boolean }[]) =>
    request<CaseDetail>(`/api/cases/${id}/answers`, { method: "POST", body: JSON.stringify({ answers }) }),
  retriage: (id: number) => request<CaseDetail>(`/api/cases/${id}/retriage`, { method: "POST" }),
  saveNote: (id: number, content: string) =>
    request<CaseDetail>(`/api/cases/${id}/note`, { method: "PUT", body: JSON.stringify({ content }) }),
  review: (id: number, body: { action: "approve" | "override"; final_priority: Priority; reason?: string; note_content?: string }) =>
    request<CaseDetail>(`/api/cases/${id}/review`, { method: "POST", body: JSON.stringify(body) }),

  /** Original upload as an object URL (fetched with auth headers, so it keeps working once Phase 5 adds tokens). */
  sourceFileUrl: async (sourceId: number): Promise<string> => {
    const res = await fetch(`/api/sources/${sourceId}/file`, { headers: authHeaders() });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    return URL.createObjectURL(await res.blob());
  },
};
