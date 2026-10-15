import type {
  Building,
  Campus,
  Equipment,
  Floor,
  Incident,
  LatestTelemetryData,
  Sensor,
  Zone,
} from "@/lib/types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000";

export interface CampusTwinData {
  campus: Campus;
  buildings: Building[];
  floors: Floor[];
  zones: Zone[];
  equipment: Equipment[];
  sensors: Sensor[];
  incidents: Incident[];
}

export async function getCampusTwin(
  campusCode = "CIT-MAIN",
): Promise<CampusTwinData> {
  const response = await fetch(
    `${API_URL}/api/v1/campus/${campusCode}/twin`,
    {
      cache: "no-store",
    },
  );

  if (!response.ok) {
    throw new Error(
      `Campus Twin API failed: ${response.status}`,
    );
  }

  return response.json();
}


export interface LatestTelemetryOptions {
  /**
   * Narrows the response to one zone. Omitted when the caller
   * does not need it, because the backend defaults to every
   * zone in the campus.
   */
  zone?: string;
  limit?: number;
  /**
   * Lets a caller cancel an in-flight request, which is how
   * the polling hook avoids overlapping requests and cleans up
   * on unmount.
   */
  signal?: AbortSignal;
}

/**
 * The shape the endpoint promises. Anything else is treated as
 * a malformed response rather than rendered.
 */

function isLatestTelemetryData(
  value: unknown,
): value is LatestTelemetryData {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<LatestTelemetryData>;

  return (
    typeof candidate.campus_code === "string" &&
    Array.isArray(candidate.readings)
  );
}

function isLatestTelemetryReading(
  value: unknown,
): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const reading = value as Partial<
    LatestTelemetryData["readings"][number]
  >;

  return (
    typeof reading.sensor_id === "string" &&
    typeof reading.metric === "string" &&
    typeof reading.value === "number" &&
    typeof reading.unit === "string" &&
    typeof reading.timestamp === "string"
  );
}

/**
 * Reads the latest stored telemetry for a campus.
 *
 * Stored data, not a live stream: the caller decides how
 * fresh it looks by comparing `timestamp` with the clock.
 */

export async function getLatestTelemetry(
  campusCode = "CIT-MAIN",
  options: LatestTelemetryOptions = {},
): Promise<LatestTelemetryData> {
  const params = new URLSearchParams();

  if (options.zone) {
    params.set("zone", options.zone);
  }

  if (typeof options.limit === "number") {
    params.set("limit", String(options.limit));
  }

  const query = params.toString();
  const url =
    `${API_URL}/api/v1/campus/${campusCode}` +
    `/telemetry/latest${query ? `?${query}` : ""}`;

  let response: Response;

  try {
    response = await fetch(url, {
      cache: "no-store",
      signal: options.signal,
    });
  } catch (cause) {
    if (
      cause instanceof DOMException &&
      cause.name === "AbortError"
    ) {
      throw cause;
    }

    throw new Error(
      "Telemetry API is unreachable. Is the backend running?",
    );
  }

  if (!response.ok) {
    throw new Error(
      `Telemetry API failed: ${response.status}`,
    );
  }

  const body: unknown = await response
    .json()
    .catch(() => {
      throw new Error(
        "Telemetry API returned a malformed response.",
      );
    });

  if (!isLatestTelemetryData(body)) {
    throw new Error(
      "Telemetry API returned an unexpected response shape.",
    );
  }

  // A malformed entry is dropped rather than rendered as
  // "no data", so a partial response still shows what is
  // trustworthy.
  const readings =
    body.readings.filter(isLatestTelemetryReading);

  return {
    ...body,
    readings,
  };
}
