import type { TwinStatus } from "@/lib/twin-state";

/**
 * Status vocabulary.
 *
 * The four states are decided by the backend
 * (`app/core/twin_rules.py`) and arrive as data. This file only
 * describes them for humans, and is the single place a hue is
 * attached to a state.
 *
 * Colour is never the only signal: every use pairs the hue with a
 * label, so the same information survives a colour-blind reader and
 * a printed screenshot.
 */

export interface StatusDescriptor {
  label: string;
  /** Tailwind text colour. */
  text: string;
  /** Tailwind background/border colour for a badge. */
  surface: string;
  /** Dot colour for markers and legends. */
  dot: string;
  description: string;
}

export const STATUS_DESCRIPTORS: Record<
  TwinStatus,
  StatusDescriptor
> = {
  normal: {
    label: "Normal",
    text: "text-healthy",
    surface: "bg-healthy-soft text-healthy border-healthy/25",
    dot: "bg-healthy",
    description: "Every measured reading is inside its band.",
  },
  warning: {
    label: "Warning",
    text: "text-warning",
    surface: "bg-warning-soft text-warning border-warning/25",
    dot: "bg-warning",
    description:
      "Something is drifting. Worth a look, not yet urgent.",
  },
  critical: {
    label: "Critical",
    text: "text-critical",
    surface: "bg-critical-soft text-critical border-critical/25",
    dot: "bg-critical",
    description: "A rule has been breached and people are affected.",
  },
  offline: {
    label: "Offline",
    text: "text-offline",
    surface: "bg-offline-soft text-offline border-offline/25",
    dot: "bg-offline",
    description:
      "No fresh readings. This is unknown, not healthy - the two must not be confused.",
  },
};

export function describeStatus(status: TwinStatus): StatusDescriptor {
  return STATUS_DESCRIPTORS[status];
}

/** Tailwind classes for a status badge. */
export function statusBadgeClass(status: TwinStatus): string {
  return `border ${STATUS_DESCRIPTORS[status].surface}`;
}

// ============================================================
// SEVERITY
// ============================================================
//
// Incident severity is a separate vocabulary from entity health:
// an entity can be critical because one rule fired, while an
// incident carries the severity the rule assigned.

export const SEVERITY_DESCRIPTORS: Record<
  string,
  StatusDescriptor
> = {
  critical: STATUS_DESCRIPTORS.critical,
  high: {
    ...STATUS_DESCRIPTORS.warning,
    label: "High",
  },
  medium: {
    ...STATUS_DESCRIPTORS.warning,
    label: "Medium",
    dot: "bg-warning/70",
  },
  low: {
    ...STATUS_DESCRIPTORS.offline,
    label: "Low",
  },
};

export function describeSeverity(
  severity: string,
): StatusDescriptor {
  return (
    SEVERITY_DESCRIPTORS[severity.toLowerCase()] ??
    SEVERITY_DESCRIPTORS.low
  );
}

// ============================================================
// METRICS
// ============================================================
//
// A metric that this deployment does not measure is `null`, and
// `null` renders as a dash. Substituting zero would be a
// fabrication: it would claim a room is empty because nobody put a
// sensor in it.

export interface MetricDescriptor {
  key: string;
  label: string;
  unit: string | null;
  /** Where to send someone who asks what the number means. */
  hint: string;
}

export const METRICS: MetricDescriptor[] = [
  {
    key: "temperature",
    label: "Temperature",
    unit: "°C",
    hint: "Air temperature reported by the zone sensor.",
  },
  {
    key: "humidity",
    label: "Humidity",
    unit: "%",
    hint: "Relative humidity.",
  },
  {
    key: "aqi",
    label: "Air quality",
    unit: "AQI",
    hint: "Air quality index. Not measured on this deployment.",
  },
  {
    key: "eco2",
    label: "CO₂",
    unit: "ppm",
    hint: "Equivalent CO₂, from the air quality sensor.",
  },
  {
    key: "occupancy",
    label: "Occupancy",
    unit: "people",
    hint: "Headcount, not a percentage.",
  },
  {
    key: "sound",
    label: "Noise",
    unit: "dB",
    hint: "Sound level. Not measured on this deployment.",
  },
  {
    key: "energy",
    label: "Energy",
    unit: "kW",
    hint: "Instantaneous draw for the zone.",
  },
];

/**
 * Formats a metric value, or a dash when it was not measured.
 *
 * `null` is never coerced to 0. "0 people" and "nobody is counting"
 * are different claims, and only the first is supported by data.
 */
export function formatMetric(
  value: number | null | undefined,
  unit: string | null,
): { text: string; measured: boolean } {
  if (value === null || value === undefined) {
    return { text: "—", measured: false };
  }

  const rounded =
    Math.abs(value) >= 100
      ? Math.round(value).toLocaleString()
      : Number(value.toFixed(1));

  return {
    text: unit ? `${rounded} ${unit}` : String(rounded),
    measured: true,
  };
}

/**
 * Compact relative age: "just now", "4 min ago", "2 h ago".
 *
 * Anything past a day says so plainly rather than counting days
 * forever, because a stale reading is a different kind of problem
 * from a fresh one and should read that way.
 */
export function formatAge(
  timestamp: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!timestamp) {
    return "never";
  }

  const then = new Date(timestamp).getTime();

  if (Number.isNaN(then)) {
    return "unknown";
  }

  const seconds = Math.max(
    0,
    Math.round((now - then) / 1000),
  );

  if (seconds < 45) {
    return "just now";
  }

  const minutes = Math.round(seconds / 60);

  if (minutes < 60) {
    return `${minutes} min ago`;
  }

  const hours = Math.round(minutes / 60);

  if (hours < 24) {
    return `${hours} h ago`;
  }

  const days = Math.round(hours / 24);

  return `${days} d ago`;
}

/** Greeting keyed to the operator's own clock. */
export function greeting(now: number = Date.now()): string {
  const hour = new Date(now).getHours();

  if (hour < 12) {
    return "Good morning";
  }

  if (hour < 18) {
    return "Good afternoon";
  }

  return "Good evening";
}
