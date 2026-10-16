"use client";

import { Suspense, useCallback } from "react";

import { Canvas } from "@react-three/fiber";

import { ContactShadows, Environment, OrbitControls } from "@react-three/drei";

import { EntityMarker } from "./EntityMarker";
import { LectureHall } from "./LectureHall";
import { TwinLighting } from "./TwinLighting";

import { TWIN_CAMERA, getPlacement, isVisible } from "@/lib/digital-twin";

import type { TwinEntity } from "@/lib/twin-state";

interface CampusSceneProps {
  entities: TwinEntity[];
  selectedId: string | null;
  onSelect: (entity: TwinEntity | null) => void;
}

/**
 * The 3D scene.
 *
 * THREE.JS ASKED ONE QUESTION: what is the current state of this
 * object?
 *
 * There is no fetch, no Supabase client and no business rule in
 * this file or anything it imports. Every number arrives as a
 * prop already resolved by the backend, and status is a value the
 * backend decided. Keeping that line clean is what stops the view
 * and the operational record from disagreeing, and it means the
 * status rules can be tested as pure functions rather than by
 * clicking a building.
 */
export function CampusScene({
  entities,
  selectedId,
  onSelect,
}: CampusSceneProps) {
  const visible = entities.filter(isVisible);

  const handleMiss = useCallback(() => {
    // Clicking empty space deselects. Without this a selection
    // sticks after the camera has been moved somewhere else.
    onSelect(null);
  }, [onSelect]);

  return (
    <div className="h-full w-full overflow-hidden rounded-2xl bg-slate-950">
      {/* "percentage" is PCFShadowMap. The bare `shadows`
          shorthand resolves to PCFSoftShadowMap, which three 0.186
          removed from the renderer: it warned and fell back to this
          same type, so naming it is identical output without the
          warning. */}
      <Canvas
        camera={{
          position: TWIN_CAMERA.position,
          fov: 45,
        }}
        dpr={[1, 1.5]}
        shadows="percentage"
        onPointerMissed={handleMiss}
      >
        <TwinLighting />

        <Environment preset="city" background={false} />

        <Suspense fallback={null}>
          <LectureHall />

          {visible.map((entity) => {
            const placement = getPlacement(entity);

            return (
              <EntityMarker
                key={entity.id}
                entity={entity}
                position={placement.position}
                selected={entity.id === selectedId}
                onSelect={onSelect}
              />
            );
          })}
        </Suspense>

        <ContactShadows
          position={[0, -0.05, 0]}
          opacity={0.35}
          scale={20}
          blur={2.5}
          far={10}
        />

        {/* `target` is set explicitly because the camera cannot be
            assumed to look at the origin: this GLB's bounds are
            not centred there, and a default target of (0,0,0)
            frames empty space. */}
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.08}
          target={TWIN_CAMERA.target}
          minDistance={TWIN_CAMERA.minDistance}
          maxDistance={TWIN_CAMERA.maxDistance}
          maxPolarAngle={Math.PI / 2.05}
        />
      </Canvas>
    </div>
  );
}
