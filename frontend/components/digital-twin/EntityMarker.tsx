"use client";

import { Html } from "@react-three/drei";

import {
  getStatusColor,
  getStatusLabel,
  summariseStatus,
} from "@/lib/digital-twin";

import type { TwinEntity, TwinStatus } from "@/lib/twin-state";

interface EntityMarkerProps {
  entity: TwinEntity;
  position: [number, number, number];
  selected: boolean;
  onSelect: (entity: TwinEntity) => void;
}

/**
 * A status marker anchored to a campus entity.
 *
 * The marker carries the signal; the building behind it stays
 * neutral. Flooding the whole model with red reads as a game
 * rather than as instrumentation, and it would also make a
 * critical zone indistinguishable from a merely warm one.
 */
export function EntityMarker({
  entity,
  position,
  selected,
  onSelect,
}: EntityMarkerProps) {
  const color = getStatusColor(entity.status);

  const offline = entity.status === "offline";

  return (
    <group position={position}>
      {/* Generous invisible hit area.

          The visible sphere is small enough that clicking it
          reliably would be frustrating, so a larger transparent
          one sits behind it.

          The material is transparent rather than the mesh being
          `visible={false}`: Three.js's raycaster skips objects
          that are not visible, so an invisible mesh is never
          intersected and the marker silently stops being
          clickable. `opacity={0}` still participates in
          raycasting, which is what a hit target needs. */}
      <mesh
        onClick={(event) => {
          // Stops the click reaching the building behind, so
          // selecting a marker does not also select the model.
          event.stopPropagation();

          onSelect(entity);
        }}
      >
        <sphereGeometry args={[0.45, 8, 8]} />

        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      <mesh>
        <sphereGeometry args={[0.12, 16, 16]} />

        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={selected ? 2.4 : offline ? 0.3 : 1.4}
        />
      </mesh>

      {selected && (
        <mesh>
          <sphereGeometry args={[0.22, 16, 16]} />

          <meshBasicMaterial
            color={color}
            transparent
            opacity={0.25}
            wireframe
          />
        </mesh>
      )}

      {/*
          The label is the primary click target, not an
          annotation. The 3D sphere is small and sits against
          busy geometry, so clicking it reliably is awkward; the
          label is large, unambiguous, and directly above the
          marker it describes.

          `onPointerDown` rather than `onClick` so a drag that
          starts on the label still orbits the camera instead of
          being swallowed as a click that never completes.
        */}
      <Html distanceFactor={8} position={[0, 0.32, 0]} zIndexRange={[10, 0]}>
        <div
          onPointerDown={(event) => {
            event.stopPropagation();

            onSelect(entity);
          }}
          className="cursor-pointer whitespace-nowrap rounded-full bg-slate-950/90 px-3 py-1 text-xs font-medium text-white shadow-lg ring-1 ring-white/10 transition hover:bg-slate-900"
        >
          <span
            className="mr-2 inline-block h-2 w-2 rounded-full align-middle"
            style={{ backgroundColor: color }}
          />

          {entity.code}

          <span className="ml-2 text-slate-400">
            {getStatusLabel(entity.status)}
          </span>

          <div className="mt-0.5 max-w-56 truncate text-[10px] font-normal text-slate-400">
            {summariseStatus(entity)}
          </div>
        </div>
      </Html>
    </group>
  );
}

export function statusLabel(status: TwinStatus): string {
  return getStatusLabel(status);
}
