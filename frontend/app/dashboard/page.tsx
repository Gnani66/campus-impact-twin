"use client";

import { useEffect, useState } from "react";

import type {
  Building,
  Incident,
  Zone,
} from "@/lib/types";

interface CampusResponse {
  buildings: Building[];
  zones: Zone[];
  incidents: Incident[];
}

export default function DashboardPage() {
  const [campus, setCampus] =
    useState<CampusResponse | null>(null);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    async function loadCampus() {
      try {
        const response = await fetch(
          `${
            process.env.NEXT_PUBLIC_API_URL ??
            "http://localhost:8000"
          }/api/v1/campus`,
        );

        if (!response.ok) {
          throw new Error(
            "Failed to load campus data.",
          );
        }

        const payload = await response.json();

        if (!payload.success) {
          throw new Error(
            payload.error?.message ??
              "Backend request failed.",
          );
        }

        setCampus(payload.data);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unknown error",
        );
      } finally {
        setLoading(false);
      }
    }

    loadCampus();
  }, []);

  if (loading) {
    return (
      <main className="min-h-screen bg-zinc-950 p-8 text-white">
        <p className="text-zinc-400">
          Loading campus state...
        </p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen bg-zinc-950 p-8 text-white">
        <div className="rounded-2xl border border-red-900 bg-red-950/30 p-6">
          <h1 className="text-xl font-semibold">
            Backend connection failed
          </h1>

          <p className="mt-2 text-sm text-red-300">
            {error}
          </p>

          <p className="mt-4 text-sm text-zinc-400">
            Make sure the FastAPI server is running
            on port 8000.
          </p>
        </div>
      </main>
    );
  }

  if (!campus) {
    return null;
  }

  return (
    <main className="min-h-screen bg-zinc-950 p-6 text-white lg:p-10">
      <div className="mx-auto max-w-7xl">
        <header>
          <p className="text-sm uppercase tracking-[0.25em] text-emerald-400">
            Campus Impact Twin
          </p>

          <h1 className="mt-3 text-4xl font-semibold">
            Command Centre
          </h1>

          <p className="mt-3 max-w-2xl text-zinc-400">
            Live operational state from the Campus
            Impact Twin backend.
          </p>
        </header>

        <section className="mt-10 grid gap-4 sm:grid-cols-3">
          <Metric
            label="Buildings"
            value={campus.buildings.length}
          />

          <Metric
            label="Zones"
            value={campus.zones.length}
          />

          <Metric
            label="Open incidents"
            value={campus.incidents.length}
          />
        </section>

        <section className="mt-10 grid gap-6 lg:grid-cols-2">
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
            <h2 className="text-lg font-semibold">
              Campus zones
            </h2>

            <div className="mt-5 space-y-3">
              {campus.zones.map((zone) => (
                <div
                  key={zone.id}
                  className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">
                      {zone.name}
                    </span>

                    <span className="text-xs uppercase text-zinc-500">
                      {zone.code}
                    </span>
                  </div>

                  <p className="mt-1 text-sm text-zinc-500">
                    {zone.type.replace(
                      "_",
                      " ",
                    )}{" "}
                    · Floor {zone.floor}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
            <h2 className="text-lg font-semibold">
              Priority incidents
            </h2>

            <div className="mt-5 space-y-3">
              {campus.incidents.map(
                (incident) => (
                  <div
                    key={incident.id}
                    className="rounded-xl border border-zinc-800 bg-zinc-950 p-4"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="font-medium">
                          {incident.title}
                        </h3>

                        <p className="mt-1 text-sm text-zinc-500">
                          {incident.description}
                        </p>
                      </div>

                      <span className="shrink-0 rounded-full border border-amber-700/50 px-3 py-1 text-xs uppercase text-amber-400">
                        {incident.severity}
                      </span>
                    </div>

                    <div className="mt-4">
                      <div className="flex justify-between text-xs text-zinc-500">
                        <span>
                          Business impact
                        </span>

                        <span>
                          {incident.impactScore}/100
                        </span>
                      </div>

                      <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-800">
                        <div
                          className="h-full rounded-full bg-amber-400"
                          style={{
                            width: `${incident.impactScore}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>
                ),
              )}

              {campus.incidents.length === 0 && (
                <p className="text-sm text-zinc-500">
                  No open incidents.
                </p>
              )}
            </div>
          </div>
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
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-6">
      <p className="text-sm text-zinc-500">
        {label}
      </p>

      <p className="mt-3 text-4xl font-semibold">
        {value}
      </p>
    </div>
  );
}