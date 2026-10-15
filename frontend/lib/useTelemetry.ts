"use client";

/**
 * Shared polling hook for stored telemetry.
 *
 * One hook instance owns one loop, so the dashboard and the
 * twin never duplicate each other's requests. Each page mounts
 * its own instance, which is the intended usage: the two pages
 * are never on screen at the same time.
 *
 * Behaviour:
 * - requests never overlap; the next poll waits for the
 *   previous one to settle;
 * - an in-flight request is aborted on unmount;
 * - a failed refresh keeps the last good readings and raises
 *   `refreshFailed`, so the UI degrades instead of blanking.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { getLatestTelemetry } from "@/lib/api";
import { indexReadingsBySensor } from "@/lib/telemetry";
import type {
  ReadingsBySensorId,
} from "@/lib/telemetry";
import type { LatestTelemetryData } from "@/lib/types";

export const DEFAULT_POLL_INTERVAL_MS = 20_000;

export interface UseTelemetryOptions {
  campusCode?: string;
  zone?: string;
  limit?: number;
  intervalMs?: number;
  enabled?: boolean;
}

export interface UseTelemetryResult {
  data: LatestTelemetryData | null;
  /** Keyed by sensor id, ready for the 3D markers. */
  readingsBySensorId: ReadingsBySensorId;
  loading: boolean;
  error: string | null;
  /** True when a refresh failed but earlier data is shown. */
  refreshFailed: boolean;
  lastSuccessAt: number | null;
}

export function useTelemetry(
  options: UseTelemetryOptions = {},
): UseTelemetryResult {
  const {
    campusCode = "CIT-MAIN",
    zone,
    limit,
    intervalMs = DEFAULT_POLL_INTERVAL_MS,
    enabled = true,
  } = options;

  const [data, setData] = useState<LatestTelemetryData | null>(
    null,
  );
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const [refreshFailed, setRefreshFailed] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<
    number | null
  >(null);

  // Guards against overlapping requests and stale updates.
  const inFlight = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  const fetchOnce = useCallback(async () => {
    if (inFlight.current) {
      // A request is already running: never stack another.
      return;
    }

    const controller = new AbortController();

    inFlight.current = controller;

    try {
      const result = await getLatestTelemetry(campusCode, {
        zone,
        limit,
        signal: controller.signal,
      });

      if (!mounted.current) {
        return;
      }

      setData(result);
      setError(null);
      setRefreshFailed(false);
      setLastSuccessAt(Date.now());
    } catch (cause) {
      if (
        cause instanceof DOMException &&
        cause.name === "AbortError"
      ) {
        return;
      }

      if (!mounted.current) {
        return;
      }

      setError(
        cause instanceof Error
          ? cause.message
          : "Telemetry request failed",
      );

      // Keep the previous readings visible if there are any.
      setRefreshFailed(true);
    } finally {
      if (inFlight.current === controller) {
        inFlight.current = null;
      }

      if (mounted.current) {
        setLoading(false);
      }
    }
  }, [campusCode, zone, limit]);

  useEffect(() => {
    mounted.current = true;

    if (!enabled) {
      return () => {
        mounted.current = false;
      };
    }

    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const tick = async () => {
      await fetchOnce();

      if (cancelled) {
        return;
      }

      timer = setTimeout(tick, intervalMs);
    };

    tick();

    return () => {
      cancelled = true;
      mounted.current = false;

      if (timer !== null) {
        clearTimeout(timer);
      }

      inFlight.current?.abort();
      inFlight.current = null;
    };
  }, [enabled, intervalMs, fetchOnce]);

  return {
    data,
    readingsBySensorId: indexReadingsBySensor(data),
    loading: enabled && loading,
    error,
    refreshFailed,
    lastSuccessAt,
  };
}