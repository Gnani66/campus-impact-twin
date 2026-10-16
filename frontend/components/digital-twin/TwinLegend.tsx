"use client";

import { STATUS_COLORS, STATUS_ORDER } from "@/lib/digital-twin";

import type { TwinStatus } from "@/lib/twin-state";

/**
 * The status legend.
 *
 * Counts are included because "how many rooms are in trouble" is
 * the first question anyone asks of an operations view, and
 * making them count the markers would mean clicking around.
 */
export function TwinLegend({
  counts,
}: {
  counts?: Partial<Record<TwinStatus, number>>;
}) {
  return (
    <div className="absolute bottom-6 left-6 flex flex-wrap items-center gap-4 rounded-xl bg-slate-950/90 px-4 py-3 text-xs text-slate-300 backdrop-blur">
      {STATUS_ORDER.map((status) => (
        <span key={status} className="inline-flex items-center gap-2">
          <span
            className="h-2.5 w-2.5 rounded-full"
            style={{
              backgroundColor: STATUS_COLORS[status].marker,
            }}
          />

          {STATUS_COLORS[status].label}

          {counts?.[status] !== undefined && (
            <span className="text-slate-500">{counts[status]}</span>
          )}
        </span>
      ))}
    </div>
  );
}
