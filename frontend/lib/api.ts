import type {
  Building,
  Campus,
  Equipment,
  Floor,
  Incident,
  LatestTelemetryData,
  Sensor,
  Zone,
} from "@/lib/types";

import type {
  CopilotEvidence,
  CopilotRecommendation,
  CopilotReply,
} from "@/lib/copilot";

/**
 * The configured backend address.
 *
 * Exported so a caller can name it when a request fails. Every
 * "failed to fetch" in this project's history has been the
 * frontend pointed at a port the backend was not listening on,
 * and the browser's own message for that names neither the
 * address nor the cause.
 *
 * The default is the deployed backend, not localhost. A localhost
 * default is wrong in the browser: it names the visitor's own
 * machine, so a deployment missing this variable failed every
 * request against a backend that was up and healthy, with
 * nothing in the console to explain it.
 *
 * It is deliberately a plain fallback rather than a build
 * failure. An earlier version threw here when the variable was
 * unset during a production build, which turned a missing value
 * into a red build — and it fired on a Vercel build that
 * vercel.json had supplied the value for, because a deployment's
 * build environment is not a place to assume the variable will be
 * readable. A build that completes against a workable default is
 * recoverable in a way that a crashed build is not.
 *
 * Point at a local backend by setting the variable in .env.local
 * to http://127.0.0.1:8000. Use that address rather than
 * "localhost": uvicorn binds 127.0.0.1 by default, and where
 * localhost resolves to ::1 first, "localhost" is refused by a
 * backend that is running perfectly well.
 */

/**
 * The deployed backend, used when the variable gives us nothing
 * usable.
 *
 * Named rather than inlined so the default is greppable and the
 * address appears in exactly one place.
 */
export const DEFAULT_API_URL =
  "https://campus-impact-twin-api.onrender.com";

/**
 * Resolves the backend address from the raw environment value.
 *
 * Taken as an argument rather than read from `process.env` so the
 * empty-value cases are testable. They are not hypothetical: a
 * deployment that declares NEXT_PUBLIC_API_URL but leaves it empty
 * produced a build where this resolved to "", and every request
 * went out as a relative path like `/api/v1/campus/CIT-MAIN/twin`
 * to the frontend's own origin. That is what the browser showed —
 * a 404 from the frontend, naming the frontend, for a call that
 * should have gone to the backend.
 *
 * `??` is not enough on its own. It falls back for null and
 * undefined but accepts "", so an empty variable passes straight
 * through as the address. An empty string is the single most
 * common shape for a variable that is declared but unset, and it
 * fails in exactly the way the localhost default used to: quietly,
 * with the wrong host and nothing in the console.
 *
 * Whitespace is treated the same as empty, because a value of " "
 * is a configuration slip rather than an address.
 */
export function resolveApiUrl(raw?: string | null): string {
  const configured = raw?.trim();

  return configured ? configured : DEFAULT_API_URL;
}

export const API_URL = resolveApiUrl(process.env.NEXT_PUBLIC_API_URL);

/**
 * The backend could not be reached at all.
 *
 * Distinct from a response the backend refused, because the
 * remedies are different: this one is nearly always the port or
 * a backend that is not running, and the message says which
 * address was tried.
 */
export class ApiUnreachableError extends Error {
  constructor(label: string) {
    super(
      `${label} could not reach the campus API at ${API_URL}. ` +
        "Check that the backend is running on that address.",
    );

    this.name = "ApiUnreachableError";
  }
}

/**
 * Performs a request, converting the failure modes that
 * otherwise surface as an unhelpful "Failed to fetch".
 *
 * An abort is rethrown untouched: a cancelled poll is not an
 * error, and the polling hooks rely on recognising it by name.
 */
async function apiFetch(
  url: string,
  init: RequestInit,
  label: string,
): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch (cause) {
    if (
      cause instanceof DOMException &&
      cause.name === "AbortError"
    ) {
      throw cause;
    }

    throw new ApiUnreachableError(label);
  }
}

/**
 * Rejects a response the backend declined to serve.
 *
 * `notFoundMessage` lets a caller describe a 404 in terms of the
 * thing that was missing rather than as a status code.
 */
function ensureOk(
  response: Response,
  label: string,
  notFoundMessage?: string,
): void {
  if (response.ok) {
    return;
  }

  if (response.status === 404 && notFoundMessage) {
    throw new Error(notFoundMessage);
  }

  throw new Error(
    `${label} failed with status ${response.status}.`,
  );
}

/**
 * Parses a JSON body, rejecting a malformed one.
 *
 * A backend that is up but serving HTML (a wrong port hitting
 * another service, for instance) produces a parse failure here
 * rather than a confusing render failure later.
 */
async function readJson(
  response: Response,
  label: string,
): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new Error(
      `${label} returned a malformed response from ${API_URL}.`,
    );
  }
}

export interface CampusTwinData {
  campus: Campus;
  buildings: Building[];
  floors: Floor[];
  zones: Zone[];
  equipment: Equipment[];
  sensors: Sensor[];
  incidents: Incident[];
}

export async function getCampusTwin(
  campusCode = "CIT-MAIN",
  signal?: AbortSignal,
): Promise<CampusTwinData> {
  const label = "Campus Twin API";

  const response = await apiFetch(
    `${API_URL}/api/v1/campus/${campusCode}/twin`,
    {
      cache: "no-store",
      signal,
    },
    label,
  );

  ensureOk(response, label);

  return (await readJson(
    response,
    label,
  )) as CampusTwinData;
}


export interface LatestTelemetryOptions {
  /**
   * Narrows the response to one zone. Omitted when the caller
   * does not need it, because the backend defaults to every
   * zone in the campus.
   */
  zone?: string;
  limit?: number;
  /**
   * Lets a caller cancel an in-flight request, which is how
   * the polling hook avoids overlapping requests and cleans up
   * on unmount.
   */
  signal?: AbortSignal;
}

/**
 * The shape the endpoint promises. Anything else is treated as
 * a malformed response rather than rendered.
 */

function isLatestTelemetryData(
  value: unknown,
): value is LatestTelemetryData {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<LatestTelemetryData>;

  return (
    typeof candidate.campus_code === "string" &&
    Array.isArray(candidate.readings)
  );
}

function isLatestTelemetryReading(
  value: unknown,
): boolean {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const reading = value as Partial<
    LatestTelemetryData["readings"][number]
  >;

  return (
    typeof reading.sensor_id === "string" &&
    typeof reading.metric === "string" &&
    typeof reading.value === "number" &&
    typeof reading.unit === "string" &&
    typeof reading.timestamp === "string"
  );
}

/**
 * Reads the latest stored telemetry for a campus.
 *
 * Stored data, not a live stream: the caller decides how
 * fresh it looks by comparing `timestamp` with the clock.
 */

export async function getLatestTelemetry(
  campusCode = "CIT-MAIN",
  options: LatestTelemetryOptions = {},
): Promise<LatestTelemetryData> {
  const params = new URLSearchParams();

  if (options.zone) {
    params.set("zone", options.zone);
  }

  if (typeof options.limit === "number") {
    params.set("limit", String(options.limit));
  }

  const query = params.toString();
  const url =
    `${API_URL}/api/v1/campus/${campusCode}` +
    `/telemetry/latest${query ? `?${query}` : ""}`;

  const label = "Telemetry API";

  const response = await apiFetch(
    url,
    {
      cache: "no-store",
      signal: options.signal,
    },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (!isLatestTelemetryData(body)) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  // A malformed entry is dropped rather than rendered as
  // "no data", so a partial response still shows what is
  // trustworthy.
  const readings =
    body.readings.filter(isLatestTelemetryReading);

  return {
    ...body,
    readings,
  };
}

// ============================================================
// DIGITAL TWIN (Phase 12)
// ============================================================
//
// Added to this module rather than replacing it, so the campus
// and telemetry fetchers already here keep working.
//
// The twin is treated as untrusted input and validated rather
// than cast: a malformed snapshot that reached a 3D scene would
// surface as an unexplained undefined at render time, deep in
// Three.js, which is a miserable thing to debug. Checking the
// shape here turns that into a clear message at the boundary.

import type {
  TwinEntity,
  TwinSnapshotWire,
} from "@/lib/twin-state";

/** Poll interval for the twin snapshot, in milliseconds. */
export const TWIN_POLL_INTERVAL_MS = 5000;

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" && value !== null
  );
}

/**
 * Checks the snapshot has the shape the twin components need.
 *
 * Deliberately shallow: it verifies the envelope and the fields
 * every component reads unconditionally, and lets the typed
 * metrics through. Deep validation of eleven numeric fields on
 * every poll would cost more than it catches.
 */
function isTwinSnapshot(
  value: unknown,
): value is TwinSnapshotWire {
  if (!isRecord(value)) {
    return false;
  }

  if (
    typeof value.timestamp !== "string" ||
    !Array.isArray(value.entities)
  ) {
    return false;
  }

  return value.entities.every(
    (entity) =>
      isRecord(entity) &&
      typeof entity.id === "string" &&
      typeof entity.name === "string" &&
      typeof entity.status === "string" &&
      isRecord(entity.metrics),
  );
}

export async function getDigitalTwinSnapshot(
  signal?: AbortSignal,
): Promise<TwinSnapshotWire> {
  const label = "Digital Twin API";

  const response = await apiFetch(
    `${API_URL}/api/v1/digital-twin/snapshot`,
    {
      cache: "no-store",
      signal,
    },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (!isTwinSnapshot(body)) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body;
}

export async function getDigitalTwinEntity(
  entityId: string,
  signal?: AbortSignal,
): Promise<TwinEntity> {
  const label = "Digital Twin API";

  const response = await apiFetch(
    `${API_URL}/api/v1/digital-twin/entities/${encodeURIComponent(
      entityId,
    )}`,
    {
      cache: "no-store",
      signal,
    },
    label,
  );

  ensureOk(
    response,
    label,
    `No campus entity matching '${entityId}'.`,
  );

  const body = await readJson(response, label);

  if (
    !isRecord(body) ||
    typeof body.id !== "string" ||
    !isRecord(body.metrics)
  ) {
    throw new Error(
      `${label} returned an unexpected entity shape.`,
    );
  }

  // The wire shape is camel-cased here so callers receive the
  // same type the snapshot endpoint produces after conversion.
  return body as unknown as TwinEntity;
}

// ============================================================
// AI COPILOT (Phase 13)
// ============================================================
//
// The copilot is the only place in this project where text comes
// from a language model. Its `answer` field is model prose; its
// `evidence` and `recommendations` are not. They are computed in
// Python and returned alongside, so a reader can check every claim
// the prose makes.
//
// That is why `source` is surfaced in the UI: when the local
// model is unavailable the copilot composes its answer from the
// same facts and says so. A demo should never appear to have
// worked when it did not.

async function askCopilot(
  message: string,
  entityId?: string | null,
  signal?: AbortSignal,
): Promise<CopilotReply> {
  const label = "The copilot";

  const response = await apiFetch(
    `${API_URL}/api/v1/copilot/ask`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        entity_id: entityId ?? null,
      }),
      signal,
    },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (
    typeof body !== "object" ||
    body === null ||
    typeof (body as { answer?: unknown }).answer !==
      "string"
  ) {
    throw new Error(
      "The copilot returned an unexpected response shape.",
    );
  }

  return body as CopilotReply;
}

export type { CopilotEvidence, CopilotRecommendation };

export { askCopilot };

// ============================================================
// INCIDENTS AND APPROVALS
// ============================================================
//
// The two pages that let a person work through what the twin has
// found: the incidents themselves, and the requests waiting on a
// decision.
//
// The approval calls are the only writes in this module, and they
// write to a decision record, not to anything on the campus. A
// request can only be approved, rejected, prepared or executed by
// naming a person, and the backend records each as its own
// auditable step.

import type {
  ApprovalExecutionResult,
  ApprovalRequest,
  ApprovalReviewResult,
  IncidentSummary,
} from "@/lib/types";

function isApprovalRequest(
  value: unknown,
): value is ApprovalRequest {
  return (
    isRecord(value) &&
    typeof value.request_code === "string" &&
    typeof value.title === "string" &&
    typeof value.status === "string" &&
    Array.isArray(value.events)
  );
}

export interface IncidentListOptions {
  status?: string | null;
  severity?: string | null;
  category?: string | null;
  /** Zone code, for example LH01. */
  zone?: string | null;
  limit?: number;
}

/**
 * Lists incidents, most severe first.
 *
 * Filters are applied by the backend, not here: fetching a page and
 * narrowing it in the browser would silently under-report once the
 * result reached the limit.
 */
export async function getIncidents(
  options: IncidentListOptions = {},
  signal?: AbortSignal,
): Promise<Incident[]> {
  const params = new URLSearchParams();

  if (options.status) {
    params.set("status", options.status);
  }

  if (options.severity) {
    params.set("severity", options.severity);
  }

  if (options.category) {
    params.set("category", options.category);
  }

  if (options.zone) {
    params.set("zone", options.zone);
  }

  if (typeof options.limit === "number") {
    params.set("limit", String(options.limit));
  }

  const query = params.toString();
  const label = "Incidents API";

  const response = await apiFetch(
    `${API_URL}/api/v1/incidents${query ? `?${query}` : ""}`,
    { cache: "no-store", signal },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (!Array.isArray(body)) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  // A row without an id cannot be keyed or acted on, so it is
  // dropped rather than rendered as a broken card.
  return body.filter(
    (item) =>
      isRecord(item) && typeof item.id === "string",
  ) as Incident[];
}

export async function getIncidentSummary(
  campusCode = "CIT-MAIN",
  signal?: AbortSignal,
): Promise<IncidentSummary> {
  const label = "Incidents API";

  const response = await apiFetch(
    `${API_URL}/api/v1/incidents/summary?campus_code=${encodeURIComponent(campusCode)}`,
    { cache: "no-store", signal },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (
    !isRecord(body) ||
    typeof body.total_incidents !== "number" ||
    typeof body.open_incidents !== "number"
  ) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body as unknown as IncidentSummary;
}

export async function getApprovalRequests(
  signal?: AbortSignal,
): Promise<ApprovalRequest[]> {
  const label = "Approvals API";

  const response = await apiFetch(
    `${API_URL}/api/v1/approvals`,
    { cache: "no-store", signal },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (!Array.isArray(body)) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body.filter(isApprovalRequest);
}

/**
 * Records a human decision on a request.
 *
 * A reviewer is required by the backend, and a reason is required
 * for anything that closes the request, so both are collected
 * before this is called rather than being left blank.
 */
export async function reviewApproval(
  approvalId: string,
  review: {
    status: "approved" | "rejected";
    reviewer: string;
    reason?: string | null;
  },
  signal?: AbortSignal,
): Promise<ApprovalReviewResult> {
  const label = "The approval review";

  const response = await apiFetch(
    `${API_URL}/api/v1/approvals/${encodeURIComponent(approvalId)}/review`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(review),
      signal,
    },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (
    !isRecord(body) ||
    !isApprovalRequest(body.approval)
  ) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body as unknown as ApprovalReviewResult;
}

/**
 * Moves an approved request to ready for execution.
 *
 * A separate step from approving, on purpose: agreeing to an action
 * and scheduling it are different decisions.
 */
export async function prepareApproval(
  approvalId: string,
  actor: string,
  signal?: AbortSignal,
): Promise<ApprovalRequest> {
  const label = "The approval preparation";

  const response = await apiFetch(
    `${API_URL}/api/v1/approvals/${encodeURIComponent(approvalId)}/prepare?actor=${encodeURIComponent(actor)}`,
    { method: "POST", cache: "no-store", signal },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (!isApprovalRequest(body)) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body;
}

/**
 * Records a simulated execution.
 *
 * Simulation only. Nothing in this project can reach a physical
 * campus system, so this writes a record of what would have
 * happened and nothing else.
 */
export async function executeApproval(
  approvalId: string,
  actor: string,
  signal?: AbortSignal,
): Promise<ApprovalExecutionResult> {
  const label = "The simulated execution";

  const response = await apiFetch(
    `${API_URL}/api/v1/approvals/${encodeURIComponent(approvalId)}/execute?actor=${encodeURIComponent(actor)}`,
    { method: "POST", cache: "no-store", signal },
    label,
  );

  ensureOk(response, label);

  const body = await readJson(response, label);

  if (
    !isRecord(body) ||
    !isApprovalRequest(body.approval)
  ) {
    throw new Error(
      `${label} returned an unexpected response shape.`,
    );
  }

  return body as unknown as ApprovalExecutionResult;
}

export type {
  ApprovalExecutionResult,
  ApprovalRequest,
  ApprovalReviewResult,
  Incident,
  IncidentSummary,
};
