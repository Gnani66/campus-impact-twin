export interface Campus {
  id: string;
  code: string;
  name: string;
  description: string | null;
  timezone: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Building {
  id: string;
  campus_id: string;
  code: string;
  name: string;
  description: string | null;
  latitude: number | null;
  longitude: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Floor {
  id: string;
  building_id: string;
  code: string;
  name: string;
  floor_number: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Zone {
  id: string;
  floor_id: string;
  code: string;
  name: string;
  zone_type: string;
  capacity: number | null;
  area_sq_meters: number | null;
  schedule_start_hour: number | null;
  schedule_end_hour: number | null;
  active_days: number[] | null;
  twin_model_object: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Equipment {
  id: string;
  zone_id: string | null;
  code: string;
  name: string;
  equipment_type: string;
  status: string;
  manufacturer: string | null;
  model_number: string | null;
  installation_date: string | null;
  rated_power_kw: number | null;
  twin_model_object: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Sensor {
  id: string;
  zone_id: string | null;
  equipment_id: string | null;
  code: string;
  name: string;
  sensor_type: string;
  unit: string | null;
  status: string;
  sampling_interval_seconds: number | null;
  twin_model_object: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * A campus incident.
 *
 * Two endpoints return this, with slightly different coverage.
 * `/campus/{code}/twin` includes the audit timestamps it stored;
 * `/incidents` resolves the zone code, which is what makes a list
 * of incidents readable. Fields that only one of them returns are
 * optional rather than duplicated into a second type, because
 * callers use both for the same purpose: showing a problem.
 */
export interface Incident {
  id: string;
  campus_id: string;
  building_id: string | null;
  zone_id: string | null;
  sensor_id: string | null;
  equipment_id: string | null;
  category: string;
  severity: string;
  status: string;
  title: string;
  description: string;
  impact_score: number;
  confidence_score: number | null;
  detection_method: string;
  evidence: unknown[];
  detected_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  /** Resolved by `/incidents`; absent from the twin snapshot. */
  zone_code?: string | null;
  created_at?: string;
  updated_at?: string;
}

/** Aggregate incident counts for one campus. */
export interface IncidentSummary {
  campus_code: string;
  total_incidents: number;
  critical: number;
  high: number;
  medium: number;
  low: number;
  open_incidents: number;
  highest_impact: number;
}

/**
 * One entry in an approval's history.
 *
 * Events are append-only: they are the record of who decided what,
 * and when.
 */
export interface ApprovalEvent {
  id: string | null;
  previous_status: string | null;
  new_status: string;
  actor: string;
  reason: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

/**
 * A recommendation put to a human.
 *
 * Nothing here acts on the campus. A request moves
 * pending -> approved -> ready_to_execute -> executed, each step a
 * separate decision recorded separately, and every status here is
 * decided by a person.
 */
export interface ApprovalRequest {
  id: string | null;
  request_code: string;
  simulation_id: string;
  simulation_option_id: string;
  title: string;
  status: string;
  description: string | null;
  requested_by: string;
  requested_at: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_reason: string | null;
  execution_started_at: string | null;
  execution_completed_at: string | null;
  execution_result: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  events: ApprovalEvent[];
}

/** The outcome of a review: the new state and the record of it. */
export interface ApprovalReviewResult {
  approval: ApprovalRequest;
  event: ApprovalEvent;
}

/** The outcome of a simulated execution. */
export interface ApprovalExecutionResult {
  approval: ApprovalRequest;
  event: ApprovalEvent | null;
  execution_result: Record<string, unknown>;
}

export interface TelemetryReading {
  id: string;
  campus_id: string;
  building_id: string | null;
  floor_id: string | null;
  zone_id: string | null;
  sensor_id: string | null;
  equipment_id: string | null;
  metric: string;
  value: number;
  unit: string;
  timestamp: string;
  source: string;
  quality: string;
  metadata: Record<string, unknown>;
}

/**
 * Latest stored telemetry, as returned by
 * GET /api/v1/campus/{campus_code}/telemetry/latest.
 *
 * Values come from the database. They are not live: with MQTT
 * disabled the newest reading is only as fresh as the last
 * write, which `timestamp` records.
 */

export interface LatestTelemetryReading {
  sensor_id: string;
  sensor_code: string | null;
  sensor_type: string | null;
  metric: string;
  value: number;
  unit: string;
  timestamp: string;
  source: string;
  quality: string;
  campus_id: string | null;
  building_id: string | null;
  floor_id: string | null;
  zone_id: string | null;
  campus_code: string | null;
  building_code: string | null;
  floor_code: string | null;
  zone_code: string | null;
  metadata: Record<string, unknown>;
}

export interface LatestTelemetryData {
  campus_code: string;
  campus_id: string;
  zone_code: string | null;
  sensors_considered: number;
  reading_count: number;
  readings: LatestTelemetryReading[];
  sensors_without_readings: string[];
  generated_at: string;
}
