import { ChevronRightIcon, RotateCcwIcon, SendIcon } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { ApiError, SIMULATE_OPTIONS, api, type DocumentSummary } from "@/api";
import { StatusBadge } from "@/components/StatusBadge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { formatTime, usePolled } from "@/hooks";

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

const DEFAULT_SOURCE = "inbox@tally.example";
const DEFAULT_SIMULATE = "random";

function SubmitCard({ onSubmitted }: { onSubmitted: () => void }) {
  const [content, setContent] = useState(SAMPLE_INVOICE);
  const [sourceReference, setSourceReference] = useState(DEFAULT_SOURCE);
  const [simulate, setSimulate] = useState(DEFAULT_SIMULATE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isDirty =
    content !== SAMPLE_INVOICE ||
    sourceReference !== DEFAULT_SOURCE ||
    simulate !== DEFAULT_SIMULATE ||
    error !== null;

  function resetForm() {
    setContent(SAMPLE_INVOICE);
    setSourceReference(DEFAULT_SOURCE);
    setSimulate(DEFAULT_SIMULATE);
    setError(null);
    toast.message("Form reset", {
      description: "Sample invoice and default options restored.",
    });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const document = await api.submitDocument({
        content,
        source_reference: sourceReference,
        simulate,
      });
      const shortId = document.id.slice(0, 8);
      if (document.duplicate) {
        toast.warning("Duplicate submission ignored", {
          description: `Identical content already exists as ${shortId}.`,
        });
      } else {
        toast.success("Queued for processing", { description: `Document ${shortId}.` });
      }
      onSubmitted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Card>
        <CardHeader>
          <CardTitle>Submit a document</CardTitle>
          <CardDescription>JSON or plain text representing an invoice.</CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Submission rejected</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="source">Source reference</Label>
            <Input
              id="source"
              value={sourceReference}
              onChange={(event) => setSourceReference(event.target.value)}
              placeholder="where this document came from"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="simulate">Extraction service behaviour</Label>
            <Select value={simulate} onValueChange={setSimulate}>
              <SelectTrigger id="simulate" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SIMULATE_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              Test hook only: it pins the simulated AI service to one outcome so every path
              is reachable on demand.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="content">Invoice</Label>
            <Textarea
              id="content"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              spellCheck={false}
              className="min-h-56 font-mono text-xs"
            />
          </div>
        </CardContent>

        <CardFooter className="flex-col items-stretch gap-3 pb-(--card-spacing)">
          <div className="flex gap-2">
            <Button type="submit" disabled={busy || content.trim() === ""} className="flex-1">
              <SendIcon />
              {busy ? "Submitting…" : "Submit for processing"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={resetForm}
              disabled={busy || !isDirty}
            >
              <RotateCcwIcon />
              Reset
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Submitting identical content twice is a no-op: the second submission collapses
            onto the first document instead of creating a second financial record.
          </p>
        </CardFooter>
      </Card>
    </form>
  );
}

function DocumentsTable({ documents }: { documents: DocumentSummary[] }) {
  const navigate = useNavigate();

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-20">Received</TableHead>
          <TableHead className="w-56">Status</TableHead>
          <TableHead>Vendor / invoice</TableHead>
          <TableHead className="w-32 text-right">Total</TableHead>
          <TableHead className="w-16 text-right">Attempts</TableHead>
          <TableHead className="w-8" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {documents.map((document) => (
          <TableRow
            key={document.id}
            onClick={() => navigate(`/documents/${document.id}`)}
            className="cursor-pointer"
          >
            <TableCell className="align-top font-mono text-xs text-muted-foreground tabular-nums">
              {formatTime(document.created_at)}
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              <StatusBadge status={document.status} />
              {document.review_reasons.length > 0 && (
                <p className="mt-1 line-clamp-2 text-xs break-words text-muted-foreground">
                  {document.review_reasons[0]}
                </p>
              )}
            </TableCell>
            <TableCell className="align-top whitespace-normal">
              <div className="break-words">
                {document.vendor_name ?? (
                  <span className="text-muted-foreground">unknown vendor</span>
                )}
              </div>
              <div className="font-mono text-xs break-all text-muted-foreground">
                {document.invoice_number ?? "no invoice number"}
              </div>
            </TableCell>
            <TableCell className="align-top text-right font-mono tabular-nums">
              {document.total ? `${document.currency ?? ""} ${document.total}` : "—"}
            </TableCell>
            <TableCell className="align-top text-right font-mono tabular-nums">
              {document.attempts}
            </TableCell>
            <TableCell className="align-top">
              <Link
                to={`/documents/${document.id}`}
                aria-label="Inspect document"
                className="text-muted-foreground hover:text-foreground"
              >
                <ChevronRightIcon className="size-4" />
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function DocumentsPage() {
  const { data, error, refresh } = usePolled(() => api.listDocuments(), 2000);

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)]">
      <SubmitCard onSubmitted={refresh} />

      <Card>
        <CardHeader>
          <CardTitle>Documents</CardTitle>
          <CardDescription>Newest first, refreshed every two seconds.</CardDescription>
        </CardHeader>
        <CardContent>
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Could not load documents</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {!error && !data && (
            <div className="space-y-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-11 w-full" />
              ))}
            </div>
          )}

          {data && data.results.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              Nothing submitted yet. Send an invoice using the form.
            </p>
          )}

          {data && data.results.length > 0 && <DocumentsTable documents={data.results} />}
        </CardContent>
      </Card>
    </div>
  );
}
