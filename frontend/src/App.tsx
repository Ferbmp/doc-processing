import { Link, Route, Routes } from "react-router-dom";

import { api } from "@/api";
import { Skeleton } from "@/components/ui/skeleton";
import { Toaster } from "@/components/ui/sonner";
import { usePolled } from "@/hooks";
import { cn } from "@/lib/utils";
import { DocumentDetailPage } from "@/pages/DocumentDetailPage";
import { DocumentsPage } from "@/pages/DocumentsPage";

function Stat({
  label,
  value,
  className,
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className="rounded-lg border bg-card px-3 py-1.5">
      <div className="text-[11px] leading-none tracking-wide text-muted-foreground uppercase">
        {label}
      </div>
      <div className={cn("mt-1 font-mono text-sm leading-none tabular-nums", className)}>
        {value}
      </div>
    </div>
  );
}

function StatStrip() {
  const { data } = usePolled(() => api.stats(), 2000);

  if (!data) {
    return (
      <div className="flex gap-2">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-[46px] w-20" />
        ))}
      </div>
    );
  }

  const s = data.by_status;
  return (
    <div className="flex flex-wrap gap-2">
      <Stat label="Documents" value={data.total} />
      <Stat label="In flight" value={s.received + s.processing + s.retry_scheduled} />
      <Stat label="Review" value={s.review_required} className="text-amber-300" />
      <Stat label="Completed" value={s.completed} className="text-emerald-300" />
      <Stat label="Failed" value={s.failed + s.rejected} className="text-rose-300" />
      <Stat label="Jobs due" value={data.jobs_due} />
    </div>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-3.5">
          <div>
            <h1 className="font-heading text-base font-semibold tracking-tight">
              <Link to="/" className="hover:underline">
                Tally <span className="text-muted-foreground">·</span> document processing
              </Link>
            </h1>
            <p className="text-xs text-muted-foreground">
              Submit an invoice, watch it move through the pipeline, inspect what happened.
            </p>
          </div>
          <StatStrip />
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        <Routes>
          <Route path="/" element={<DocumentsPage />} />
          <Route path="/documents/:id" element={<DocumentDetailPage />} />
        </Routes>
      </main>

      <Toaster theme="dark" position="bottom-right" />
    </div>
  );
}
