/**
 * Pure helpers for presenting stored telemetry.
 *
 * Kept separate from the React hook so they can be tested
 * without a DOM or a running backend.
 */

import type {
  LatestTelemetryData,
  LatestTelemetryReading,
} from "@/lib/types";

/**
 * Indexed by sensor id, which is the only identifier the
 * backend guarantees is stable.
 */

export type ReadingsBySensorId = Record<
  string,
  LatestTelemetryReading
>;

export function indexReadingsBySensor(
  data: LatestTelemetryData | null,
): ReadingsBySensorId {
  if (!data) {
    return {};
  }

  const indexed: ReadingsBySensorId = {};

  for (const reading of data.readings) {
    indexed[reading.sensor_id] = reading;
  }

  return indexed;
}

export type Freshness = "just now" | "stale" | "unknown";

/**
 * Age of a stored reading.
 *
 * This is presentation only. An old reading means the data is
 * old, never that a sensor is broken, so nothing here reports
 * a disconnect.
 */

export function readingAgeSeconds(
  timestamp: string,
  now: number,
): number | null {
  const parsed = Date.parse(timestamp);

  if (Number.isNaN(parsed)) {
    return null;
  }

  return Math.max(0, (now - parsed) / 1000);
}

export function describeFreshness(
  timestamp: string | undefined,
  now: number,
): Freshness {
  if (!timestamp) {
    return "unknown";
  }

  const age = readingAgeSeconds(timestamp, now);

  if (age === null) {
    return "unknown";
  }

  return age < 60 ? "just now" : "stale";
}

export function formatReadingAge(
  timestamp: string,
  now: number,
): string {
  const age = readingAgeSeconds(timestamp, now);

  if (age === null) {
    return "timestamp unknown";
  }

  if (age < 60) {
    return "just now";
  }

  const minutes = Math.floor(age / 60);

  if (minutes < 60) {
    return `${minutes} min ago`;
  }

  const hours = Math.floor(minutes / 60);

  if (hours < 24) {
    return `${hours} h ago`;
  }

  const days = Math.floor(hours / 24);

  return `${days} d ago`;
}

/**
 * True when the stored reading came from the simulator rather
 * than from physical instrumentation.
 */

export function isSimulated(
  reading: LatestTelemetryReading | undefined,
): boolean {
  if (!reading) {
    return false;
  }

  if (reading.source === "simulator") {
    return true;
  }

  return reading.metadata?.simulated === true;
}

/**
 * Formats a measurement for display.
 *
 * A reading with a non-finite value is not a measurement, so
 * it is reported as unavailable rather than printed as NaN.
 */

export function formatValue(
  reading: LatestTelemetryReading | undefined,
): string {
  if (!reading || !Number.isFinite(reading.value)) {
    return "no data";
  }

  const magnitude = Math.abs(reading.value);

  const text =
    magnitude >= 100
      ? reading.value.toFixed(1)
      : magnitude >= 10
        ? reading.value.toFixed(2)
        : reading.value.toFixed(2);

  return `${text} ${reading.unit}`;
}

export function formatMetricLabel(metric: string): string {
  return metric
    .split("_")
    .map(
      (part) =>
        part.charAt(0).toUpperCase() + part.slice(1),
    )
    .join(" ");
}

/**
 * The newest reading timestamp across a response, used for the
 * "data as of" line. The response's generated_at is when the
 * server answered, which is not when the data was measured.
 */

export function newestTimestamp(
  data: LatestTelemetryData | null,
): string | null {
  if (!data || data.readings.length === 0) {
    return null;
  }

  let newest: string | null = null;
  let newestMs = Number.NEGATIVE_INFINITY;

  for (const reading of data.readings) {
    const parsed = Date.parse(reading.timestamp);

    if (Number.isNaN(parsed)) {
      continue;
    }

    if (parsed > newestMs) {
      newestMs = parsed;
      newest = reading.timestamp;
    }
  }

  return newest;
}