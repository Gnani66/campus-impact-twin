"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  MapPin,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

import type { TwinEntity } from "@/lib/twin-state";

import {
  METRICS,
  formatAge,
  formatMetric,
  statusBadgeClass,
  describeStatus,
} from "@/lib/status";

/**
 * The entity detail panel.
 *
 * Opens from a click in the 3D model, and shows only what the
 * backend already decided. A metric this deployment does not
 * measure reads "—" with the reason in the tooltip: six honest
 * dashes are more useful than one invented number, and an operator
 * acting on a fabricated AQI has no way to tell it was fabricated.
 *
 * The panel stays live: the entity passed in re-renders with each
 * poll, so a reading that crosses a threshold while the panel is
 * open updates in place rather than freezing.
 */

interface EntityDetailSheetProps {
  entity: TwinEntity | null;
  onClose: () => void;
}

export function EntityDetailSheet({
  entity,
  onClose,
}: EntityDetailSheetProps) {
  return (
    <Sheet
      open={entity !== null}
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
    >
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        {entity && (
          <>
            <SheetHeader>
              <div className="flex items-center gap-2">
                <Badge
                  variant="outline"
                  className={`text-[10px] font-semibold tracking-wide uppercase ${statusBadgeClass(entity.status)}`}
                >
                  {describeStatus(entity.status).label}
                </Badge>

                <span className="text-xs text-muted-foreground">
                  {entity.code}
                </span>
              </div>

              <SheetTitle className="text-lg">
                {entity.name}
              </SheetTitle>

              <SheetDescription className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <MapPin
                    aria-hidden
                    className="size-3"
                  />
                  {entity.type.replace(/_/g, " ")}
                </span>

                <span>
                  Last reading{" "}
                  {formatAge(entity.observedAt)}
                </span>
              </SheetDescription>
            </SheetHeader>

            <div className="px-4 pb-8">
              <p className="text-xs text-muted-foreground">
                {describeStatus(entity.status).description}
              </p>

              <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-5">
                {METRICS.map((metric) => {
                  const value = (
                    entity.metrics as unknown as Record<
                      string,
                      number | null
                    >
                  )[metric.key];

                  const formatted = formatMetric(
                    value,
                    metric.unit,
                  );

                  return (
                    <div key={metric.key}>
                      <dt className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                        {metric.label}
                      </dt>

                      <dd
                        className={`tabular mt-1 text-lg font-semibold ${
                          formatted.measured
                            ? "text-foreground"
                            : "text-muted-foreground/60"
                        }`}
                        title={metric.hint}
                      >
                        {formatted.text}
                      </dd>
                    </div>
                  );
                })}
              </dl>

              {entity.reasons.length > 0 && (
                <>
                  <Separator className="my-5" />

                  <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                    Why it holds this status
                  </h3>

                  <ul className="mt-2 space-y-1.5">
                    {entity.reasons.map((reason) => (
                      <li
                        key={reason}
                        className="flex gap-2 text-sm"
                      >
                        <span
                          aria-hidden
                          className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground/50"
                        />

                        {reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {entity.activeIssues.length > 0 && (
                <>
                  <Separator className="my-5" />

                  <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                    Active incidents
                    <span className="tabular ml-1.5 text-foreground">
                      {entity.openIncidentCount}
                    </span>
                  </h3>

                  <ul className="mt-2 space-y-1.5">
                    {entity.activeIssues.map((issue) => (
                      <li
                        key={issue}
                        className="flex gap-2 text-sm"
                      >
                        <span
                          aria-hidden
                          className="mt-2 size-1 shrink-0 rounded-full bg-warning"
                        />

                        {issue}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {entity.pendingApprovals > 0 && (
                <div className="mt-5 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2.5">
                  <p className="text-xs text-warning">
                    <span className="tabular font-semibold">
                      {entity.pendingApprovals}
                    </span>{" "}
                    {entity.pendingApprovals === 1
                      ? "recommendation"
                      : "recommendations"}{" "}
                    waiting on a person. Nothing has been changed
                    on the campus.
                  </p>
                </div>
              )}

              <Separator className="my-5" />

              <div className="flex flex-col gap-2">
                <Button
                  className="w-full"
                  render={<a href="/digital-twin" />}
                >
                  Open details
                  <ArrowUpRight
                    aria-hidden
                    className="size-4"
                  />
                </Button>

                <Button
                  variant="outline"
                  className="w-full"
                  render={
                    <Link
                      href={`/copilot?entity=${encodeURIComponent(entity.id)}`}
                    />
                  }
                >
                  <Sparkles
                    aria-hidden
                    className="size-4"
                  />
                  Ask the copilot why
                </Button>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
