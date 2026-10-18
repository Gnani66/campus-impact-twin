/**
 * Static twin configuration and marker placement.
 *
 * The database holds the identity of every campus entity
 * (code, type, status, twin_model_object). This module owns
 * the presentation layer: how an entity is coloured and
 * where it is anchored inside the 3D scene.
 *
 * Marker positions are derived from the model's real
 * bounding box at runtime instead of hardcoded coordinates.
 * The GLB does not have its origin at the centre of the
 * room, so fixed coordinates would place some markers behind
 * the camera or inside geometry.
 */

import { Box3, Object3D, Vector3 } from "three";

import type { Equipment, Sensor } from "@/lib/types";

export type Vec3 = [number, number, number];

export interface MarkerStyle {
  position: Vec3;
  color: string;
}

/**
 * Where the lecture hall GLB lives.
 *
 * Defaults to the copy in public/models. Set
 * NEXT_PUBLIC_MODEL_URL to serve it from somewhere else instead,
 * which is how it is hosted in production: the file is 260 MB,
 * far past what a repository should carry, and public/models is
 * gitignored for that reason, so a build from the repository has
 * no model to serve.
 *
 * Takes the raw value so the blank case is testable. A variable
 * that is declared but empty has to be treated as unset rather
 * than as a path, because an empty path would ask the frontend's
 * own origin for the model — which is the same silent wrong-host
 * failure the API address had.
 */
export function resolveModelPath(raw?: string | null): string {
  const configured = raw?.trim();

  return configured
    ? configured
    : "/models/lecture-hall.glb";
}

export const TWIN_CONFIG = {
  campusCode: "CIT-MAIN",
  zoneCode: "LH01",
  model: {
    path: resolveModelPath(process.env.NEXT_PUBLIC_MODEL_URL),
    scale: 1,
  },
  camera: {
    position: [8, 6, 10] as Vec3,
    fov: 45,
  },
  background: "#020617",
  markerHeight: 0.75,
  markerSpacing: 1.6,
  markerSpan: 0.85,
} as const;

const SENSOR_COLORS: Record<string, string> = {
  occupancy: "#22d3ee",
  temperature: "#f97316",
  humidity: "#38bdf8",
  co2: "#a78bfa",
  energy: "#34d399",
};

const FALLBACK_SENSOR_COLOR = "#94a3b8";
const FALLBACK_EQUIPMENT_COLOR = "#fbbf24";

export function getSensorColor(
  sensorType: string,
): string {
  return SENSOR_COLORS[sensorType] ?? FALLBACK_SENSOR_COLOR;
}

export function getEquipmentColor(): string {
  return FALLBACK_EQUIPMENT_COLOR;
}

export function formatMarkerLabel(
  sensorType: string,
): string {
  return sensorType
    .split("_")
    .map(
      (part) =>
        part.charAt(0).toUpperCase() +
        part.slice(1),
    )
    .join(" ");
}

/**
 * Places every marker in a row just above the model's
 * bounding box, centred on the box.
 *
 * Also returns the combined framing box (model + markers)
 * so the camera can be positioned to show everything.
 */

export interface MarkerLayout {
  sensors: MarkerStyle[];
  equipment: MarkerStyle[];
  framing: Box3;
}

export function computeMarkerLayout(
  scene: Object3D,
  sensors: Sensor[],
  equipment: Equipment[],
): MarkerLayout {
  const box = new Box3().setFromObject(scene);

  if (box.isEmpty()) {
    box.set(
      new Vector3(-4, 0, -4),
      new Vector3(4, 4, 4),
    );
  }

  const centre = box.getCenter(new Vector3());
  const total = sensors.length + equipment.length;

  const rowY =
    box.max.y + TWIN_CONFIG.markerHeight;

  const extent = box.getSize(new Vector3());

  // Spread the markers across the building so they read as
  // distinct positions rather than one cluster. The minimum
  // spacing keeps them apart even for a very small model.
  const usableWidth = Math.max(
    extent.x * TWIN_CONFIG.markerSpan,
    TWIN_CONFIG.markerSpacing * total,
    1,
  );

  const startX = centre.x - usableWidth / 2;

  const step = total > 0 ? usableWidth / total : 0;

  let index = 0;

  const nextPosition = (): Vec3 => {
    const x =
      total > 1
        ? startX + step * (index + 0.5)
        : centre.x;

    index += 1;

    return [x, rowY, centre.z];
  };

  const sensorMarkers = sensors.map((sensor) => ({
    position: nextPosition(),
    color: getSensorColor(sensor.sensor_type),
  }));

  const equipmentMarkers = equipment.map(() => ({
    position: nextPosition(),
    color: getEquipmentColor(),
  }));

  const framing = box.clone();

  for (const marker of [
    ...sensorMarkers,
    ...equipmentMarkers,
  ]) {
    framing.expandByPoint(
      new Vector3(...marker.position),
    );
  }

  return {
    sensors: sensorMarkers,
    equipment: equipmentMarkers,
    framing,
  };
}
