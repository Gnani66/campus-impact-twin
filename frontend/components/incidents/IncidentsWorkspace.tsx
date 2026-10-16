"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getIncidentSummary,
  getIncidents,
} from "@/lib/api";
import type {
  Incident,
  IncidentSummary,
} from "@/lib/types";

interface IncidentsWorkspaceProps {
  /**
   * Zone code from the URL, for example LH01.
   *
   * The twin's entity panel links here with `?zone=<code>`, which
   * is how a person arrives at "the problems in this room" rather
   * than at the whole campus.
   */
  zone: string | null;
}

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "investigating", label: "Investigating" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Dismissed" },
];

const SEVERITY_OPTIONS = [
  { value: "", label: "All severities" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
];

const SEVERITY_STYLES: Record<string, string> = {
  critical: "border-red-700/60 bg-red-950/40 text-red-300",
  high: "border-amber-700/50 bg-amber-950/30 text-amber-300",
  medium: "border-sky-700/50 bg-sky-950/30 text-sky-300",
  low: "border-slate-700 bg-slate-900 text-slate-400",
};

const STATUS_STYLES: Record<string, string> = {
  open: "text-rose-300",
  acknowledged: "text-amber-300",
  investigating: "text-sky-300",
  resolved: "text-emerald-300",
  dismissed: "text-slate-500",
};

/**
 * The incidents page body.
 *
 * READ-ONLY BY DESIGN.
 *
 * An incident is a record of something the rules already decided,
 * so nothing on this page can change one. Acknowledging or closing
 * an incident is a decision about real work, and the twin already
 * decides statuses from stored readings; a button here would look
 * like the same authority and would not be.
 *
 * Filters are sent to the backend rather than applied here, so the
 * count shown is the count that exists.
 */
export function IncidentsWorkspace({
  zone,
}: IncidentsWorkspaceProps) {
  const [incidents, setIncidents] = useState<
    Incident[] | null
  >(null);
  const [summary, setSummary] = useState<
    IncidentSummary | null
  >(null);
  const [status, setStatus] = useState("");
  const [severity, setSeverity] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (signal: AbortSignal) => {
      setLoading(true);

      try {
        // The summary describes the whole campus, so it is
        // deliberately not narrowed by the filters below. Mixing
        // the two would put "8 open" above a list showing one.
        const [rows, counts] = await Promise.all([
          getIncidents(
            {
              status: status || null,
              severity: severity || null,
              zone,
              limit: 200,
            },
            signal,
          ),
          getIncidentSummary(
            "CIT-MAIN",
            signal,
          ),
        ]);

        setIncidents(rows);
        setSummary(counts);
        setError(null);
      } catch (err) {
        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }

        setError(
          err instanceof Error
            ? err.message
            : "Incidents could not be loaded.",
        );
      } finally {
        setLoading(false);
      }
    },
    [status, severity, zone],
  );

  useEffect(() => {
    let active = true;

    const controller = new AbortController();

    void (async () => {
      await load(controller.signal);

      if (!active) {
        return;
      }
    })();

    return () => {
      active = false;
      controller.abort();
    };
  }, [load]);

  return (
    <div className="space-y-8">
      {summary && (
        <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric
            label="Open now"
            value={summary.open_incidents}
            hint="Open, acknowledged or under investigation"
          />

          <Metric
            label="Critical"
            value={summary.critical}
            hint="Ever recorded at critical severity"
          />

          <Metric
            label="Highest impact"
            value={`${summary.highest_impact}/100`}
            hint="Worst single incident"
          />

          <Metric
            label="Recorded"
            value={summary.total_incidents}
            hint="Including resolved and dismissed"
          />
        </section>
      )}

      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
        <div className="flex flex-wrap items-end gap-4">
          <Filter
            label="Status"
            value={status}
            options={STATUS_OPTIONS}
            onChange={setStatus}
          />

          <Filter
            label="Severity"
            value={severity}
            options={SEVERITY_OPTIONS}
            onChange={setSeverity}
          />

          {zone && (
            <p className="pb-2 text-sm text-slate-400">
              Showing zone{" "}
              <span className="font-semibold text-white">
                {zone}
              </span>
            </p>
          )}

          <p className="ml-auto pb-2 text-sm text-slate-500">
            {loading
              ? "Loading..."
              : `${incidents?.length ?? 0} shown`}
          </p>
        </div>
      </section>

      {error && (
        <div className="rounded-2xl border border-red-900 bg-red-950/30 p-6">
          <p className="text-sm text-red-300">
            Incidents are unavailable: {error}
          </p>
        </div>
      )}

      <section className="space-y-3">
        {!incidents && !error && (
          <p className="text-sm text-slate-500">
            Loading incidents...
          </p>
        )}

        {incidents && incidents.length === 0 && (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
            <p className="text-sm text-slate-500">
              No incidents match these filters.
            </p>
          </div>
        )}

        {incidents?.map((incident) => (
          <IncidentCard
            key={incident.id}
            incident={incident}
          />
        ))}
      </section>
    </div>
  );
}

/**
 * One incident.
 *
 * The evidence is shown as the count of observations it holds
 * rather than expanded: an incident can carry fifty readings, and
 * the copilot is the place that reads them in full. Printing a
 * hundred rows of numbers here would bury the title.
 */
function IncidentCard({
  incident,
}: {
  incident: Incident;
}) {
  const [expanded, setExpanded] = useState(false);

  const observations =
    incident.evidence[0] &&
    typeof incident.evidence[0] === "object" &&
    incident.evidence[0] !== null &&
    Array.isArray(
      (
        incident.evidence[0] as {
          observations?: unknown[];
        }
      ).observations,
    )
      ? (
          incident.evidence[0] as {
            observations: unknown[];
          }
        ).observations.length
      : 0;

  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">{incident.title}</h3>

          <p className="mt-1 text-sm text-slate-400">
            {incident.description}
          </p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <span
            className={`rounded-full border px-3 py-1 text-xs uppercase ${
              SEVERITY_STYLES[incident.severity] ??
              SEVERITY_STYLES.low
            }`}
          >
            {incident.severity}
          </span>

          <span
            className={`text-xs uppercase ${
              STATUS_STYLES[incident.status] ??
              "text-slate-400"
            }`}
          >
            {incident.status}
          </span>
        </div>
      </div>

      <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-xs text-slate-500">
        <Detail
          label="Zone"
          value={incident.zone_code ?? "not attributed"}
        />

        <Detail label="Category" value={incident.category} />

        <Detail
          label="Impact"
          value={`${incident.impact_score}/100`}
        />

        <Detail
          label="Detected"
          value={new Date(
            incident.detected_at,
          ).toLocaleString()}
        />

        <Detail
          label="Method"
          value={incident.detection_method.replace(
            /_/g,
            " ",
          )}
        />

        {observations > 0 && (
          <Detail
            label="Observations"
            value={String(observations)}
          />
        )}
      </dl>

      {observations > 0 && (
        <>
          <button
            type="button"
            onClick={() => setExpanded((open) => !open)}
            className="mt-4 text-xs text-slate-400 underline decoration-slate-700 underline-offset-4 hover:text-white"
          >
            {expanded
              ? "Hide readings"
              : `Show the ${observations} readings behind this`}
          </button>

          {expanded && (
            <EvidencePanel evidence={incident.evidence} />
          )}
        </>
      )}
    </article>
  );
}

/**
 * The readings an incident was raised from.
 *
 * Rendered from stored evidence only. If a value is not there, the
 * row is not drawn: an incident panel that filled a gap would be
 * showing a number nobody measured.
 */
function EvidencePanel({
  evidence,
}: {
  evidence: unknown[];
}) {
  const record = evidence[0];

  if (
    typeof record !== "object" ||
    record === null
  ) {
    return null;
  }

  const observations = (
    record as { observations?: unknown[] }
  ).observations;

  if (!Array.isArray(observations)) {
    return null;
  }

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-slate-500">
          <tr>
            <th className="py-2 pr-4 font-normal">
              Observed
            </th>
            <th className="py-2 pr-4 font-normal">
              Metric
            </th>
            <th className="py-2 pr-4 font-normal">
              Value
            </th>
            <th className="py-2 font-normal">Impact</th>
          </tr>
        </thead>

        <tbody className="tabular-nums">
          {observations.map((entry, index) => {
            if (
              typeof entry !== "object" ||
              entry === null
            ) {
              return null;
            }

            const row = entry as {
              observed_at?: unknown;
              metric?: unknown;
              value?: unknown;
              impact_score?: unknown;
            };

            return (
              <tr
                key={index}
                className="border-t border-slate-800 text-slate-300"
              >
                <td className="py-2 pr-4">
                  {typeof row.observed_at === "string"
                    ? new Date(
                        row.observed_at,
                      ).toLocaleString()
                    : "—"}
                </td>

                <td className="py-2 pr-4">
                  {typeof row.metric === "string"
                    ? row.metric
                    : "—"}
                </td>

                <td className="py-2 pr-4">
                  {typeof row.value === "number"
                    ? row.value
                    : "—"}
                </td>

                <td className="py-2">
                  {typeof row.impact_score ===
                  "number"
                    ? row.impact_score
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  hint?: string;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <p className="text-sm text-slate-500">{label}</p>

      <p className="mt-2 text-3xl font-semibold tabular-nums">
        {value}
      </p>

      {hint && (
        <p className="mt-1 text-xs text-slate-600">
          {hint}
        </p>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div>
      <dt className="uppercase tracking-wider">
        {label}
      </dt>

      <dd className="mt-1 text-slate-300">{value}</dd>
    </div>
  );
}

function Filter({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (next: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-xs uppercase tracking-wider text-slate-500">
        {label}
      </span>

      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
      >
        {options.map((option) => (
          <option
            key={option.value || "any"}
            value={option.value}
          >
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
