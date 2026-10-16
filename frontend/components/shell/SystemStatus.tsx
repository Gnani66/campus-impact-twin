"use client";

import { useEffect, useState } from "react";

import { getIncidentSummary } from "@/lib/api";

/**
 * The sidebar's system line.
 *
 * It reports what the API can actually see, and the most important
 * state is the one where nothing is known.
 *
 * "Operational" is never inferred from silence. If the summary
 * request fails, this says the status is unknown rather than
 * falling back to a reassuring green, because a monitoring strip
 * that hides its own blindness is worse than no strip at all.
 */

type Verdict =
  | { state: "critical"; label: string; detail: string }
  | { state: "warning"; label: string; detail: string }
  | { state: "healthy"; label: string; detail: string }
  | { state: "unknown"; label: string; detail: string };

const POLL_INTERVAL_MS = 30_000;

export function SystemStatus() {
  const [verdict, setVerdict] = useState<Verdict>({
    state: "unknown",
    label: "Checking",
    detail: "Contacting the campus API",
  });

  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    async function read() {
      try {
        const summary = await getIncidentSummary(
          "CIT-MAIN",
          controller.signal,
        );

        if (!active) {
          return;
        }

        if (summary.open_incidents === 0) {
          setVerdict({
            state: "healthy",
            label: "System operational",
            detail: "No open incidents",
          });

          return;
        }

        if (summary.critical > 0) {
          setVerdict({
            state: "critical",
            label: "Needs attention",
            detail: `${summary.open_incidents} open · ${summary.critical} critical`,
          });

          return;
        }

        setVerdict({
          state: "warning",
          label: "Watching",
          detail: `${summary.open_incidents} open incidents`,
        });
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

        setVerdict({
          state: "unknown",
          label: "Status unknown",
          detail: "The campus API is not responding",
        });
      }
    }

    async function load() {
      await read();

      const interval = setInterval(
        read,
        POLL_INTERVAL_MS,
      );

      return () => clearInterval(interval);
    }

    let dispose: (() => void) | undefined;

    void load().then((cleanup) => {
      dispose = cleanup;
    });

    return () => {
      active = false;
      dispose?.();
      controller.abort();
    };
  }, []);

  const dot = {
    healthy: "bg-healthy",
    warning: "bg-warning",
    critical: "bg-critical",
    unknown: "bg-offline",
  }[verdict.state];

  return (
    <div
      className="rounded-lg border bg-card px-3 py-2.5"
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={`size-2 shrink-0 rounded-full ${dot}`}
        />

        <p className="truncate text-xs font-medium">
          {verdict.label}
        </p>
      </div>

      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
        {verdict.detail}
      </p>
    </div>
  );
}
