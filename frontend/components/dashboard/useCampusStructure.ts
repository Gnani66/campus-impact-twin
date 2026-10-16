"use client";

import { useEffect, useState } from "react";

import { getCampusTwin } from "@/lib/api";

import type { CampusStructure } from "./CampusMetrics";

/**
 * Structural counts for the campus: buildings, zones, sensors,
 * equipment.
 *
 * FETCHED ONCE, NOT POLLED.
 *
 * This is the shape of the campus, not its state, and it changes
 * when someone builds a room rather than every five seconds.
 * Polling it would put a 19 kB request on the wire forever for a
 * number that is almost always identical.
 */

export function useCampusStructure(): {
  structure: CampusStructure | null;
  error: string | null;
} {
  const [structure, setStructure] =
    useState<CampusStructure | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    async function read() {
      try {
        const twin = await getCampusTwin(
          "CIT-MAIN",
          controller.signal,
        );

        if (!active) {
          return;
        }

        setStructure({
          buildings: twin.buildings.length,
          zones: twin.zones.length,
          sensors: twin.sensors.length,
          equipment: twin.equipment.length,
        });

        setError(null);
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

        setError(
          err instanceof Error
            ? err.message
            : "The campus record could not be read.",
        );
      }
    }

    void read();

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  return { structure, error };
}
