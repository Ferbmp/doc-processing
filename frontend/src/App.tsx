import { Link, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { usePolled } from "./hooks";
import { DocumentDetailPage } from "./pages/DocumentDetailPage";
import { DocumentsPage } from "./pages/DocumentsPage";

function StatStrip() {
  const { data } = usePolled(() => api.stats(), 2000);
  if (!data) return <div className="stat-strip muted">loading…</div>;

  const s = data.by_status;
  return (
    <div className="stat-strip">
      <span>
        <b>{data.total}</b> documents
      </span>
      <span>
        in flight{" "}
        <b>{s.received + s.processing + s.retry_scheduled}</b>
      </span>
      <span>
        needs review <b>{s.review_required}</b>
      </span>
      <span>
        completed <b>{s.completed}</b>
      </span>
      <span>
        failed <b>{s.failed}</b>
      </span>
      <span>
        rejected <b>{s.rejected}</b>
      </span>
      <span>
        jobs due <b>{data.jobs_due}</b>
      </span>
    </div>
  );
}

export default function App() {
  return (
    <div className="app">
      <header className="masthead">
        <div>
          <h1>
            <Link to="/" style={{ color: "inherit" }}>
              Tally · document processing
            </Link>
          </h1>
          <div className="sub">
            Submit an invoice, watch it move through the pipeline, inspect what happened.
          </div>
        </div>
        <StatStrip />
      </header>

      <Routes>
        <Route path="/" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailPage />} />
      </Routes>
    </div>
  );
}
