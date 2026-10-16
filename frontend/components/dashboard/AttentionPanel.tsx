"use client";

import Link from "next/link";
import { ArrowUpRight, Users } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import type { Incident } from "@/lib/types";
import type { TwinEntity } from "@/lib/twin-state";

import {
  describeSeverity,
  formatAge,
} from "@/lib/status";

/**
 * What needs attention.
 *
 * SORTED BY OPERATIONAL IMPACT, NOT BY SENSOR VALUE.
 *
 * A CO₂ reading of 1900 ppm matters enormously in a lecture hall
 * with 400 people and barely at all in an empty store room. The
 * backend already computes that - `impact_score` is a function of
 * severity and how many people are affected - so this panel sorts
 * by it and never re-derives a ranking of its own.
 *
 * "91 occupants affected" is read from the same twin snapshot that
 * draws the model, not estimated here.
 */

interface AttentionPanelProps {
  incidents: Incident[];
  entities: TwinEntity[];
  loading: boolean;
}

const MAX_ROWS = 6;

export function AttentionPanel({
  incidents,
  entities,
  loading,
}: AttentionPanelProps) {
  const occupancyByZone = new Map<string, number | null>();

  for (const entity of entities) {
    occupancyByZone.set(
      entity.zone_id,
      entity.metrics.occupancy,
    );
  }

  // The API returns most severe first; taking the head keeps that
  // ordering rather than re-sorting a list that is already right.
  const rows = incidents.slice(0, MAX_ROWS);

  const remaining = incidents.length - rows.length;

  return (
    <section className="flex h-full flex-col rounded-xl border bg-card">
      <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">
            What needs attention
          </h2>

          <p className="text-xs text-muted-foreground">
            Ranked by operational impact
          </p>
        </div>

        <Button
          variant="ghost"
          size="sm"
          render={<Link href="/incidents" />}
        >
          All incidents
          <ArrowUpRight
            aria-hidden
            className="size-3.5"
          />
        </Button>
      </header>

      <div className="flex-1 p-2">
        {loading && !incidents.length ? (
          <div className="space-y-2 p-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        ) : rows.length === 0 ? (
          <div className="px-2 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              Nothing needs attention.
            </p>

            <p className="mt-1 text-xs text-muted-foreground/80">
              No incident is open on this campus.
            </p>
          </div>
        ) : (
          <ul className="divide-y">
            {rows.map((incident) => (
              <Row
                key={incident.id}
                incident={incident}
                occupants={occupancyByZone.get(
                  incident.zone_id ?? "",
                )}
              />
            ))}
          </ul>
        )}
      </div>

      {remaining > 0 && (
        <p className="border-t px-4 py-2.5 text-xs text-muted-foreground">
          {remaining} more below the top{" "}
          {MAX_ROWS}
        </p>
      )}
    </section>
  );
}

function Row({
  incident,
  occupants,
}: {
  incident: Incident;
  occupants: number | null | undefined;
}) {
  const severity = describeSeverity(incident.severity);

  // Null means nobody is counting, which is not the same as an
  // empty room. The affected figure is omitted rather than shown
  // as zero.
  const affected =
    typeof occupants === "number" && occupants > 0
      ? occupants
      : null;

  return (
    <li>
      <Link
        href={`/incidents?incident=${encodeURIComponent(incident.id)}`}
        className="flex items-start gap-3 rounded-lg px-2 py-3 transition-colors hover:bg-muted/60 focus-visible:bg-muted/60"
      >
        <Badge
          variant="outline"
          className={`mt-0.5 shrink-0 px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase ${severity.surface}`}
        >
          {severity.label}
        </Badge>

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {incident.zone_code ??
              incident.title}
          </p>

          <p className="truncate text-xs text-muted-foreground">
            {incident.title}
          </p>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Users
                aria-hidden
                className="size-3"
              />

              {affected === null
                ? "occupancy not measured"
                : `${affected.toLocaleString()} affected`}
            </span>

            <span>
              impact{" "}
              <span className="tabular">
                {Math.round(incident.impact_score)}
              </span>
              /100
            </span>

            <span>
              {formatAge(incident.detected_at)}
            </span>
          </div>
        </div>

        <ArrowUpRight
          aria-hidden
          className="mt-1 size-3.5 shrink-0 text-muted-foreground"
        />
      </Link>
    </li>
  );
}
