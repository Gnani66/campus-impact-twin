/**
 * Telemetry presentation tests.
 *
 * Pure functions only: no DOM, no backend, no network. The
 * API client is tested with a stubbed global fetch.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getLatestTelemetry } from "@/lib/api";
import {
  describeFreshness,
  formatMetricLabel,
  formatReadingAge,
  formatValue,
  indexReadingsBySensor,
  isSimulated,
  newestTimestamp,
  readingAgeSeconds,
} from "@/lib/telemetry";
import type {
  LatestTelemetryData,
  LatestTelemetryReading,
} from "@/lib/types";


const T0 = "2026-10-15T13:01:53.369695Z";
const T0_MS = Date.parse(T0);

function reading(
  overrides: Partial<LatestTelemetryReading> = {},
): LatestTelemetryReading {
  return {
    sensor_id: "sensor-a",
    sensor_code: "TEMP-LH01",
    sensor_type: "temperature",
    metric: "temperature",
    value: 26.0033,
    unit: "°C",
    timestamp: T0,
    source: "simulator",
    quality: "good",
    campus_id: "campus-1",
    building_id: "building-1",
    floor_id: "floor-1",
    zone_id: "zone-1",
    campus_code: "CIT-MAIN",
    building_code: "ACADEMIC-BLK-A",
    floor_code: "A-F1",
    zone_code: "LH01",
    metadata: { simulated: true },
    ...overrides,
  };
}

function payload(
  readings: LatestTelemetryReading[],
  overrides: Partial<LatestTelemetryData> = {},
): LatestTelemetryData {
  return {
    campus_code: "CIT-MAIN",
    campus_id: "campus-1",
    zone_code: null,
    sensors_considered: 5,
    reading_count: readings.length,
    readings,
    sensors_without_readings: [],
    generated_at: "2026-10-15T13:05:00Z",
    ...overrides,
  };
}

function mockFetch(body: unknown, ok = true, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  });

  vi.stubGlobal("fetch", fetchMock);

  return fetchMock;
}

// --- Sensor matching --------------------------------------------

describe("indexReadingsBySensor", () => {
  it("matches readings to sensors by sensor id", () => {
    const indexed = indexReadingsBySensor(
      payload([
        reading({ sensor_id: "a", metric: "co2" }),
        reading({ sensor_id: "b", metric: "temperature" }),
      ]),
    );

    expect(Object.keys(indexed).sort()).toEqual(["a", "b"]);
    expect(indexed.a.metric).toBe("co2");
    expect(indexed.b.metric).toBe("temperature");
  });

  it("returns an empty map for no data", () => {
    expect(indexReadingsBySensor(null)).toEqual({});
    expect(indexReadingsBySensor(payload([]))).toEqual({});
  });

  it("keeps only the last reading when one sensor repeats", () => {
    const indexed = indexReadingsBySensor(
      payload([
        reading({ sensor_id: "a", value: 1 }),
        reading({ sensor_id: "a", value: 2 }),
      ]),
    );

    expect(indexed.a.value).toBe(2);
  });
});

// --- Missing and empty -------------------------------------------

describe("missing readings", () => {
  it("shows no data rather than zero", () => {
    expect(formatValue(undefined)).toBe("no data");
  });

  it("treats a non-finite value as unavailable", () => {
    expect(formatValue(reading({ value: Number.NaN }))).toBe(
      "no data",
    );
    expect(formatValue(reading({ value: Infinity }))).toBe(
      "no data",
    );
  });

  it("reports sensors without readings", () => {
    const data = payload([reading()], {
      sensors_considered: 5,
      sensors_without_readings: ["HUM-LH01", "OCC-LH01"],
    });

    expect(data.readings).toHaveLength(1);
    expect(data.sensors_without_readings).toEqual([
      "HUM-LH01",
      "OCC-LH01",
    ]);
  });
});

// --- Formatting ---------------------------------------------------

describe("formatValue", () => {
  it("includes the unit from the backend", () => {
    expect(formatValue(reading())).toBe("26.00 °C");
    expect(
      formatValue(
        reading({ metric: "occupancy", value: 0, unit: "people" }),
      ),
    ).toBe("0.00 people");
    expect(
      formatValue(
        reading({ metric: "co2", value: 820.5, unit: "ppm" }),
      ),
    ).toBe("820.5 ppm");
  });
});

describe("formatMetricLabel", () => {
  it("humanises a metric name", () => {
    expect(formatMetricLabel("temperature")).toBe("Temperature");
    expect(formatMetricLabel("air_quality")).toBe("Air Quality");
  });
});

// --- Freshness ----------------------------------------------------

describe("freshness", () => {
  it("computes age from the reading timestamp", () => {
    expect(readingAgeSeconds(T0, T0_MS + 30_000)).toBe(30);
  });

  it("labels a recent reading as just now", () => {
    expect(describeFreshness(T0, T0_MS + 10_000)).toBe(
      "just now",
    );
    expect(formatReadingAge(T0, T0_MS + 10_000)).toBe("just now");
  });

  it("labels an old reading as stale without claiming failure", () => {
    const old = describeFreshness(
      T0,
      T0_MS + 3_600_000,
    );

    expect(old).toBe("stale");
    expect(formatReadingAge(T0, T0_MS + 3_600_000)).toBe(
      "1 h ago",
    );
    expect(formatReadingAge(T0, T0_MS + 120_000)).toBe(
      "2 min ago",
    );
  });

  it("reports unknown for missing or invalid timestamps", () => {
    expect(describeFreshness(undefined, T0_MS)).toBe("unknown");
    expect(describeFreshness("not-a-date", T0_MS)).toBe(
      "unknown",
    );
    expect(
      formatReadingAge("not-a-date", T0_MS),
    ).toBe("timestamp unknown");
  });

  it("never reports a reading as newer than now", () => {
    expect(readingAgeSeconds(T0, T0_MS - 60_000)).toBe(0);
  });

  it("uses the reading timestamp, not generated_at", () => {
    const data = payload([reading()], {
      generated_at: "2026-10-15T13:05:00Z",
    });

    expect(newestTimestamp(data)).toBe(T0);
  });

  it("returns null when there is nothing to date", () => {
    expect(newestTimestamp(null)).toBeNull();
    expect(newestTimestamp(payload([]))).toBeNull();
  });

  it("picks the newest of several readings", () => {
    const data = payload([
      reading({
        sensor_id: "a",
        timestamp: "2026-10-15T12:00:00Z",
      }),
      reading({
        sensor_id: "b",
        timestamp: "2026-10-15T13:30:00Z",
      }),
      reading({
        sensor_id: "c",
        timestamp: "2026-10-15T12:45:00Z",
      }),
    ]);

    expect(newestTimestamp(data)).toBe("2026-10-15T13:30:00Z");
  });
});

// --- Simulated labelling ------------------------------------------

describe("isSimulated", () => {
  it("detects the simulator source", () => {
    expect(isSimulated(reading())).toBe(true);
  });

  it("does not label physical sensor data", () => {
    const physical = reading({
      source: "sensor",
      metadata: {},
    });

    expect(isSimulated(physical)).toBe(false);
  });

  it("treats absent readings as not simulated", () => {
    expect(isSimulated(undefined)).toBe(false);
  });

  it("honours the metadata flag as well", () => {
    expect(
      isSimulated(
        reading({ source: "import", metadata: { simulated: true } }),
      ),
    ).toBe(true);
  });
});

// --- API client ----------------------------------------------------

describe("getLatestTelemetry", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests the latest endpoint for the campus", async () => {
    const fetchMock = mockFetch(payload([reading()]));

    const data = await getLatestTelemetry("CIT-MAIN");

    const [url, init] = fetchMock.mock.calls[0];

    expect(url).toContain(
      "/api/v1/campus/CIT-MAIN/telemetry/latest",
    );
    expect(init.cache).toBe("no-store");
    expect(data.readings).toHaveLength(1);
  });

  it("passes zone and limit only when provided", async () => {
    const fetchMock = mockFetch(payload([]));

    await getLatestTelemetry("CIT-MAIN", {
      zone: "LH01",
      limit: 10,
    });

    const url = fetchMock.mock.calls[0][0];

    expect(url).toContain("zone=LH01");
    expect(url).toContain("limit=10");

    const plain = mockFetch(payload([]));

    await getLatestTelemetry("CIT-MAIN");

    expect(plain.mock.calls[0][0]).not.toContain("?");
  });

  it("throws on a non-success response", async () => {
    mockFetch({}, false, 503);

    await expect(
      getLatestTelemetry("CIT-MAIN"),
    ).rejects.toThrow(/503/);
  });

  it("throws when the network fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("offline")),
    );

    await expect(
      getLatestTelemetry("CIT-MAIN"),
    ).rejects.toThrow(/unreachable/i);
  });

  it("rejects a malformed response shape", async () => {
    mockFetch({ unexpected: true });

    await expect(
      getLatestTelemetry("CIT-MAIN"),
    ).rejects.toThrow(/unexpected response shape/i);
  });

  it("drops individually malformed readings", async () => {
    mockFetch(
      payload([
        reading(),
        { sensor_id: "broken" } as LatestTelemetryReading,
      ]),
    );

    const data = await getLatestTelemetry("CIT-MAIN");

    expect(data.readings).toHaveLength(1);
    expect(data.readings[0].sensor_id).toBe("sensor-a");
  });

  it("propagates an abort instead of reporting an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(
        new DOMException("aborted", "AbortError"),
      ),
    );

    await expect(
      getLatestTelemetry("CIT-MAIN"),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});