"use client";

import { Canvas } from "@react-three/fiber";
import {
  OrbitControls,
  PerspectiveCamera,
  useGLTF,
  useProgress,
} from "@react-three/drei";
import {
  Suspense,
  useMemo,
} from "react";
import { Box3, Vector3 } from "three";

import type {
  Equipment,
  LatestTelemetryReading,
  Sensor,
} from "@/lib/types";

import {
  TWIN_CONFIG,
  computeMarkerLayout,
  type MarkerStyle,
  type Vec3,
} from "@/lib/twin/config";

import LectureHall from "./LectureHall";
import SensorMarker from "./SensorMarker";

interface TwinCanvasProps {
  sensors: Sensor[];
  equipment: Equipment[];
  /**
   * Latest stored readings keyed by sensor id. Changes on every
   * refresh, so the scene keeps its geometry and only the
   * marker labels update.
   */
  readings?: Record<string, LatestTelemetryReading>;
  now: number | null;
}

export default function TwinCanvas({
  sensors,
  equipment,
  readings,
  now,
}: TwinCanvasProps) {
  return (
    <div className="relative h-full w-full">
      {/* "percentage" is PCFShadowMap. The bare `shadows` shorthand
          resolves to PCFSoftShadowMap, which three 0.186 removed
          from the renderer: it warned and fell back to this same
          type, so naming it is identical output without the
          warning. */}
      <Canvas shadows="percentage">
        <color
          attach="background"
          args={[TWIN_CONFIG.background]}
        />

        <ambientLight intensity={1.2} />

        <hemisphereLight
          intensity={0.6}
          color="#bae6fd"
          groundColor="#0f172a"
        />

        <directionalLight
          position={[10, 15, 10]}
          intensity={2.4}
          castShadow
        />

        <Suspense fallback={null}>
          <TwinScene
            sensors={sensors}
            equipment={equipment}
            readings={readings}
            now={now}
          />
        </Suspense>
      </Canvas>

      <ModelLoader />
    </div>
  );
}

/**
 * useGLTF caches the parsed scene, so calling it here does
 * not trigger a second download. It gives us the real
 * bounding box of the model, which anchors both the markers
 * and the camera.
 */

function TwinScene({
  sensors,
  equipment,
  readings,
  now,
}: TwinCanvasProps) {
  const { scene } = useGLTF(
    TWIN_CONFIG.model.path,
  );

  // Placement depends only on the model and the sensors, never
  // on readings, so a telemetry refresh cannot move a marker.
  const layout = useMemo(
    () =>
      computeMarkerLayout(
        scene,
        sensors,
        equipment,
      ),
    [scene, sensors, equipment],
  );

  const framing = useFraming(layout.framing);

  return (
    <>
      <PerspectiveCamera
        makeDefault
        fov={TWIN_CONFIG.camera.fov}
        position={framing.position}
        near={framing.near}
        far={framing.far}
      />

      <LectureHall />

      {sensors.map((sensor, index) => (
        <SensorMarker
          key={sensor.id}
          sensor={sensor}
          marker={layout.sensors[index]}
          reading={readings?.[sensor.id]}
          now={now}
        />
      ))}

      {equipment.map((item, index) => (
        <EquipmentMarker
          key={item.id}
          marker={layout.equipment[index]}
        />
      ))}

      <OrbitControls
        makeDefault
        target={framing.target}
        enableDamping
        dampingFactor={0.08}
        minDistance={2}
        maxDistance={framing.far / 4}
        maxPolarAngle={Math.PI / 2.05}
      />
    </>
  );
}

function EquipmentMarker({
  marker,
}: {
  marker: MarkerStyle;
}) {
  return (
    <mesh
      position={[
        marker.position[0],
        marker.position[1] - 0.3,
        marker.position[2],
      ]}
    >
      <boxGeometry args={[0.4, 0.4, 0.4]} />

      <meshStandardMaterial
        color={marker.color}
        emissive={marker.color}
        emissiveIntensity={0.35}
        roughness={0.4}
        metalness={0.3}
      />
    </mesh>
  );
}

/**
 * The GLB has its origin at an arbitrary point, so a fixed
 * camera would either crop the model or push markers out of
 * frame. This derives a camera that fits the real bounding
 * box plus the marker row.
 */

interface Framing {
  position: Vec3;
  target: Vec3;
  near: number;
  far: number;
}

const DEFAULT_FRAMING: Framing = {
  position: TWIN_CONFIG.camera.position,
  target: [0, 0, 0],
  near: 0.1,
  far: 500,
};

function useFraming(framing: Box3): Framing {
  return useMemo(() => {
    if (framing.isEmpty()) {
      return DEFAULT_FRAMING;
    }

    const centre = framing.getCenter(new Vector3());
    const extent = framing.getSize(new Vector3());

    const fov =
      TWIN_CONFIG.camera.fov * (Math.PI / 180);

    // Assume a 16:9 viewport. The horizontal field of view
    // is wider, so height is the binding constraint for a
    // wide building.
    const aspect = 16 / 9;

    const horizontalFov =
      2 * Math.atan(Math.tan(fov / 2) * aspect);

    const fitHeight =
      extent.y / 2 / Math.tan(fov / 2);

    const fitWidth =
      extent.x / 2 / Math.tan(horizontalFov / 2);

    const fitDepth =
      extent.z / 2 / Math.tan(fov / 2);

    const distance =
      Math.max(fitHeight, fitWidth, fitDepth) * 1.05;

    const direction = new Vector3(
      0.45,
      0.4,
      1,
    ).normalize();

    const position = centre
      .clone()
      .add(direction.multiplyScalar(distance));

    return {
      position: [
        position.x,
        position.y,
        position.z,
      ],
      target: [centre.x, centre.y, centre.z],
      near: Math.max(distance / 100, 0.01),
      far: distance * 20,
    };
  }, [framing]);
}

/**
 * The lecture hall asset is a large GLB, so the first paint
 * can take several seconds. Without this the scene is just a
 * black rectangle while the Suspense boundary resolves.
 */

function ModelLoader() {
  const { progress, active } = useProgress();

  if (!active && progress >= 100) {
    return null;
  }

  const percent = Math.min(
    100,
    Math.max(0, Math.round(progress)),
  );

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-950/70">
      <div className="w-64 text-center">
        <p className="text-xs font-medium uppercase tracking-[0.25em] text-cyan-400">
          Loading digital twin
        </p>

        <p className="mt-3 text-3xl font-semibold tabular-nums text-white">
          {percent}%
        </p>

        <div className="mt-4 h-1 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-cyan-400 transition-[width] duration-200"
            style={{ width: `${percent}%` }}
          />
        </div>

        <p className="mt-3 text-xs text-slate-500">
          {TWIN_CONFIG.model.path}
        </p>
      </div>
    </div>
  );
}
