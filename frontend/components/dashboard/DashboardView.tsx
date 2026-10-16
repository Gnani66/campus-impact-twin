"use client";

import { AlertCircle, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { greeting } from "@/lib/status";

import { AttentionPanel } from "./AttentionPanel";
import { CampusMetrics } from "./CampusMetrics";
import { CampusTwinPanel } from "./CampusTwinPanel";
import { EntityDetailSheet } from "./EntityDetailSheet";
import { useCampusStructure } from "./useCampusStructure";
import { useDashboardData } from "./useDashboardData";

/**
 * The overview.
 *
 * Answers one question - "what is happening on campus right now?"
 * - in the order an operator asks it: how bad is it, what is it,
 * then what specifically.
 *
 * The 3D model is the centre of the layout rather than a
 * decoration beside it, because the model is the only view where
 * every entity, its state and its sensors are in one picture. The
 * numbers above it are the same data in numbers; the panel to the
 * side is the same data ranked by consequence.
 */

export function DashboardView() {
  const {
    snapshot,
    entities,
    incidents,
    summary,
    lastUpdated,
    loading,
    error,
    stale,
    select,
    selected,
    refresh,
  } = useDashboardData();

  const { structure } = useCampusStructure();

  // Greeting is derived once per mount rather than per render: it
  // depends on the hour, and re-evaluating it on every poll would
  // mean a new string identity for text that has not changed.
  const [hello] = useState(() => greeting());

  return (
    <div className="mx-auto max-w-[1600px] space-y-5 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            {hello}.
          </h2>

          <p className="mt-0.5 text-sm text-muted-foreground">
            Campus operational overview.
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          onClick={refresh}
          className="h-8 gap-1.5 text-xs"
        >
          <RefreshCw
            aria-hidden
            className="size-3.5"
          />
          Refresh
        </Button>
      </header>

      {/*
        A failed refresh is a banner, not a blank screen. The twin
        and the metrics underneath are still the last known truth,
        and saying so is more useful than hiding them.
      */}
      {error && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-critical/30 bg-critical-soft px-3.5 py-2.5"
        >
          <AlertCircle
            aria-hidden
            className="mt-0.5 size-4 shrink-0 text-critical"
          />

          <p className="text-sm text-critical">
            {error}

            {stale && (
              <span className="font-normal">
                {" "}
                Showing the last known state.
              </span>
            )}
          </p>
        </div>
      )}

      <CampusMetrics
        entities={entities}
        summary={summary}
        structure={structure}
        lastUpdated={lastUpdated}
        loading={loading}
      />

      {/*
        The twin takes the full width on small screens and sits
        beside the incident panel from `xl` up. On a laptop the
        model still gets the majority of the width, which is what
        makes it the centrepiece rather than one panel among many.
      */}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="h-[520px] xl:h-[640px]">
          <CampusTwinPanel
            entities={entities}
            counts={snapshot?.counts ?? {}}
            selectedId={selected?.id ?? null}
            onSelect={(entity) =>
              select(entity?.id ?? null)
            }
            loading={loading}
          />
        </div>

        <div className="min-h-[320px] xl:h-[640px]">
          <AttentionPanel
            incidents={incidents}
            entities={entities}
            loading={loading}
          />
        </div>
      </div>

      <EntityDetailSheet
        entity={selected}
        onClose={() => select(null)}
      />
    </div>
  );
}
