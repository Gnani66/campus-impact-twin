"use client";

import {
  AlertTriangle,
  Boxes,
  Building2,
  Cpu,
  Flame,
  Grid2x2,
} from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import type { IncidentSummary } from "@/lib/types";
import type { TwinEntity } from "@/lib/twin-state";

import { formatAge } from "@/lib/status";

/**
 * The metric row.
 *
 * EVERY NUMBER HERE HAS A SOURCE, and the source is named in the
 * tile's own tooltip.
 *
 * Nothing is derived to look impressive. There is no "12% better
 * than yesterday" on this row, because the API exposes no
 * comparison to make that honestly - a percentage with no baseline
 * is decoration that reads as analysis. Where a count would be
 * misleading the tile says so instead of showing a number.
 */

export interface CampusStructure {
  buildings: number;
  zones: number;
  sensors: number;
  equipment: number;
}

interface CampusMetricsProps {
  entities: TwinEntity[];
  summary: IncidentSummary | null;
  structure: CampusStructure | null;
  lastUpdated: string | null;
  loading: boolean;
}

export function CampusMetrics({
  entities,
  summary,
  structure,
  lastUpdated,
  loading,
}: CampusMetricsProps) {
  const needingAttention = entities.filter(
    (entity) => entity.status !== "normal",
  ).length;

  const criticalEntities = entities.filter(
    (entity) => entity.status === "critical",
  ).length;

  return (
    <section
      aria-label="Campus at a glance"
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6"
    >
      <Tile
        icon={Building2}
        label="Buildings"
        value={structure?.buildings ?? null}
        loading={loading && !structure}
        hint="From the campus record: how many buildings the twin is built from."
      />

      <Tile
        icon={Grid2x2}
        label="Zones"
        value={structure?.zones ?? null}
        loading={loading && !structure}
        hint="Rooms and spaces that carry sensors and can hold an incident."
      />

      <Tile
        icon={Cpu}
        label="Sensors"
        value={structure?.sensors ?? null}
        loading={loading && !structure}
        hint="Registered sensors. The API reports which of them are reporting as part of each entity's metrics, not as a separate health list."
      />

      <Tile
        icon={AlertTriangle}
        label="Open alerts"
        value={summary?.open_incidents ?? null}
        loading={loading && !summary}
        tone={
          summary && summary.open_incidents > 0
            ? "warning"
            : undefined
        }
        hint="Incidents that are open, acknowledged or under investigation. Counted by the backend."
      />

      <Tile
        icon={Flame}
        label="Critical issues"
        value={summary?.critical ?? null}
        loading={loading && !summary}
        tone={
          summary && summary.critical > 0 ? "critical" : undefined
        }
        hint="Incidents ever raised at critical severity. Includes ones since resolved, because the summary is a lifetime count."
      />

      <Tile
        icon={Boxes}
        label="Need attention"
        value={loading && !entities.length ? null : needingAttention}
        loading={loading && !entities.length}
        tone={needingAttention > 0 ? "warning" : undefined}
        hint="Entities in the twin whose current state is warning, critical or offline. Offline counts here, because not knowing is not the same as healthy."
        footer={
          criticalEntities > 0
            ? `${criticalEntities} critical`
            : undefined
        }
        updated={lastUpdated}
      />
    </section>
  );
}

function Tile({
  icon: Icon,
  label,
  value,
  hint,
  footer,
  tone,
  loading,
  updated,
}: {
  icon: React.ComponentType<{
    className?: string;
    "aria-hidden"?: boolean;
  }>;
  label: string;
  value: number | null;
  hint: string;
  footer?: string;
  tone?: "warning" | "critical";
  loading?: boolean;
  updated?: string | null;
}) {
  const valueTone =
    tone === "critical"
      ? "text-critical"
      : tone === "warning"
        ? "text-warning"
        : "text-foreground";

  return (
    <Tooltip>
      {/*
        Base UI composes through `render`, so the card *is* the
        trigger. Wrapping it in an extra element would have put a
        `<span>` between the button role and its content.
      */}
      <TooltipTrigger
        render={
          <div className="rounded-xl border bg-card p-4 transition-colors hover:border-foreground/20" />
        }
      >
        <div className="flex items-center gap-2">
          <Icon
            aria-hidden
            className="size-3.5 text-muted-foreground"
          />

          <p className="truncate text-xs font-medium text-muted-foreground">
            {label}
          </p>
        </div>

        {loading ? (
          <Skeleton className="mt-2.5 h-7 w-10" />
        ) : (
          <p
            className={`tabular mt-1.5 text-2xl font-semibold ${valueTone}`}
          >
            {value === null ? "—" : value}
          </p>
        )}

        {(footer || updated) && (
          <p className="mt-1 truncate text-[11px] text-muted-foreground">
            {footer ??
              (updated ? formatAge(updated) : undefined)}
          </p>
        )}
      </TooltipTrigger>

      <TooltipContent
        side="top"
        className="max-w-64 text-xs"
      >
        {hint}
      </TooltipContent>
    </Tooltip>
  );
}
