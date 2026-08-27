import type { DocumentStatus } from "../api";

const LABELS: Record<DocumentStatus, string> = {
  received: "Received",
  processing: "Processing",
  retry_scheduled: "Retry scheduled",
  review_required: "Review required",
  completed: "Completed",
  rejected: "Rejected",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  return <span className={`badge ${status}`}>{LABELS[status] ?? status}</span>;
}
