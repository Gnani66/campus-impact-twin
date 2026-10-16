"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  getDigitalTwinSnapshot,
  getIncidentSummary,
  getIncidents,
} from "@/lib/api";

import type { Incident, IncidentSummary } from "@/lib/types";
import type {
  TwinEntity,
  TwinSnapshot,
} from "@/lib/twin-state";
import { toTwinEntity } from "@/lib/twin-state";

/**
 * Dashboard data.
 *
 * ONE POLL LOOP, THREE READS.
 *
 * The twin snapshot is the expensive read - it renders geometry -
 * so it polls on its own short interval and the cheaper incident
 * reads ride along at a slower cadence. Three components each
 * polling the same endpoint would be three times the load and three
 * chances for the header and the body to disagree about what is
 * open.
 *
 * Nothing here is derived for effect. Counts come from the
 * endpoints that count; entity status arrives decided by the
 * backend. The only computation is grouping and sorting, both pure.
 */

const SNAPSHOT_POLL_MS = 5_000;
const INCIDENT_POLL_MS = 15_000;

export interface DashboardData {
  snapshot: TwinSnapshot | null;
  entities: TwinEntity[];
  incidents: Incident[];
  summary: IncidentSummary | null;

  /** Last successful read, used to label staleness honestly. */
  lastUpdated: string | null;

  loading: boolean;
  error: string | null;

  /** True when a refresh failed but earlier data is still shown. */
  stale: boolean;

  select: (entityId: string | null) => void;
  selected: TwinEntity | null;
  refresh: () => void;
}

export function useDashboardData(): DashboardData {
  const [snapshot, setSnapshot] = useState<TwinSnapshot | null>(
    null,
  );
  const [entities, setEntities] = useState<TwinEntity[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [summary, setSummary] = useState<IncidentSummary | null>(
    null,
  );

  const [lastUpdated, setLastUpdated] = useState<string | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(
    null,
  );

  const [nonce, setNonce] = useState(0);

  const select = useCallback((entityId: string | null) => {
    setSelectedId(entityId);
  }, []);

  const refresh = useCallback(() => {
    setNonce((value) => value + 1);
  }, []);

  // --- the twin ------------------------------------------------
  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    async function read() {
      try {
        const wire = await getDigitalTwinSnapshot(
          controller.signal,
        );

        if (!active) {
          return;
        }

        const next = wire.entities.map(toTwinEntity);

        setSnapshot({
          timestamp: wire.timestamp,
          entities: next,
          counts: wire.counts ?? {},
        });

        setEntities(next);
        setLastUpdated(new Date().toISOString());
        setError(null);
        setStale(false);
      } catch (err) {
        if (!active) {
          return;
        }

        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }

        // Keep the last good snapshot on screen. Blanking the twin
        // because one request failed would destroy the operator's
        // context at exactly the moment something has gone wrong.
        setStale(true);
        setError(
          err instanceof Error
            ? err.message
            : "The digital twin could not be refreshed.",
        );
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    async function loop() {
      await read();

      const interval = setInterval(read, SNAPSHOT_POLL_MS);

      return () => clearInterval(interval);
    }

    let dispose: (() => void) | undefined;

    void loop().then((cleanup) => {
      dispose = cleanup;
    });

    return () => {
      active = false;
      dispose?.();
      controller.abort();
    };
  }, [nonce]);

  // --- incidents and counts ------------------------------------
  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    async function read() {
      try {
        const [rows, counts] = await Promise.all([
          getIncidents({ limit: 100 }, controller.signal),
          getIncidentSummary("CIT-MAIN", controller.signal),
        ]);

        if (!active) {
          return;
        }

        setIncidents(rows);
        setSummary(counts);
      } catch (err) {
        if (!active) {
          return;
        }

        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }

        // The incident panel says so itself; the twin keeps
        // working, and this read is not allowed to take the whole
        // dashboard down with it.
        setError(
          err instanceof Error
            ? err.message
            : "Incidents could not be refreshed.",
        );
      }
    }

    async function loop() {
      await read();

      const interval = setInterval(read, INCIDENT_POLL_MS);

      return () => clearInterval(interval);
    }

    let dispose: (() => void) | undefined;

    void loop().then((cleanup) => {
      dispose = cleanup;
    });

    return () => {
      active = false;
      dispose?.();
      controller.abort();
    };
  }, [nonce]);

  const selected = useMemo(
    () =>
      selectedId
        ? (entities.find(
            (entity) => entity.id === selectedId,
          ) ?? null)
        : null,
    [entities, selectedId],
  );

  return {
    snapshot,
    entities,
    incidents,
    summary,
    lastUpdated,
    loading,
    error,
    stale,
    select,
    selected,
    refresh,
  };
}
