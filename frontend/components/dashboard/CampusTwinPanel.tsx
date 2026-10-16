"use client";

import { Suspense } from "react";

import dynamic from "next/dynamic";

import { Maximize2, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

import type { TwinEntity } from "@/lib/twin-state";

import { STATUS_DESCRIPTORS } from "@/lib/status";
import type { TwinStatus } from "@/lib/twin-state";

/**
 * The 3D campus, as the centre of the dashboard.
 *
 * LAZY, AND ONLY ON THE CLIENT.
 *
 * Three.js touches `window` when it is imported, so a server render
 * of this component throws on a module that is perfectly valid in a
 * browser. `ssr: false` is not a workaround here, it is the only
 * correct arrangement.
 *
 * It is also the heaviest thing on the page by a wide margin - a
 * 260 MB model and a WebGL context - so it is code-split and only
 * mounted once the dashboard is on screen. The metrics and the
 * incident panel render immediately and do not wait for it.
 */

const CampusScene = dynamic(
  () =>
    import("@/components/digital-twin/CampusScene").then(
      (module) => module.CampusScene,
    ),
  { ssr: false },
);

interface CampusTwinPanelProps {
  entities: TwinEntity[];
  counts: Partial<Record<TwinStatus, number>>;
  selectedId: string | null;
  onSelect: (entity: TwinEntity | null) => void;
  loading: boolean;
}

export function CampusTwinPanel({
  entities,
  counts,
  selectedId,
  onSelect,
  loading,
}: CampusTwinPanelProps) {
  const legend = (
    Object.keys(STATUS_DESCRIPTORS) as TwinStatus[]
  ).filter((status) => (counts[status] ?? 0) > 0);

  return (
    <section
      aria-label="Campus digital twin"
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border bg-card"
    >
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">
            Campus digital twin
          </h2>

          <p className="text-xs text-muted-foreground">
            {loading && !entities.length
              ? "Loading the model"
              : `${entities.length} entit${entities.length === 1 ? "y" : "ies"} · drag to orbit, scroll to zoom`}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <ul className="hidden items-center gap-3 sm:flex">
            {legend.map((status) => (
              <li
                key={status}
                className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
              >
                <span
                  aria-hidden
                  className={`size-2 rounded-full ${STATUS_DESCRIPTORS[status].dot}`}
                />

                {STATUS_DESCRIPTORS[status].label}

                <span className="tabular">
                  {counts[status]}
                </span>
              </li>
            ))}
          </ul>

          <Button
            variant="outline"
            size="sm"
            render={<a href="/digital-twin" />}
          >
            <Maximize2
              aria-hidden
              className="size-3.5"
            />
            Open twin
          </Button>
        </div>
      </header>

      {/*
        A soft neutral studio backdrop rather than the page white.
        The model is a physical-looking object, and a mid-tone
        behind it gives its edges something to read against.
      */}
      <div className="relative min-h-0 flex-1 bg-[#eceee9]">
        <Suspense fallback={<SceneSkeleton />}>
          <CampusScene
            entities={entities}
            selectedId={selectedId}
            onSelect={onSelect}
            className="h-full w-full"
          />
        </Suspense>

        <p className="pointer-events-none absolute bottom-3 left-3 flex items-center gap-1.5 rounded-md bg-card/85 px-2 py-1 text-[10px] text-muted-foreground backdrop-blur">
          <RotateCcw
            aria-hidden
            className="size-3"
          />
          Status is decided by the backend from stored readings
        </p>
      </div>
    </section>
  );
}

function SceneSkeleton() {
  return (
    <div className="grid h-full w-full place-items-center">
      <div className="w-full max-w-xs space-y-3 px-6">
        <Skeleton className="h-4 w-full" />

        <Skeleton className="h-4 w-4/5" />

        <p className="pt-2 text-center text-xs text-muted-foreground">
          Loading the 3D campus model
        </p>
      </div>
    </div>
  );
}
