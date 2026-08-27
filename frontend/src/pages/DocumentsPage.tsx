import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, SIMULATE_OPTIONS, api } from "../api";
import { StatusBadge } from "../components/StatusBadge";
import { formatTime, usePolled } from "../hooks";

const SAMPLE_INVOICE = JSON.stringify(
  {
    vendor_name: "Northwind Supplies Ltd",
    invoice_number: "INV-2026-0431",
    invoice_date: "2026-08-21",
    currency: "GBP",
    line_items: [
      { description: "Managed hosting, August", quantity: 1, unit_price: "840.00" },
      { description: "Support hours", quantity: 6, unit_price: "95.00" },
    ],
    subtotal: "1410.00",
    tax: "282.00",
    total: "1692.00",
  },
  null,
  2,
);

function SubmitPanel({ onSubmitted }: { onSubmitted: () => void }) {
  const [content, setContent] = useState(SAMPLE_INVOICE);
  const [sourceReference, setSourceReference] = useState("inbox@tally.example");
  const [simulate, setSimulate] = useState("random");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const document = await api.submitDocument({
        content,
        source_reference: sourceReference,
        simulate,
      });
      setNotice(
        document.duplicate
          ? `Already had this exact document (${document.id.slice(0, 8)}); the duplicate was ignored.`
          : `Queued ${document.id.slice(0, 8)} for processing.`,
      );
      onSubmitted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Submit a document</h2>
      {error && <div className="error-box">{error}</div>}
      {notice && <div className="notice-box">{notice}</div>}

      <label htmlFor="source">Source reference</label>
      <input
        id="source"
        value={sourceReference}
        onChange={(e) => setSourceReference(e.target.value)}
        placeholder="where this document came from"
      />

      <label htmlFor="simulate">Extraction service behaviour</label>
      <select id="simulate" value={simulate} onChange={(e) => setSimulate(e.target.value)}>
        {SIMULATE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <label htmlFor="content">Invoice (JSON or plain text)</label>
      <textarea id="content" value={content} onChange={(e) => setContent(e.target.value)} />

      <div className="row">
        <button type="submit" disabled={busy || content.trim() === ""}>
          {busy ? "Submitting…" : "Submit for processing"}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setContent(SAMPLE_INVOICE)}
          disabled={busy}
        >
          Reset sample
        </button>
      </div>
      <p className="muted small" style={{ marginBottom: 0 }}>
        Submitting identical content twice is a no-op: the second submission collapses onto
        the first document instead of creating a second financial record.
      </p>
    </form>
  );
}

export function DocumentsPage() {
  const { data, error, refresh } = usePolled(() => api.listDocuments(), 2000);

  return (
    <div className="grid">
      <SubmitPanel onSubmitted={refresh} />

      <div className="panel">
        <h2>Documents</h2>
        {error && <div className="error-box">{error}</div>}
        {!data && <p className="muted small">Loading…</p>}
        {data && data.results.length === 0 && (
          <p className="muted small">Nothing submitted yet.</p>
        )}
        {data && data.results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Received</th>
                <th>Status</th>
                <th>Vendor / invoice</th>
                <th style={{ textAlign: "right" }}>Total</th>
                <th style={{ textAlign: "right" }}>Attempts</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.results.map((document) => (
                <tr key={document.id}>
                  <td className="mono muted">{formatTime(document.created_at)}</td>
                  <td>
                    <StatusBadge status={document.status} />
                    {document.review_reasons.length > 0 && (
                      <div className="muted small" style={{ marginTop: 4 }}>
                        {document.review_reasons[0]}
                      </div>
                    )}
                  </td>
                  <td>
                    {document.vendor_name ?? <span className="muted">unknown vendor</span>}
                    <div className="muted small mono">
                      {document.invoice_number ?? "no invoice number"}
                    </div>
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {document.total ? `${document.currency ?? ""} ${document.total}` : "—"}
                  </td>
                  <td className="mono" style={{ textAlign: "right" }}>
                    {document.attempts}
                  </td>
                  <td style={{ textAlign: "right" }}>
                    <Link to={`/documents/${document.id}`}>inspect</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
