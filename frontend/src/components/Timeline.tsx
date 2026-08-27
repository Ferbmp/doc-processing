import {
  BanIcon,
  CircleCheckIcon,
  CopyIcon,
  InboxIcon,
  LifeBuoyIcon,
  ListPlusIcon,
  OctagonXIcon,
  PlayIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  SparklesIcon,
  TriangleAlertIcon,
} from "lucide-react";

import type { AuditEvent } from "@/api";
import { formatTime } from "@/hooks";
import { cn } from "@/lib/utils";

type Tone = { className: string; Icon: typeof InboxIcon };

const NEUTRAL: Tone = { className: "border-border bg-muted text-muted-foreground", Icon: ListPlusIcon };
const INFO = "border-sky-500/30 bg-sky-500/10 text-sky-300";
const GOOD = "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
const WARN = "border-amber-500/30 bg-amber-500/10 text-amber-300";
const BAD = "border-rose-500/30 bg-rose-500/10 text-rose-300";
const RETRY = "border-violet-500/30 bg-violet-500/10 text-violet-300";

const TONES: Record<string, Tone> = {
  document_received: { className: INFO, Icon: InboxIcon },
  job_enqueued: NEUTRAL,
  processing_started: { className: INFO, Icon: PlayIcon },
  extraction_succeeded: { className: GOOD, Icon: SparklesIcon },
  result_accepted: { className: GOOD, Icon: CircleCheckIcon },
  review_approved: { className: GOOD, Icon: ShieldCheckIcon },
  attempt_failed: { className: BAD, Icon: OctagonXIcon },
  processing_failed: { className: BAD, Icon: OctagonXIcon },
  review_rejected: { className: BAD, Icon: BanIcon },
  retry_scheduled: { className: RETRY, Icon: RefreshCwIcon },
  manual_retry_requested: { className: RETRY, Icon: RotateCcwIcon },
  review_required: { className: WARN, Icon: TriangleAlertIcon },
  duplicate_submission_ignored: { className: WARN, Icon: CopyIcon },
  duplicate_execution_ignored: { className: WARN, Icon: ShieldAlertIcon },
  job_recovered: { className: WARN, Icon: LifeBuoyIcon },
};

export function Timeline({ events }: { events: AuditEvent[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-muted-foreground">No events recorded yet.</p>;
  }

  return (
    <ol>
      {events.map((event, index) => {
        const tone = TONES[event.event_type] ?? NEUTRAL;
        const { Icon } = tone;
        const isLast = index === events.length - 1;

        return (
          <li key={event.id} className={cn("relative flex gap-3", !isLast && "pb-5")}>
            {!isLast && (
              <span
                aria-hidden
                className="absolute top-7 bottom-0 left-[13px] w-px bg-border"
              />
            )}
            <span
              className={cn(
                "relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border",
                tone.className,
              )}
            >
              <Icon className="size-3.5" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-sm font-medium">{event.event_label}</span>
                <span className="font-mono text-xs text-muted-foreground tabular-nums">
                  {formatTime(event.created_at)}
                </span>
                {event.attempt !== null && (
                  <span className="text-xs text-muted-foreground">attempt {event.attempt}</span>
                )}
                {event.actor && (
                  <span className="truncate font-mono text-xs text-muted-foreground/70">
                    {event.actor}
                  </span>
                )}
              </div>
              <p className="mt-0.5 text-sm break-words text-muted-foreground">{event.message}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
