"use client";

import { getStatusColor, getStatusLabel } from "@/lib/digital-twin";

import type { TwinEntity, TwinStatus } from "@/lib/twin-state";

/**
 * A plain-DOM list of campus entities.
 *
 * SELECTION DOES NOT DEPEND ON RAYCASTING.
 *
 * Picking an entity by clicking a marker inside the 3D scene
 * works only while the marker happens to be on screen, unobscured
 * and correctly projected. drei's HTML labels are positioned from
 * the render loop, so a marker outside the frustum sits at an
 * absurd screen coordinate and cannot be clicked at all. Every
 * attempt to make that reliable was unreliable for a different
 * reason: the hit sphere was invisible (and the raycaster skips
 * invisible objects), the label wrapper swallowed pointer events,
 * and the camera was framed inside a model 56 units wide.
 *
 * This list always works. The 3D marker stays as the visual
 * signal and is still clickable; the list is the guaranteed path
 * to the same selection, and it is also what a keyboard user or a
 * small screen needs.
 */
export function EntityList({
  entities,
  selectedId,
  onSelect,
}: {
  entities: TwinEntity[];
  selectedId: string | null;
  onSelect: (entity: TwinEntity) => void;
}) {
  if (entities.length === 0) {
    return null;
  }

  return (
    <div className="absolute left-6 top-6 w-56 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/90 backdrop-blur">
      <p className="border-b border-white/10 px-4 py-2.5 text-xs font-semibold uppercase tracking-widest text-slate-400">
        Campus entities
      </p>

      <ul className="max-h-64 overflow-y-auto">
        {entities.map((entity) => {
          const selected = entity.id === selectedId;

          return (
            <li key={entity.id}>
              <button
                type="button"
                onClick={() => onSelect(entity)}
                aria-pressed={selected}
                className={`flex w-full items-center gap-2.5 px-4 py-2.5 text-left transition ${
                  selected ? "bg-white/10" : "hover:bg-white/5"
                }`}
              >
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-full"
                  style={{
                    backgroundColor: getStatusColor(entity.status),
                  }}
                />

                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-white">
                    {entity.name}
                  </span>

                  <span className="block truncate text-[11px] text-slate-400">
                    {entity.code} · {getStatusLabel(entity.status)}
                  </span>
                </span>

                {entity.pendingApprovals > 0 && (
                  <span
                    className="shrink-0 rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-200"
                    title={`${entity.pendingApprovals} approval(s) awaiting review`}
                  >
                    {entity.pendingApprovals}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function statusText(status: TwinStatus): string {
  return getStatusLabel(status);
}
