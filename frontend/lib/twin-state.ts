/**
 * Types for the live digital twin (Phase 12).
 *
 * This is the single frontend contract with the backend's
 * `/api/v1/digital-twin/snapshot` endpoint. Keeping it in one
 * file means a change to the contract surfaces as a type error
 * in one place rather than as `any` spreading through the 3D
 * components.
 *
 * The important convention: a metric of `null` means this
 * deployment does not measure it. That is different from zero,
 * and the UI must render it as a dash rather than substituting a
 * plausible number. This project has five measured metrics;
 * pressure, aqi, tvoc, light, sound and uv are declared because
 * the contract names them, and are always null until sensors
 * exist.
 */

export type TwinStatus = "normal" | "warning" | "critical" | "offline";

export type CampusEntityType =
  "building" | "lecture_hall" | "laboratory" | "library" | "hostel" | "other";

export interface TwinMetrics {
  temperature: number | null;
  humidity: number | null;
  pressure: number | null;
  aqi: number | null;
  tvoc: number | null;
  eco2: number | null;
  light: number | null;
  sound: number | null;
  uv: number | null;

  /** People counted. A headcount, not a percentage. */
  occupancy: number | null;

  /** Occupancy as a fraction of capacity. */
  occupancy_ratio: number | null;

  /** Instantaneous draw in kW. */
  energy: number | null;

  /** Seat count, needed to interpret the ratio. */
  capacity: number | null;
}

export interface TwinEntity {
  /** Stable, readable id. The React key and the URL segment. */
  id: string;

  /** Database authority, kept alongside the readable id. */
  zone_id: string;

  code: string;
  name: string;
  type: string;

  status: TwinStatus;

  metrics: TwinMetrics;

  /** Why it holds that status, in plain language. */
  reasons: string[];

  /** Open incidents and the latest correlation finding. */
  activeIssues: string[];

  openIncidentCount: number;

  /** Links onward into the decision loop. */
  correlationRunId: string | null;
  correlationStatus: string | null;
  rootCause: string | null;
  pendingApprovals: number;

  /** Object name inside the GLB, supplied by the database. */
  modelObject: string | null;

  position: [number, number, number] | null;
  scale: number | null;

  latitude: number | null;
  longitude: number | null;

  /** When these readings were taken. */
  observedAt: string | null;

  metadata: Record<string, unknown>;
}

export interface TwinSnapshot {
  timestamp: string;
  entities: TwinEntity[];
  counts: Partial<Record<TwinStatus, number>>;
}

/**
 * Raw wire shape from the backend.
 *
 * Separate from `TwinEntity` because the API uses snake_case and
 * the components use camelCase. Converting once, in one place,
 * means no component has to remember which convention it is
 * holding, and a rename on either side breaks the build rather
 * than producing `undefined` at runtime.
 */
export interface TwinEntityWire {
  id: string;
  zone_id: string;
  code: string;
  name: string;
  type: string;
  status: TwinStatus;
  metrics: {
    temperature: number | null;
    humidity: number | null;
    pressure: number | null;
    aqi: number | null;
    tvoc: number | null;
    eco2: number | null;
    light: number | null;
    sound: number | null;
    uv: number | null;
    occupancy: number | null;
    occupancy_ratio: number | null;
    energy: number | null;
    capacity: number | null;
  };
  reasons: string[];
  active_issues: string[];
  open_incident_count: number;
  correlation_run_id: string | null;
  correlation_status: string | null;
  root_cause: string | null;
  pending_approvals: number;
  model_object: string | null;
  position: number[] | null;
  scale: number | null;
  latitude: number | null;
  longitude: number | null;
  observed_at: string | null;
  metadata: Record<string, unknown>;
}

export interface TwinSnapshotWire {
  timestamp: string;
  entities: TwinEntityWire[];
  counts: Partial<Record<TwinStatus, number>>;
}

/** Converts the wire shape into the shape components consume. */
export function toTwinEntity(wire: TwinEntityWire): TwinEntity {
  const position =
    wire.position && wire.position.length === 3
      ? ([wire.position[0], wire.position[1], wire.position[2]] as [
          number,
          number,
          number,
        ])
      : null;

  return {
    id: wire.id,
    zone_id: wire.zone_id,
    code: wire.code,
    name: wire.name,
    type: wire.type,
    status: wire.status,
    metrics: wire.metrics,
    reasons: wire.reasons ?? [],
    activeIssues: wire.active_issues ?? [],
    openIncidentCount: wire.open_incident_count ?? 0,
    correlationRunId: wire.correlation_run_id ?? null,
    correlationStatus: wire.correlation_status ?? null,
    rootCause: wire.root_cause ?? null,
    pendingApprovals: wire.pending_approvals ?? 0,
    modelObject: wire.model_object ?? null,
    position,
    scale: wire.scale ?? null,
    latitude: wire.latitude ?? null,
    longitude: wire.longitude ?? null,
    observedAt: wire.observed_at ?? null,
    metadata: wire.metadata ?? {},
  };
}
