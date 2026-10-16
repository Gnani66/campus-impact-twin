"use client";

import { useEffect, useState } from "react";

import { getIncidentSummary } from "@/lib/api";

/**
 * The LIVE indicator.
 *
 * "Live" here means one thing only: the backend answered just now.
 * It is not a claim that a sensor is producing data, and not a
 * WebSocket that may not be there - the polling interval is stated
 * on the tooltip so nobody has to guess how fresh this is.
 *
 * When the API cannot be reached the badge says so instead of
 * quietly going stale, because an indicator frozen on "LIVE" while
 * the backend is down is actively misleading.
 */

const POLL_INTERVAL_MS = 30_000;

export function LiveIndicator() {
  const [state, setState] = useState<
    "checking" | "live" | "down"
  >("checking");

  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    async function probe() {
      try {
        await getIncidentSummary(
          "CIT-MAIN",
          controller.signal,
        );

        if (active) {
          setState("live");
        }
      } catch (err) {
        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }

        if (active) {
          setState("down");
        }
      }
    }

    async function loop() {
      await probe();

      const interval = setInterval(
        probe,
        POLL_INTERVAL_MS,
      );

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
  }, []);

  const config = {
    checking: {
      label: "Checking",
      dot: "bg-offline",
      text: "text-muted-foreground",
      title: "Contacting the campus API",
    },
    live: {
      label: "Live",
      dot: "bg-healthy animate-pulse",
      text: "text-healthy",
      title:
        "The campus API answered moments ago. Readings refresh on their own interval.",
    },
    down: {
      label: "API unreachable",
      dot: "bg-critical",
      text: "text-critical",
      title:
        "The campus API is not responding. Values on screen are the last known ones.",
    },
  }[state];

  return (
    <span
      title={config.title}
      className={`inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-[11px] font-medium ${config.text}`}
    >
      <span
        aria-hidden
        className={`size-1.5 rounded-full ${config.dot}`}
      />

      {config.label}

      <span className="sr-only">
        {" "}
        - {config.title}
      </span>
    </span>
  );
}
