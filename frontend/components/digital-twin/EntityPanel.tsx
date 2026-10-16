"use client";

import Link from "next/link";

import {
  formatMetric,
  formatOccupancyRatio,
  getEntityTypeLabel,
  getStatusColor,
  getStatusLabel,
} from "@/lib/digital-twin";

import type { TwinEntity } from "@/lib/twin-state";

interface EntityPanelProps {
  entity: TwinEntity | null;
}

/**
 * The detail panel for a selected entity.
 *
 * Every metric renders through `formatMetric`, so a sensor this
 * deployment does not have shows as a dash. Showing a plausible
 * number there would be the most misleading thing on the screen,
 * because the reader has no way to tell an invented value from a
 * measured one.
 */
export function EntityPanel({ entity }: EntityPanelProps) {
  if (!entity) {
    return (
      <aside className="absolute right-6 top-6 w-80 rounded-2xl border border-white/10 bg-slate-950/90 p-5 text-white shadow-2xl backdrop-blur">
        <p className="text-sm text-slate-400">
          Select a campus entity to inspect its live operational data.
        </p>

        <p className="mt-4 text-xs leading-relaxed text-slate-500">
          Status is decided on the backend from stored sensor readings. A marker
          shown grey means telemetry has stopped, not that the room is healthy.
        </p>
      </aside>
    );
  }

  const color = getStatusColor(entity.status);

  const metrics = entity.metrics;

  return (
    <aside className="absolute right-6 top-6 max-h-[calc(100vh-6rem)] w-80 overflow-y-auto rounded-2xl border border-white/10 bg-slate-950/95 p-5 text-white shadow-2xl backdrop-blur">
      <div className="mb-5">
        <p className="text-xs uppercase tracking-widest text-slate-400">
          {getEntityTypeLabel(entity.type)}
        </p>

        <h2 className="mt-1 text-xl font-semibold">{entity.name}</h2>

        <p className="text-xs text-slate-500">{entity.code}</p>

        <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-white/5 px-3 py-1 text-xs font-medium">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: color }}
          />

          {getStatusLabel(entity.status)}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Metric
          label="Temperature"
          value={formatMetric(metrics.temperature, "°C")}
        />

        <Metric label="Humidity" value={formatMetric(metrics.humidity, "%")} />

        <Metric label="CO2" value={formatMetric(metrics.eco2, "ppm", 0)} />

        <Metric
          label="Occupancy"
          value={formatMetric(metrics.occupancy, "people", 0)}
        />

        <Metric
          label="Of capacity"
          value={formatOccupancyRatio(metrics.occupancy_ratio)}
        />

        <Metric label="Energy" value={formatMetric(metrics.energy, "kW", 2)} />

        {/* Declared by the contract, not currently measured. */}
        <Metric label="AQI" value={formatMetric(metrics.aqi)} />

        <Metric label="Noise" value={formatMetric(metrics.sound, "dB")} />
      </div>

      <p className="mt-3 text-[10px] leading-relaxed text-slate-500">
        A dash means this deployment has no sensor for that measurement. It is
        not a reading of zero.
      </p>

      {entity.reasons.length > 0 && (
        <Section title="Why this status">
          {entity.reasons.map((reason) => (
            <p
              key={reason}
              className="rounded-lg bg-white/5 px-3 py-2 text-sm text-slate-200"
            >
              {reason}
            </p>
          ))}
        </Section>
      )}

      {entity.activeIssues.length > 0 && (
        <Section
          title={`Active issues${
            entity.openIncidentCount > 0 ? ` (${entity.openIncidentCount})` : ""
          }`}
        >
          {entity.activeIssues.map((issue) => (
            <p
              key={issue}
              className="rounded-lg bg-white/5 px-3 py-2 text-sm text-slate-200"
            >
              {issue}
            </p>
          ))}
        </Section>
      )}

      {entity.correlationStatus && (
        <Section title="Latest analysis">
          <div className="rounded-lg bg-white/5 px-3 py-2 text-sm">
            <p className="text-slate-200">
              {entity.correlationStatus.replace(/_/g, " ")}
            </p>

            {entity.rootCause && (
              <p className="mt-1 text-xs text-slate-400">{entity.rootCause}</p>
            )}
          </div>
        </Section>
      )}

      <div className="mt-5 flex flex-wrap gap-2 border-t border-white/10 pt-4">
        <Link
          href={`/incidents?zone=${entity.code}`}
          className="rounded-lg bg-white/10 px-3 py-2 text-xs font-medium text-white transition hover:bg-white/20"
        >
          View Analysis
        </Link>

        {/*
          Opens the copilot already scoped to this zone. Passing
          the id rather than the name means the question the
          operator asks next is answered about this exact entity,
          and the backend resolves it against its own identifiers
          rather than trusting a label on the URL.
        */}
        <Link
          href={`/copilot?entity=${encodeURIComponent(entity.id)}`}
          className="rounded-lg bg-cyan-400/20 px-3 py-2 text-xs font-medium text-cyan-200 transition hover:bg-cyan-400/30"
        >
          Ask the copilot
        </Link>

        {entity.pendingApprovals > 0 && (
          <Link
            href="/approvals"
            className="rounded-lg bg-amber-500/20 px-3 py-2 text-xs font-medium text-amber-200 transition hover:bg-amber-500/30"
          >
            {entity.pendingApprovals} awaiting approval
          </Link>
        )}
      </div>
    </aside>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 border-t border-white/10 pt-4">
      <p className="mb-2 text-xs uppercase tracking-widest text-slate-400">
        {title}
      </p>

      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white/5 p-3">
      <p className="text-xs text-slate-400">{label}</p>

      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
