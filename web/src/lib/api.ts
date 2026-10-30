// Typed client for the Enterprise Knowledge API. Requests go to /api/*, which Next.js
// rewrites to the FastAPI server (EKA_API_URL), so the browser needs no CORS setup.

export type AnswerMode = "direct" | "workflow";

export interface Identity {
  tenant: string;
  user: string;
  groups: string;
}

export interface Citation {
  label: string;
  chunk_id: string;
  document_id: string;
  document_version: number;
  title: string;
  page: number | null;
  section: string | null;
  char_start: number | null;
  char_end: number | null;
}

export interface AnswerResponse {
  status: "answered" | "insufficient_evidence";
  answer: string | null;
  abstention_reason: string | null;
  citations: Citation[];
  model_id: string | null;
  prompt_version: string;
  mode: AnswerMode;
  sub_questions: string[];
  usage: { steps: number; model_calls: number };
  // Workflow answers are checked claim by claim (ADR-0019); null when nothing was verified.
  verification: { verified: boolean | null; revisions: number };
}

export interface Job {
  id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  attempts: number;
  max_attempts: number;
  error_category: string | null;
  document_id: string;
  document_version: number;
  created_at: string;
  updated_at: string;
}

export interface DocumentSummary {
  id: string;
  version: number;
  title: string;
  status: string;
  language: string;
  error_category: string | null;
}

export interface UploadResponse {
  document: DocumentSummary;
  job: Job | null;
  duplicate: boolean;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly category: string,
    message: string,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const BASE = "/api";

export function identityHeaders(identity: Identity): Record<string, string> {
  return {
    "X-Tenant-ID": identity.tenant.trim(),
    "X-User-ID": identity.user.trim(),
    "X-User-Groups": identity.groups
      .split(",")
      .map((g) => g.trim())
      .filter(Boolean)
      .join(","),
  };
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "api_unreachable", "The knowledge API is not reachable. Is it running?");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as { error?: { category?: string; message?: string; request_id?: string } })
      ?.error;
    throw new ApiError(
      response.status,
      error?.category ?? "http_error",
      error?.message ?? `The API answered ${response.status}.`,
      error?.request_id ?? null,
    );
  }
  return body as T;
}

export async function askQuestion(
  question: string,
  mode: AnswerMode,
  identity: Identity,
): Promise<{ answer: AnswerResponse; latencyMs: number }> {
  const started = performance.now();
  const answer = await request<AnswerResponse>("/v1/answers", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...identityHeaders(identity) },
    body: JSON.stringify({ question, mode }),
  });
  return { answer, latencyMs: performance.now() - started };
}

export function uploadDocument(
  file: File,
  allowedGroups: string,
  identity: Identity,
  title?: string,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("allowed_groups", allowedGroups);
  if (title?.trim()) form.append("title", title.trim());
  return request<UploadResponse>("/v1/documents", {
    method: "POST",
    headers: identityHeaders(identity),
    body: form,
  });
}

export function getJob(jobId: string, identity: Identity): Promise<Job> {
  return request<Job>(`/v1/jobs/${encodeURIComponent(jobId)}`, {
    headers: identityHeaders(identity),
  });
}
