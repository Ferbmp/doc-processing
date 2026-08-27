import { ArrowLeftIcon, BanIcon, CheckIcon, ChevronRightIcon, RotateCcwIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { ApiError, api, type DocumentDetail, type ExtractionResult } from "@/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Timeline } from "@/components/Timeline";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, usePolled } from "@/hooks";
import { cn } from "@/lib/utils";

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
  const fields = {} as Record<CorrectableField, string>;
  for (const [name] of CORRECTABLE) {
    const value = result ? (result[name] as string | null) : null;
    fields[name] = value ?? "";
  }
  return fields;
}

function Disclosure({
  label,
  className,
  children,
}: {
  label: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Collapsible className={cn("group/disclosure rounded-lg border", className)}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm font-medium hover:bg-muted/40"
        >
          <ChevronRightIcon className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/disclosure:rotate-90" />
          {label}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t p-3">{children}</CollapsibleContent>
    </Collapsible>
  );
}

function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-md bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap">
      {children}
    </pre>
  );
}

function Field({
  label,
  value,
  missing = "missing",
  mono = true,
}: {
  label: string;
  value: string | null;
  missing?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 truncate text-sm", mono && "font-mono tabular-nums")}>
        {value ?? <span className="text-muted-foreground/60 italic">{missing}</span>}
      </div>
    </div>
  );
}

function ResultCard({ result }: { result: ExtractionResult }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Extracted financial record</CardTitle>
        <CardDescription>Written on attempt {result.attempt}.</CardDescription>
        <CardAction>
          <span
            className={cn(
              "font-mono text-sm tabular-nums",
              result.confidence >= 0.9
                ? "text-emerald-300"
                : result.confidence >= 0.75
                  ? "text-amber-300"
                  : "text-rose-300",
            )}
          >
            {(result.confidence * 100).toFixed(1)}% confidence
          </span>
        </CardAction>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Field label="Vendor" value={result.vendor_name} mono={false} />
          <Field label="Invoice number" value={result.invoice_number} />
          <Field label="Invoice date" value={result.invoice_date} />
          <Field label="Currency" value={result.currency} />
          <Field label="Subtotal" value={result.subtotal} />
          <Field label="Tax" value={result.tax} />
          <Field label="Total" value={result.total} missing="withheld" />
        </div>

        {result.review_reasons.length > 0 && (
          <Alert className="border-amber-500/30 bg-amber-500/5 text-amber-100">
            <AlertTitle>Why this needs a human</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-0.5 pl-4 text-amber-200/80">
                {result.review_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {result.reviewed_at && (
          <p className="text-xs text-muted-foreground">
            {result.review_action === "approve" ? "Approved" : "Rejected"} by{" "}
            <span className="font-mono">{result.reviewed_by}</span> on{" "}
            {formatDateTime(result.reviewed_at)}
            {result.review_notes ? ` — ${result.review_notes}` : ""}
          </p>
        )}

        {result.line_items.length > 0 && (
          <Disclosure label={`${result.line_items.length} line item(s)`}>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit price</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.line_items.map((item, index) => (
                  <TableRow key={index}>
                    <TableCell className="whitespace-normal">{item.description}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {item.quantity ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {item.unit_price ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {item.amount ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Disclosure>
        )}

        <Disclosure label="Raw extraction service response">
          <CodeBlock>{JSON.stringify(result.raw_extraction, null, 2)}</CodeBlock>
        </Disclosure>
      </CardContent>
    </Card>
  );
}

function ActionsCard({
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
    <Card className="ring-amber-500/25">
      <CardHeader>
        <CardTitle>{canReview ? "Human review" : "Recovery"}</CardTitle>
        <CardDescription>
          {canReview
            ? "Correct the figures if needed, then accept or reject the record."
            : "This document exhausted its attempts and is waiting for a decision."}
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertTitle>{error}</AlertTitle>
            {details.length > 0 && (
              <AlertDescription>
                <ul className="list-disc space-y-0.5 pl-4">
                  {details.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </AlertDescription>
            )}
          </Alert>
        )}

        {canRetry && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Retrying resets the attempt budget and queues a fresh job. Nothing is
              re-processed unless this document is still undecided.
            </p>
            <Button disabled={busy} onClick={() => run(() => api.retryDocument(document.id))}>
              <RotateCcwIcon />
              {busy ? "Queueing…" : "Retry processing"}
            </Button>
          </div>
        )}

        {canReview && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="reviewer">Reviewer</Label>
                <Input
                  id="reviewer"
                  value={reviewer}
                  onChange={(event) => setReviewer(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="notes">Notes</Label>
                <Input
                  id="notes"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  placeholder="optional"
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label>Corrections</Label>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {CORRECTABLE.map(([name, label]) => (
                  <div key={name} className="space-y-1.5">
                    <Label
                      htmlFor={`field-${name}`}
                      className="text-xs font-normal text-muted-foreground"
                    >
                      {label}
                    </Label>
                    <Input
                      id={`field-${name}`}
                      value={fields[name]}
                      onChange={(event) =>
                        setFields({ ...fields, [name]: event.target.value })
                      }
                      className={cn(
                        "font-mono text-xs",
                        fields[name] !== original[name] && "border-amber-500/50",
                      )}
                    />
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy}
                className="bg-emerald-600 text-white hover:bg-emerald-600/85"
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
                <CheckIcon />
                {busy ? "Working…" : "Approve and accept"}
              </Button>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api.reviewDocument(document.id, { action: "reject", reviewer, notes }),
                  )
                }
              >
                <BanIcon />
                Reject
              </Button>
            </div>

            <p className="text-xs text-muted-foreground">
              Approving re-runs the same completeness and arithmetic checks that blocked
              auto-acceptance, and the database still refuses a second accepted record for
              the same vendor and invoice number.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

const JOB_STATUS_CLASS: Record<string, string> = {
  queued: "text-muted-foreground",
  running: "text-sky-300",
  succeeded: "text-emerald-300",
  failed: "text-rose-300",
};

function JobsCard({ jobs }: { jobs: DocumentDetail["jobs"] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Attempts</CardTitle>
        <CardDescription>
          One row per queued job, including retries and recovered work.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-20">Attempt</TableHead>
              <TableHead className="w-24">Job status</TableHead>
              <TableHead className="w-40">Worker</TableHead>
              <TableHead className="w-44">Runs after</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow key={job.id}>
                <TableCell className="align-top font-mono tabular-nums">
                  {job.attempt} / {job.max_attempts}
                </TableCell>
                <TableCell
                  className={cn("align-top font-mono", JOB_STATUS_CLASS[job.status])}
                >
                  {job.status}
                </TableCell>
                <TableCell className="align-top font-mono text-xs break-all whitespace-normal text-muted-foreground">
                  {job.locked_by || "—"}
                </TableCell>
                <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
                  {formatDateTime(job.run_after)}
                </TableCell>
                <TableCell className="align-top text-xs whitespace-normal">
                  {job.error_type ? (
                    <>
                      <div className="font-mono text-rose-300">{job.error_type}</div>
                      <div className="break-words text-muted-foreground">
                        {job.error_message}
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export function DocumentDetailPage() {
  const { id = "" } = useParams();
  const { data, error, setData } = usePolled(() => api.getDocument(id), 2000, id);

  if (error) {
    return (
      <div className="space-y-4">
        <Alert variant="destructive">
          <AlertTitle>Could not load this document</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
        <Button asChild variant="outline">
          <Link to="/">
            <ArrowLeftIcon />
            All documents
          </Link>
        </Button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            <StatusBadge status={data.status} />
            <span className="font-mono text-xs text-muted-foreground">{data.id}</span>
          </CardTitle>
          <CardDescription>
            {data.source_reference || "no source reference"} · received{" "}
            {formatDateTime(data.created_at)} · {data.attempts} attempt(s) · simulated
            behaviour: {data.forced_outcome || "random"}
          </CardDescription>
          <CardAction>
            <Button asChild variant="ghost" size="sm">
              <Link to="/">
                <ArrowLeftIcon />
                All documents
              </Link>
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent>
          <Disclosure label={`Submitted content (${data.input_format})`}>
            <CodeBlock>{data.raw_text}</CodeBlock>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              content hash {data.content_hash}
            </p>
          </Disclosure>
        </CardContent>
      </Card>

      <ActionsCard document={data} onChanged={setData} />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
        <div className="space-y-6">
          {data.result ? (
            <ResultCard result={data.result} />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>Extracted financial record</CardTitle>
                <CardDescription>
                  No record has been written yet. Nothing is stored until an attempt
                  succeeds, so a failed extraction leaves no partial financial data behind.
                </CardDescription>
              </CardHeader>
            </Card>
          )}

          <JobsCard jobs={data.jobs} />
        </div>

        <Card className="xl:sticky xl:top-24">
          <CardHeader>
            <CardTitle>What happened</CardTitle>
            <CardDescription>Append-only audit trail.</CardDescription>
          </CardHeader>
          <CardContent>
            <Timeline events={data.events} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
