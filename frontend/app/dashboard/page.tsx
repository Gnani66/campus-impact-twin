"use client";

import { useEffect, useState } from "react";

import {
  getCampusTwin,
  type CampusTwinData,
} from "@/lib/api";
import { TWIN_CONFIG } from "@/lib/twin/config";

export default function DashboardPage() {
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

  if (loading) {
    return (
      <main className="min-h-screen bg-slate-950 p-8 text-white">
        <p className="text-slate-400">
          Loading campus twin...
        </p>
      </main>
    );
  }

  if (error || !twin) {
    return (
      <main className="min-h-screen bg-slate-950 p-8 text-white">
        <div className="max-w-xl rounded-2xl border border-red-900 bg-red-950/30 p-6">
          <h1 className="text-xl font-semibold">
            Campus API unavailable
          </h1>

          <p className="mt-2 text-sm text-red-300">
            {error}
          </p>

          <p className="mt-4 text-sm text-slate-400">
            Make sure the FastAPI server is running on
            port 8000.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 p-6 text-white lg:p-10">
      <div className="mx-auto max-w-7xl">
        <header>
          <p className="text-sm uppercase tracking-[0.25em] text-emerald-400">
            Smart Campus Digital Twin
          </p>

          <h1 className="mt-3 text-4xl font-semibold">
            {twin.campus.name}
          </h1>

          <p className="mt-3 max-w-2xl text-slate-400">
            {twin.campus.description}
          </p>
        </header>

        <section className="mt-10 grid gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Metric
            label="Buildings"
            value={twin.buildings.length}
          />

          <Metric
            label="Floors"
            value={twin.floors.length}
          />

          <Metric
            label="Zones"
            value={twin.zones.length}
          />

          <Metric
            label="Equipment"
            value={twin.equipment.length}
          />

          <Metric
            label="Sensors"
            value={twin.sensors.length}
          />

          <Metric
            label="Incidents"
            value={twin.incidents.length}
          />
        </section>

        <section className="mt-10 grid gap-6 lg:grid-cols-2">
          <Panel title="Hierarchy">
            <Breadcrumb
              code={twin.campus.code}
              name={twin.campus.name}
            />

            {twin.buildings.map((building) => (
              <Breadcrumb
                key={building.id}
                code={building.code}
                name={building.name}
              />
            ))}

            {twin.floors.map((floor) => (
              <Breadcrumb
                key={floor.id}
                code={floor.code}
                name={floor.name}
              />
            ))}

            {twin.zones.map((zone) => (
              <Breadcrumb
                key={zone.id}
                code={zone.code}
                name={zone.name}
                detail={[
                  zone.zone_type,
                  zone.capacity !== null
                    ? `${zone.capacity} seats`
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              />
            ))}
          </Panel>

          <Panel title="Sensors">
            <ul className="space-y-3">
              {twin.sensors.map((sensor) => (
                <li
                  key={sensor.id}
                  className="rounded-xl border border-slate-800 bg-slate-950 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">
                      {sensor.code}
                    </span>

                    <span className="text-xs uppercase text-cyan-400">
                      {sensor.sensor_type}
                    </span>
                  </div>

                  <p className="mt-1 text-sm text-slate-500">
                    {sensor.name}
                    {sensor.unit
                      ? ` · ${sensor.unit}`
                      : ""}
                    {sensor.sampling_interval_seconds
                      ? ` · every ${sensor.sampling_interval_seconds}s`
                      : ""}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Equipment">
            <ul className="space-y-3">
              {twin.equipment.map((item) => (
                <li
                  key={item.id}
                  className="rounded-xl border border-slate-800 bg-slate-950 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">
                      {item.code}
                    </span>

                    <span className="text-xs uppercase text-amber-400">
                      {item.equipment_type}
                    </span>
                  </div>

                  <p className="mt-1 text-sm text-slate-500">
                    {item.name}
                    {item.rated_power_kw !==
                    null
                      ? ` · ${item.rated_power_kw} kW rated`
                      : ""}
                  </p>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Incidents">
            {twin.incidents.length === 0 ? (
              <p className="text-sm text-slate-500">
                No incidents detected.
              </p>
            ) : (
              <ul className="space-y-3">
                {twin.incidents.map((incident) => (
                  <li
                    key={incident.id}
                    className="rounded-xl border border-slate-800 bg-slate-950 p-4"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium">
                          {incident.title}
                        </p>

                        <p className="mt-1 text-sm text-slate-500">
                          {incident.description}
                        </p>
                      </div>

                      <span className="shrink-0 rounded-full border border-amber-700/50 px-3 py-1 text-xs uppercase text-amber-400">
                        {incident.severity}
                      </span>
                    </div>

                    <p className="mt-3 text-xs text-slate-500">
                      {incident.category} · impact{" "}
                      {incident.impact_score}/100
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </section>
      </div>
    </main>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <p className="text-sm text-slate-500">
        {label}
      </p>

      <p className="mt-2 text-3xl font-semibold tabular-nums">
        {value}
      </p>
    </div>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
      <h2 className="text-lg font-semibold">
        {title}
      </h2>

      <div className="mt-5 space-y-3">
        {children}
      </div>
    </div>
  );
}

function Breadcrumb({
  code,
  name,
  detail,
}: {
  code: string;
  name: string;
  detail?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950 p-4">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">
          {name}
        </span>

        <span className="text-xs uppercase text-slate-500">
          {code}
        </span>
      </div>

      {detail && (
        <p className="mt-1 text-sm text-slate-500">
          {detail}
        </p>
      )}
    </div>
  );
}
