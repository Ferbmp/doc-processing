import {
  BanIcon,
  CircleCheckIcon,
  ClockIcon,
  InboxIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";

import type { DocumentStatus } from "@/api";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type Meta = {
  label: string;
  className: string;
  Icon: typeof InboxIcon;
  spin?: boolean;
};

const STATUS: Record<DocumentStatus, Meta> = {
  received: {
    label: "Received",
    className: "border-border bg-muted text-muted-foreground",
    Icon: InboxIcon,
  },
  processing: {
    label: "Processing",
    className: "border-sky-500/30 bg-sky-500/10 text-sky-300",
    Icon: Loader2Icon,
    spin: true,
  },
  retry_scheduled: {
    label: "Retry scheduled",
    className: "border-violet-500/30 bg-violet-500/10 text-violet-300",
    Icon: ClockIcon,
  },
  review_required: {
    label: "Review required",
    className: "border-amber-500/30 bg-amber-500/10 text-amber-300",
    Icon: TriangleAlertIcon,
  },
  completed: {
    label: "Completed",
    className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
    Icon: CircleCheckIcon,
  },
  rejected: {
    label: "Rejected",
    className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    Icon: BanIcon,
  },
  failed: {
    label: "Failed",
    className: "border-rose-500/30 bg-rose-500/10 text-rose-300",
    Icon: OctagonXIcon,
  },
};

export function StatusBadge({
  status,
  className,
}: {
  status: DocumentStatus;
  className?: string;
}) {
  const meta = STATUS[status];
  if (!meta) return <Badge variant="outline">{status}</Badge>;

  const { Icon } = meta;
  return (
    <Badge variant="outline" className={cn("gap-1.5", meta.className, className)}>
      <Icon className={cn("size-3", meta.spin && "animate-spin")} />
      {meta.label}
    </Badge>
  );
}
