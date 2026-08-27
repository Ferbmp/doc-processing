import type { AuditEvent } from "../api";
import { formatTime } from "../hooks";

const TONE: Record<string, string> = {
  document_received: "info",
  job_enqueued: "",
  processing_started: "info",
  extraction_succeeded: "ok",
  result_accepted: "ok",
  review_approved: "ok",
  attempt_failed: "bad",
  processing_failed: "bad",
  review_rejected: "bad",
  retry_scheduled: "warn",
  review_required: "warn",
  duplicate_submission_ignored: "warn",
  duplicate_execution_ignored: "warn",
  job_recovered: "warn",
  manual_retry_requested: "info",
};

export function Timeline({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return <p className="muted small">No events recorded yet.</p>;
  }

  return (
    <ol className="timeline">
      {events.map((event) => (
        <li key={event.id} className={TONE[event.event_type] ?? ""}>
          <div className="when">
            {formatTime(event.created_at)}
            {event.attempt !== null ? ` · attempt ${event.attempt}` : ""}
            {event.actor ? ` · ${event.actor}` : ""}
          </div>
          <div className="what">{event.event_label}</div>
          <div className="msg">{event.message}</div>
        </li>
      ))}
    </ol>
  );
}
