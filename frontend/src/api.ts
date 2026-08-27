export type DocumentStatus =
  | "received"
  | "processing"
  | "retry_scheduled"
  | "review_required"
  | "completed"
  | "rejected"
  | "failed";

export interface DocumentSummary {
  id: string;
  status: DocumentStatus;
  status_label: string;
  source_reference: string;
  input_format: "json" | "text";
  forced_outcome: string;
  attempts: number;
  created_at: string;
  updated_at: string;
  vendor_name: string | null;
  invoice_number: string | null;
  total: string | null;
  currency: string | null;
  review_reasons: string[];
  duplicate?: boolean;
}

export interface LineItem {
  description: string;
  quantity: string | null;
  unit_price: string | null;
  amount: string | null;
}

export interface ExtractionResult {
  attempt: number;
  vendor_name: string | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string | null;
  subtotal: string | null;
  tax: string | null;
  total: string | null;
  line_items: LineItem[];
  confidence: number;
  needs_review: boolean;
  review_reasons: string[];
  raw_extraction: Record<string, unknown>;
  extracted_at: string;
  review_action: string;
  reviewed_by: string;
  reviewed_at: string | null;
  review_notes: string;
  corrections: Record<string, unknown>;
}

export interface ProcessingJob {
  id: number;
  status: "queued" | "running" | "succeeded" | "failed";
  attempt: number;
  max_attempts: number;
  run_after: string;
  locked_by: string;
  locked_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_type: string;
  error_message: string;
  created_at: string;
}

export interface AuditEvent {
  id: number;
  event_type: string;
  event_label: string;
  message: string;
  attempt: number | null;
  from_status: string;
  to_status: string;
  actor: string;
  context: Record<string, unknown>;
  created_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  raw_text: string;
  raw_payload: Record<string, unknown> | null;
  content_hash: string;
  result: ExtractionResult | null;
  jobs: ProcessingJob[];
  events: AuditEvent[];
}

export interface Stats {
  total: number;
  by_status: Record<DocumentStatus, number>;
  jobs_due: number;
}

export class ApiError extends Error {
  code: string;
  details: string[];
  status: number;

  constructor(message: string, status: number, code = "error", details: string[] = []) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  const text = await response.text();
  const body = text ? JSON.parse(text) : null;

  if (!response.ok) {
    const detail =
      body?.detail ??
      (body && typeof body === "object" ? Object.values(body).flat().join(" ") : null) ??
      `Request failed with ${response.status}`;
    throw new ApiError(String(detail), response.status, body?.code, body?.details ?? []);
  }
  return body as T;
}

export const api = {
  stats: () => request<Stats>("/stats/"),

  listDocuments: () =>
    request<{ results: DocumentSummary[]; count: number }>("/documents/?limit=100"),

  getDocument: (id: string) => request<DocumentDetail>(`/documents/${id}/`),

  submitDocument: (payload: {
    content: string;
    source_reference?: string;
    simulate?: string;
  }) =>
    request<DocumentSummary>("/documents/", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  retryDocument: (id: string) =>
    request<DocumentDetail>(`/documents/${id}/retry/`, { method: "POST", body: "{}" }),

  reviewDocument: (
    id: string,
    payload: {
      action: "approve" | "reject";
      reviewer: string;
      notes?: string;
      corrections?: Record<string, string | null>;
    },
  ) =>
    request<DocumentDetail>(`/documents/${id}/review/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

export const SIMULATE_OPTIONS: { value: string; label: string }[] = [
  { value: "random", label: "Random (weighted, like the real thing)" },
  { value: "success", label: "Success - accepted automatically" },
  { value: "flaky", label: "Flaky - fails attempt 1, succeeds on retry" },
  { value: "transient_failure", label: "Always times out - exhausts retries" },
  { value: "permanent_failure", label: "Unrecognisable document - no retries" },
  { value: "low_confidence", label: "Low confidence - needs review" },
  { value: "incomplete", label: "Missing fields - needs review" },
  { value: "arithmetic_mismatch", label: "Totals do not add up - needs review" },
];
