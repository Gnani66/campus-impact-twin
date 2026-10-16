"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CampusScene } from "./CampusScene";
import { EntityList } from "./EntityList";
import { EntityPanel } from "./EntityPanel";
import { TwinLegend } from "./TwinLegend";

import { TWIN_POLL_INTERVAL_MS, getDigitalTwinSnapshot } from "@/lib/api";

import {
  toTwinEntity,
  type TwinEntity,
  type TwinSnapshot,
} from "@/lib/twin-state";

/**
 * The live digital twin.
 *
 * POLLING, NOT A FAKE SOCKET.
 *
 * There is no WebSocket here, so nothing pretends to be one.
 * A connection that claims to be live but is polling behind a
 * websocket API is worse than an honest interval, because it
 * invites the reader to trust freshness the code cannot promise.
 *
 * A failed refresh keeps the last good snapshot on screen and
 * reports the failure. Blanking the view because one request
 * failed would destroy the operator's context at exactly the
 * moment something has gone wrong.
 */
export function DigitalTwin() {
  const [snapshot, setSnapshot] = useState<TwinSnapshot | null>(null);

  const [entities, setEntities] = useState<TwinEntity[]>([]);

  const [selected, setSelected] = useState<TwinEntity | null>(null);

  const [error, setError] = useState<string | null>(null);

  const [stale, setStale] = useState(false);

  // Tracks whether the effect is still live, so an in-flight
  // response cannot set state after unmount.
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;

    const controller = new AbortController();

    async function load() {
      try {
        const wire = await getDigitalTwinSnapshot(controller.signal);

        if (!mounted.current) {
          return;
        }

        const next = wire.entities.map(toTwinEntity);

        setSnapshot({
          timestamp: wire.timestamp,
          entities: next,
          counts: wire.counts ?? {},
        });

        setEntities(next);
        setError(null);
        setStale(false);

        // Keeps the open panel current as readings change,
        // rather than freezing at whatever it showed when it was
        // clicked.
        setSelected((current) => {
          if (!current) {
            return current;
          }

          return next.find((entity) => entity.id === current.id) ?? current;
        });
      } catch (err) {
        if (!mounted.current) {
          return;
        }

        if (err instanceof DOMException && err.name === "AbortError") {
          return;
        }

        setStale(true);
        setError(
          err instanceof Error
            ? err.message
            : "Unable to load the digital twin.",
        );
      }
    }

    load();

    const interval = setInterval(load, TWIN_POLL_INTERVAL_MS);

    return () => {
      mounted.current = false;
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  const handleSelect = useCallback((entity: TwinEntity | null) => {
    setSelected(entity);
  }, []);

  return (
    <div className="relative h-full">
      <CampusScene
        entities={entities}
        selectedId={selected?.id ?? null}
        onSelect={handleSelect}
      />

      <EntityList
        entities={entities}
        selectedId={selected?.id ?? null}
        onSelect={handleSelect}
      />

      <EntityPanel entity={selected} />

      <TwinLegend counts={snapshot?.counts} />

      {error && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 rounded-xl bg-red-950/90 px-4 py-3 text-sm text-red-200 shadow-lg">
          {stale ? `${error} — showing the last known state.` : error}
        </div>
      )}

      <div className="absolute right-6 bottom-6 rounded-xl bg-slate-950/90 px-4 py-3 text-xs text-slate-300 backdrop-blur">
        {entities.length} campus entities
        {snapshot && (
          <span className="ml-2 text-slate-500">
            as of {new Date(snapshot.timestamp).toLocaleTimeString()}
          </span>
        )}
      </div>
    </div>
  );
}
