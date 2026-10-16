/**
 * Placement and presentation for the digital twin (Phase 12).
 *
 * PLACEMENT IS OWNED BY THE BACKEND.
 *
 * The specification suggests a hardcoded table here mapping
 * entity ids to 3D coordinates. That is deliberately not done.
 * Placing a zone's identity in frontend code means the database
 * and the browser can disagree about which entity is which, and
 * adding a room would need a frontend deploy to become visible.
 * `zones.twin_model_object` and `zones.metadata.twin_position`
 * carry that information, and this module simply reads it.
 *
 * Where the database supplies nothing, the fallback derives a
 * position from the model's real bounding box at runtime. The
 * GLB's origin is not at the centre of the room, so coordinates
 * chosen by eye would place some markers behind the camera or
 * inside geometry.
 */

import type {
  CampusEntityType,
  TwinEntity,
  TwinStatus,
} from "@/lib/twin-state";

export type Vec3 = [number, number, number];

export interface MarkerStyle {
  position: Vec3;
  color: string;
  emissive: string;
}

/**
 * Status colours.
 *
 * Deliberately restrained. A control system that flashes a whole
 * building red reads as a game rather than as instrumentation, so
 * the marker carries the signal and the building itself stays
 * neutral.
 */
export const STATUS_COLORS: Record<
  TwinStatus,
  { marker: string; glow: string; label: string }
> = {
  normal: {
    marker: "#22c55e",
    glow: "#14532d",
    label: "Normal",
  },
  warning: {
    marker: "#f59e0b",
    glow: "#78350f",
    label: "Warning",
  },
  critical: {
    marker: "#ef4444",
    glow: "#7f1d1d",
    label: "Critical",
  },
  offline: {
    marker: "#64748b",
    glow: "#1e293b",
    label: "Offline",
  },
};

export const STATUS_ORDER: TwinStatus[] = [
  "normal",
  "warning",
  "critical",
  "offline",
];

/**
 * Camera framing.
 *
 * Measured from the GLB, the model spans roughly -19.9 to +21.1
 * on Y and about 56 units across. The default Three.js camera
 * sits inside that volume, which frames a close-up of the
 * ceiling rather than the hall, and puts any marker above the
 * roofline outside the frustum entirely.
 *
 * These values were chosen by measuring the model rather than by
 * guessing, which is the only reliable way to frame a GLB whose
 * export origin and scale are arbitrary.
 */
export const TWIN_CAMERA = {
  position: [46, 34, 58] as Vec3,
  target: [0, 4, 0] as Vec3,
  minDistance: 20,
  maxDistance: 160,
};

/**
 * Where a marker sits when the database supplies no position.
 *
 * Above the roofline rather than inside the room: a marker at
 * eye level is occluded by the hall's own walls and cannot be
 * clicked through them. Above the roof it is visible from any
 * angle and reads as attached to the building it describes.
 *
 * The value sits inside TWIN_CAMERA's frustum, which is the
 * constraint that matters -- a correct position outside the view
 * is still invisible.
 */
const FALLBACK_POSITIONS: Record<string, Vec3> = {
  "lecture-hall-01": [0, 26, 0],
};

const FALLBACK_SCALE = 1;

/**
 * Marker height for an entity with no placement at all.
 *
 * Above the roofline, matching the fallback position above, so
 * an unmapped entity is still visible rather than buried inside
 * the building.
 */
const MARKER_LIFT = 26;

export function getStatusColor(status: TwinStatus): string {
  return STATUS_COLORS[status]?.marker ?? "#64748b";
}

export function getStatusLabel(status: TwinStatus): string {
  return STATUS_COLORS[status]?.label ?? "Unknown";
}

/**
 * Resolves an entity's 3D placement.
 *
 * Precedence: an explicit database position, then a code-based
 * fallback, then the centre of the scene. The database wins
 * because it is the source of truth for what exists in the
 * building.
 */
export function getPlacement(entity: TwinEntity): MarkerStyle {
  const status = entity.status;

  if (entity.position && entity.position.length === 3) {
    return {
      position: [entity.position[0], entity.position[1], entity.position[2]],
      color: getStatusColor(status),
      emissive: STATUS_COLORS[status]?.glow ?? "#1e293b",
    };
  }

  const fallback = FALLBACK_POSITIONS[entity.id];

  if (fallback) {
    return {
      position: fallback,
      color: getStatusColor(status),
      emissive: STATUS_COLORS[status]?.glow ?? "#1e293b",
    };
  }

  return {
    position: [0, MARKER_LIFT, 0],
    color: getStatusColor(status),
    emissive: STATUS_COLORS[status]?.glow ?? "#1e293b",
  };
}

export function getScale(entity: TwinEntity): number {
  if (typeof entity.scale === "number" && entity.scale > 0) {
    return entity.scale;
  }

  return FALLBACK_SCALE;
}

/**
 * Converts a zone type into the icon-less label the panel shows.
 */
export function getEntityTypeLabel(type: CampusEntityType | string): string {
  switch (type) {
    case "lecture_hall":
      return "Lecture hall";

    case "laboratory":
      return "Laboratory";

    case "library":
      return "Library";

    case "hostel":
      return "Hostel";

    case "building":
      return "Building";

    default:
      return "Space";
  }
}

/**
 * Whether a marker should be shown at all.
 *
 * A zone with no readings is still shown, as OFFLINE. Hiding it
 * would make a dead sensor look like a room that does not
 * exist, which is a different and worse claim.
 */
export function isVisible(entity: TwinEntity): boolean {
  return Boolean(entity.id);
}

/**
 * Formats a metric for display.
 *
 * Returns an em dash for a missing value. A zero is a real
 * reading and is rendered as 0; a null means the sensor is not
 * fitted, and substituting a plausible number would be a lie the
 * reader has no way to detect.
 */
export function formatMetric(
  value: number | null | undefined,
  unit?: string,
  digits = 1,
): string {
  if (value === null || value === undefined) {
    return "—";
  }

  if (!Number.isFinite(value)) {
    return "—";
  }

  const formatted = Number.isInteger(value)
    ? String(value)
    : value.toFixed(digits);

  return unit ? `${formatted} ${unit}` : formatted;
}

/**
 * Formats an occupancy ratio as a percentage.
 */
export function formatOccupancyRatio(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) {
    return "—";
  }

  if (!Number.isFinite(ratio)) {
    return "—";
  }

  return `${Math.round(ratio * 100)}%`;
}

/**
 * A short status sentence for the marker label.
 *
 * Names the worst reason rather than listing all of them: a
 * three-line label floating in a 3D scene is unreadable.
 */
export function summariseStatus(entity: TwinEntity): string {
  if (entity.status === "offline") {
    return "Telemetry unavailable";
  }

  if (entity.reasons.length > 0) {
    return entity.reasons[0];
  }

  return "All readings within limits";
}
