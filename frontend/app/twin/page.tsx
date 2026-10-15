"use client";

import { useEffect, useState } from "react";

import {
  getCampusTwin,
  type CampusTwinData,
} from "@/lib/api";
import { useTelemetry } from "@/lib/useTelemetry";
import {
  formatReadingAge,
  newestTimestamp,
} from "@/lib/telemetry";
import { TWIN_CONFIG } from "@/lib/twin/config";

import TwinCanvas from "@/components/TwinCanvas";

export default function TwinPage() {
  const [twin, setTwin] =
    useState<CampusTwinData | null>(null);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await getCampusTwin(
          TWIN_CONFIG.campusCode,
        );

        if (!cancelled) {
          setTwin(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unknown error",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, []);

  const zone = twin?.zones.find(
    (item) => item.code === TWIN_CONFIG.zoneCode,
  );

  // One polling loop for this page. Readings refresh the
  // labels only; the scene geometry is untouched.
  const telemetry = useTelemetry({
    campusCode: TWIN_CONFIG.campusCode,
    zone: TWIN_CONFIG.zoneCode,
  });

  // Next 16 blocks Date.now() during prerender, so the clock
  // starts on the client and stays null until then.
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    // Deferred, not synchronous: a setState in the effect body
    // itself would cascade a render.
    const start = setTimeout(
      () => setNow(Date.now()),
      0,
    );

    const timer = setInterval(
      () => setNow(Date.now()),
      30_000,
    );

    return () => {
      clearTimeout(start);
      clearInterval(timer);
    };
  }, []);

  const dataAsOf = newestTimestamp(telemetry.data);

  return (
    <main className="flex h-screen flex-col bg-slate-950 text-white">
      <header className="z-10 flex flex-wrap items-center justify-between gap-4 border-b border-white/10 bg-slate-950/80 px-6 py-4 backdrop-blur-md">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.25em] text-cyan-400">
            Smart Campus Digital Twin
          </p>

          <h1 className="mt-1 text-xl font-semibold">
            {zone?.name ??
              "University Lecture Hall"}
          </h1>

          <p className="mt-1 text-xs text-slate-500">
            {twin
              ? [
                  twin.campus.code,
                  twin.buildings[0]?.code,
                  twin.floors[0]?.code,
                  zone?.code,
                ]
                  .filter(Boolean)
                  .join(" › ")
              : "Connecting to campus API..."}
          </p>
        </div>

        <div className="flex items-center gap-4">
          <Stat
            label="Sensors"
            value={twin?.sensors.length}
          />

          <Stat
            label="Equipment"
            value={twin?.equipment.length}
          />

          <Stat
            label="Incidents"
            value={twin?.incidents.length}
          />

          <Stat
            label="Readings"
            value={telemetry.data?.reading_count}
          />

          <span className="flex items-center gap-2 text-xs text-slate-400">
            <span
              className={`h-2 w-2 rounded-full ${
                error
                  ? "bg-red-400"
                  : "bg-emerald-400"
              }`}
            />

            {error
              ? "API offline"
              : loading
                ? "Connecting"
                : "Twin data loaded"}
          </span>

          <span className="text-right text-xs text-slate-500">
            {telemetry.loading
              ? "Loading telemetry..."
              : telemetry.refreshFailed
                ? "Telemetry refresh failed"
                : telemetry.error
                  ? "Telemetry unavailable"
                  : dataAsOf && now !== null
                    ? `Stored data as of ${formatReadingAge(dataAsOf, now)}`
                    : "No stored readings"}

            {telemetry.data?.readings.some(
              (reading) =>
                reading.source === "simulator",
            ) ? (
              <span className="ml-2 text-amber-400/90">
                simulated
              </span>
            ) : null}
          </span>
        </div>
      </header>

      <div className="relative h-full flex-1">
        {twin && (
          <TwinCanvas
            sensors={twin.sensors}
            equipment={twin.equipment}
            readings={telemetry.readingsBySensorId}
            now={now}
          />
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center p-6">
            <div className="max-w-lg rounded-2xl border border-red-900 bg-red-950/40 p-6 text-center">
              <h2 className="text-lg font-semibold">
                Campus API unavailable
              </h2>

              <p className="mt-2 text-sm text-red-300">
                {error}
              </p>

              <p className="mt-4 text-sm text-zinc-400">
                Start the backend, then run{" "}
                <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-xs">
                  backend/migrations/001_smart_campus.sql
                </code>{" "}
                and{" "}
                <code className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-xs">
                  002_seed_smart_campus.sql
                </code>{" "}
                in the Supabase SQL editor.
              </p>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function Stat({
  label,
  value,
}: {
  label: string;
  value?: number;
}) {
  return (
    <div className="text-right">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </p>

      <p className="text-lg font-semibold tabular-nums">
        {value ?? "-"}
      </p>
    </div>
  );
}
