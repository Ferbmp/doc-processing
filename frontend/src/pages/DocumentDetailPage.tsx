import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, type DocumentDetail, type ExtractionResult } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { Timeline } from "../components/Timeline";
import { formatDateTime, usePolled } from "../hooks";

const CORRECTABLE = [
  ["vendor_name", "Vendor name"],
  ["invoice_number", "Invoice number"],
  ["invoice_date", "Invoice date (YYYY-MM-DD)"],
  ["currency", "Currency"],
  ["subtotal", "Subtotal"],
  ["tax", "Tax"],
  ["total", "Total"],
] as const;

type CorrectableField = (typeof CORRECTABLE)[number][0];

function initialFields(result: ExtractionResult | null): Record<CorrectableField, string> {
  const empty = {} as Record<CorrectableField, string>;
  for (const [name] of CORRECTABLE) {
    const value = result ? (result[name] as string | null) : null;
    empty[name] = value ?? "";
  }
  return empty;
}

function ResultPanel({ result }: { result: ExtractionResult }) {
  return (
    <div className="panel section-gap">
      <h2>Extracted financial record</h2>
      <div className="field-grid">
        <div>
          <label>Vendor</label>
          <div>{result.vendor_name ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Invoice number</label>
          <div className="mono">{result.invoice_number ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Invoice date</label>
          <div className="mono">{result.invoice_date ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Currency</label>
          <div className="mono">{result.currency ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Subtotal</label>
          <div className="mono">{result.subtotal ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Tax</label>
          <div className="mono">{result.tax ?? <span className="muted">missing</span>}</div>
        </div>
        <div>
          <label>Total</label>
          <div className="mono">
            {result.total ?? <span className="muted">withheld</span>}
          </div>
        </div>
        <div>
          <label>Confidence</label>
          <div className="mono">{(result.confidence * 100).toFixed(1)}%</div>
        </div>
      </div>

      {result.review_reasons.length > 0 && (
        <>
          <label style={{ marginTop: 12 }}>Why this needs a human</label>
          <ul className="reasons">
            {result.review_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </>
      )}

      {result.reviewed_at && (
        <p className="small muted" style={{ marginTop: 12, marginBottom: 0 }}>
          {result.review_action === "approve" ? "Approved" : "Rejected"} by{" "}
          {result.reviewed_by} on {formatDateTime(result.reviewed_at)}
          {result.review_notes ? ` — ${result.review_notes}` : ""}
        </p>
      )}

      {result.line_items.length > 0 && (
        <details className="section-gap">
          <summary>{result.line_items.length} line item(s)</summary>
          <table>
            <thead>
              <tr>
                <th>Description</th>
                <th style={{ textAlign: "right" }}>Qty</th>
                <th style={{ textAlign: "right" }}>Unit price</th>
                <th style={{ textAlign: "right" }}>Amount</th>
              </tr>
            </thead>
            <tbody>
              {result.line_items.map((item, index) => (
                <tr key={index}>
                  <td>{item.description}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{item.quantity}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{item.unit_price ?? "—"}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{item.amount ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <details className="section-gap">
        <summary>Raw extraction service response</summary>
        <pre>{JSON.stringify(result.raw_extraction, null, 2)}</pre>
      </details>
    </div>
  );
}

function ActionsPanel({
  document,
  onChanged,
}: {
  document: DocumentDetail;
  onChanged: (updated: DocumentDetail) => void;
}) {
  const [reviewer, setReviewer] = useState("fernando");
  const [notes, setNotes] = useState("");
  const [fields, setFields] = useState(() => initialFields(document.result));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<string[]>([]);

  const original = initialFields(document.result);

  useEffect(() => {
    setFields(initialFields(document.result));
  }, [document.id, document.result?.extracted_at]);

  async function run(work: () => Promise<DocumentDetail>) {
    setBusy(true);
    setError(null);
    setDetails([]);
    try {
      onChanged(await work());
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        setDetails(err.details);
      } else {
        setError(String(err));
      }
    } finally {
      setBusy(false);
    }
  }

  function corrections() {
    const changed: Record<string, string | null> = {};
    for (const [name] of CORRECTABLE) {
      if (fields[name] !== original[name]) {
        changed[name] = fields[name].trim() === "" ? null : fields[name].trim();
      }
    }
    return changed;
  }

  const canReview = document.status === "review_required";
  const canRetry = document.status === "failed";

  if (!canReview && !canRetry) return null;

  return (
    <div className="panel section-gap">
      <h2>{canReview ? "Human review" : "Recovery"}</h2>
      {error && (
        <div className="error-box">
          {error}
          {details.length > 0 && (
            <ul className="reasons" style={{ color: "inherit" }}>
              {details.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {canRetry && (
        <>
          <p className="small muted">
            Retrying resets the attempt budget and queues a fresh job. Nothing is
            re-processed unless this document is still undecided.
          </p>
          <button disabled={busy} onClick={() => run(() => api.retryDocument(document.id))}>
            {busy ? "Queueing…" : "Retry processing"}
          </button>
        </>
      )}

      {canReview && (
        <>
          <div className="inline-form-row">
            <div>
              <label htmlFor="reviewer">Reviewer</label>
              <input id="reviewer" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            </div>
            <div>
              <label htmlFor="notes">Notes</label>
              <input id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
          </div>

          <label>Correct the figures before accepting, if needed</label>
          <div className="field-grid">
            {CORRECTABLE.map(([name, label]) => (
              <div key={name}>
                <label htmlFor={`field-${name}`} className="muted">
                  {label}
                </label>
                <input
                  id={`field-${name}`}
                  value={fields[name]}
                  onChange={(e) => setFields({ ...fields, [name]: e.target.value })}
                />
              </div>
            ))}
          </div>

          <div className="row">
            <button
              className="success"
              disabled={busy}
              onClick={() =>
                run(() =>
                  api.reviewDocument(document.id, {
                    action: "approve",
                    reviewer,
                    notes,
                    corrections: corrections(),
                  }),
                )
              }
            >
              {busy ? "Working…" : "Approve and accept"}
            </button>
            <button
              className="danger"
              disabled={busy}
              onClick={() =>
                run(() =>
                  api.reviewDocument(document.id, { action: "reject", reviewer, notes }),
                )
              }
            >
              Reject
            </button>
          </div>
          <p className="muted small" style={{ marginBottom: 0 }}>
            Approving re-runs the same completeness and arithmetic checks that blocked
            auto-acceptance, and the database still refuses a second accepted record for
            the same vendor and invoice number.
          </p>
        </>
      )}
    </div>
  );
}

function JobsPanel({ jobs }: { jobs: DocumentDetail["jobs"] }) {
  return (
    <div className="panel section-gap">
      <h2>Attempts</h2>
      <table>
        <thead>
          <tr>
            <th>Attempt</th>
            <th>Job status</th>
            <th>Worker</th>
            <th>Runs after</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id}>
              <td className="mono">
                {job.attempt} / {job.max_attempts}
              </td>
              <td className="mono">{job.status}</td>
              <td className="mono muted">{job.locked_by || "—"}</td>
              <td className="mono muted">{formatDateTime(job.run_after)}</td>
              <td className="small">
                {job.error_type ? (
                  <>
                    <span className="mono">{job.error_type}</span>
                    <div className="muted">{job.error_message}</div>
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  const { data, error, setData } = usePolled(() => api.getDocument(id), 2000, id);

  if (error) {
    return (
      <div className="panel">
        <div className="error-box">{error}</div>
        <Link to="/">Back to all documents</Link>
      </div>
    );
  }

  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <div className="row">
              <StatusBadge status={data.status} />
              <span className="mono muted">{data.id}</span>
            </div>
            <div className="muted small" style={{ marginTop: 6 }}>
              {data.source_reference || "no source reference"} · received{" "}
              {formatDateTime(data.created_at)} · {data.attempts} attempt(s) ·
              simulated behaviour: {data.forced_outcome || "random"}
            </div>
          </div>
          <Link to="/">← all documents</Link>
        </div>

        <details className="section-gap">
          <summary>Submitted content ({data.input_format})</summary>
          <pre>{data.raw_text}</pre>
          <p className="muted small mono" style={{ marginTop: 8 }}>
            content hash {data.content_hash}
          </p>
        </details>
      </div>

      <ActionsPanel document={data} onChanged={setData} />

      {data.result ? (
        <ResultPanel result={data.result} />
      ) : (
        <div className="panel section-gap">
          <h2>Extracted financial record</h2>
          <p className="muted small">
            No record has been written yet. Nothing is stored until an attempt succeeds,
            so a failed extraction leaves no partial financial data behind.
          </p>
        </div>
      )}

      <div className="panel section-gap">
        <h2>What happened</h2>
        <Timeline events={data.events} />
      </div>

      <JobsPanel jobs={data.jobs} />
    </>
  );
}
