/**
 * Tests for the API boundary (Phase 13 follow-up).
 *
 * The failure these defend against is the one that actually
 * happened here: the frontend was pointed at a port the backend
 * was not on, and every call surfaced as the browser's
 * "Failed to fetch", which names neither the address nor the
 * cause. Two of the five fetchers did not handle a network
 * failure at all, so those threw a raw TypeError.
 *
 * The contract is now uniform: a network failure names the
 * configured address, an abort is passed through untouched, and
 * a response the backend refused names the status.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_URL,
  ApiUnreachableError,
  executeApproval,
  getApprovalRequests,
  getCampusTwin,
  getDigitalTwinEntity,
  getDigitalTwinSnapshot,
  getIncidentSummary,
  getIncidents,
  getLatestTelemetry,
  prepareApproval,
  reviewApproval,
} from "@/lib/api";

/**
 * Replaces the global fetch.
 *
 * The parameters are typed as unknown rather than left off, so a
 * test can read back what was passed - the URL and body of a write
 * are the thing worth asserting on.
 */
function stubFetch(
  implementation: (
    ...args: unknown[]
  ) => Promise<Response>,
) {
  const spy = vi.fn(implementation);

  vi.stubGlobal("fetch", spy);

  return spy;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("network failure", () => {
  it("names the configured address instead of failing to fetch", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(getCampusTwin()).rejects.toThrow(
      ApiUnreachableError,
    );

    await expect(getCampusTwin()).rejects.toThrow(API_URL);
  });

  it("covers every fetcher, not just the ones that had handling", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    const failures = await Promise.all([
      getCampusTwin().catch((error: unknown) => error),
      getLatestTelemetry().catch((error: unknown) => error),
      getDigitalTwinSnapshot().catch((error: unknown) => error),
      getDigitalTwinEntity("lecture-hall-01").catch(
        (error: unknown) => error,
      ),
    ]);

    for (const failure of failures) {
      expect(failure).toBeInstanceOf(ApiUnreachableError);
      expect((failure as Error).message).toContain(API_URL);
    }
  });

  it("says what to check", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(getCampusTwin()).rejects.toThrow(
      /backend is running/,
    );
  });
});

describe("abort", () => {
  it("is passed through untouched, not reported as unreachable", async () => {
    stubFetch(() =>
      Promise.reject(
        new DOMException("The operation was aborted.", "AbortError"),
      ),
    );

    const error = await getDigitalTwinSnapshot().catch(
      (cause: unknown) => cause,
    );

    // A cancelled poll is not a failure, and the polling hooks
    // recognise it by name. Wrapping it would break them.
    expect(error).toBeInstanceOf(DOMException);
    expect((error as DOMException).name).toBe("AbortError");
    expect(error).not.toBeInstanceOf(ApiUnreachableError);
  });
});

describe("refused responses", () => {
  it("reports the status when the backend declines", async () => {
    stubFetch(() => Promise.resolve(new Response("", { status: 503 })));

    await expect(getCampusTwin()).rejects.toThrow(
      /Campus Twin API failed with status 503/,
    );
  });

  it("describes a missing entity by name rather than as a 404", async () => {
    stubFetch(() => Promise.resolve(new Response("", { status: 404 })));

    await expect(
      getDigitalTwinEntity("does-not-exist"),
    ).rejects.toThrow("No campus entity matching 'does-not-exist'.");
  });
});

describe("malformed bodies", () => {
  it("rejects a body that is not JSON", async () => {
    // What a wrong port looks like when it reaches a different
    // service: a 200 carrying HTML.
    stubFetch(() =>
      Promise.resolve(
        new Response("<!doctype html><html></html>", {
          status: 200,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    await expect(getCampusTwin()).rejects.toThrow(
      /malformed response from/,
    );
  });

  it("rejects a JSON body of the wrong shape", async () => {
    stubFetch(() => Promise.resolve(jsonResponse({ nope: true })));

    await expect(getLatestTelemetry()).rejects.toThrow(
      /unexpected response shape/,
    );
  });
});

describe("success", () => {
  it("returns the twin snapshot unchanged", async () => {
    const snapshot = {
      timestamp: "2026-10-16T10:42:15+00:00",
      entities: [
        {
          id: "lecture-hall-01",
          name: "University Lecture Hall",
          status: "critical",
          metrics: {},
        },
      ],
      counts: {},
    };

    stubFetch(() => Promise.resolve(jsonResponse(snapshot)));

    await expect(getDigitalTwinSnapshot()).resolves.toEqual(
      snapshot,
    );
  });
});

/**
 * The incidents and approvals clients.
 *
 * Two behaviours are worth pinning here. Filters must reach the
 * backend rather than being applied in the browser, because
 * fetching a page and narrowing it locally under-reports as soon
 * as the result hits the limit. And every approval write must
 * carry the reviewer's name, since that is what makes a decision
 * attributable - a client that quietly dropped it would produce
 * rejections the backend refuses, with nothing on the page to
 * explain why.
 */
describe("incidents", () => {
  function incident(overrides: Record<string, unknown> = {}) {
    return {
      id: "incident-1",
      title: "Overheating in an occupied zone",
      status: "open",
      severity: "critical",
      impact_score: 91,
      detected_at: "2026-10-16T01:00:00Z",
      zone_code: "LH01",
      ...overrides,
    };
  }

  it("sends filters to the backend", async () => {
    const spy = stubFetch(() =>
      Promise.resolve(jsonResponse([incident()])),
    );

    await getIncidents({
      status: "open",
      severity: "critical",
      category: "environment",
      zone: "LH01",
      limit: 200,
    });

    const url = new URL(
      spy.mock.calls[0][0] as string,
    );

    expect(url.pathname).toContain("/api/v1/incidents");
    expect(url.searchParams.get("status")).toBe("open");
    expect(url.searchParams.get("severity")).toBe(
      "critical",
    );
    expect(url.searchParams.get("category")).toBe(
      "environment",
    );
    // The zone is sent as `zone`, which is what the twin's
    // entity panel links to.
    expect(url.searchParams.get("zone")).toBe("LH01");
    expect(url.searchParams.get("limit")).toBe("200");
  });

  it("sends no filters when none are set", async () => {
    const spy = stubFetch(() =>
      Promise.resolve(jsonResponse([])),
    );

    await getIncidents();

    const url = new URL(
      spy.mock.calls[0][0] as string,
    );

    expect(url.search).toBe("");
  });

  it("keeps the zone code the backend resolved", async () => {
    stubFetch(() =>
      Promise.resolve(jsonResponse([incident()])),
    );

    const rows = await getIncidents();

    expect(rows[0].zone_code).toBe("LH01");
  });

  it("drops a row with no id", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse([
          incident(),
          { title: "no id here" },
        ]),
      ),
    );

    // A row without an id cannot be keyed, so it is dropped
    // rather than rendered as a card React cannot reconcile.
    const rows = await getIncidents();

    expect(rows).toHaveLength(1);
  });

  it("rejects a body that is not a list", async () => {
    stubFetch(() =>
      Promise.resolve(jsonResponse({ nope: true })),
    );

    await expect(getIncidents()).rejects.toThrow(
      /unexpected response shape/,
    );
  });

  it("reads the summary", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse({
          campus_code: "CIT-MAIN",
          total_incidents: 50,
          critical: 18,
          high: 32,
          medium: 0,
          low: 0,
          open_incidents: 8,
          highest_impact: 100,
        }),
      ),
    );

    const summary = await getIncidentSummary();

    expect(summary.open_incidents).toBe(8);
  });

  it("rejects a summary without counts", async () => {
    stubFetch(() =>
      Promise.resolve(jsonResponse({ campus_code: "X" })),
    );

    await expect(getIncidentSummary()).rejects.toThrow(
      /unexpected response shape/,
    );
  });
});

describe("approvals", () => {
  function request(overrides: Record<string, unknown> = {}) {
    return {
      id: "approval-1",
      request_code: "APR-604E9B",
      simulation_id: "sim-1",
      simulation_option_id: "option-1",
      title: "Reduce lecture hall HVAC energy usage",
      status: "pending",
      requested_by: "system",
      events: [],
      ...overrides,
    };
  }

  it("lists requests", async () => {
    stubFetch(() =>
      Promise.resolve(jsonResponse([request()])),
    );

    const rows = await getApprovalRequests();

    expect(rows).toHaveLength(1);
    expect(rows[0].request_code).toBe("APR-604E9B");
  });

  it("drops a row that is not a request", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse([request(), { id: "x" }]),
      ),
    );

    await expect(getApprovalRequests()).resolves.toHaveLength(
      1,
    );
  });

  it("sends the reviewer with a decision", async () => {
    const spy = stubFetch(() =>
      Promise.resolve(
        jsonResponse({
          approval: request({ status: "approved" }),
          event: {
            previous_status: "pending",
            new_status: "approved",
            actor: "operator",
          },
        }),
      ),
    );

    const result = await reviewApproval("approval-1", {
      status: "approved",
      reviewer: "operator",
    });

    expect(spy.mock.calls[0][0]).toContain(
      "/api/v1/approvals/approval-1/review",
    );

    const init = spy.mock.calls[0][1] as RequestInit;

    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      status: "approved",
      reviewer: "operator",
    });

    expect(result.approval.status).toBe("approved");
  });

  it("escapes an id with characters that need it", async () => {
    const spy = stubFetch(() =>
      Promise.resolve(jsonResponse(request())),
    );

    await prepareApproval("a b/c", "operator");

    expect(spy.mock.calls[0][0]).toContain(
      "/api/v1/approvals/a%20b%2Fc/prepare",
    );
  });

  it("names the actor when preparing", async () => {
    const spy = stubFetch(() =>
      Promise.resolve(jsonResponse(request())),
    );

    await prepareApproval("approval-1", "operator");

    const url = new URL(
      spy.mock.calls[0][0] as string,
    );

    expect(url.pathname).toContain("/prepare");
    expect(url.searchParams.get("actor")).toBe(
      "operator",
    );
  });

  it("returns the recorded execution", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse({
          approval: request({ status: "executed" }),
          event: null,
          execution_result: { mode: "simulation" },
        }),
      ),
    );

    const result = await executeApproval(
      "approval-1",
      "operator",
    );

    expect(result.execution_result).toEqual({
      mode: "simulation",
    });
  });

  it("rejects a review without an approval in it", async () => {
    stubFetch(() =>
      Promise.resolve(jsonResponse({ event: {} })),
    );

    await expect(
      reviewApproval("approval-1", {
        status: "approved",
        reviewer: "operator",
      }),
    ).rejects.toThrow(/unexpected response shape/);
  });

  it("reports a refused decision with its status", async () => {
    stubFetch(() =>
      Promise.resolve(new Response("", { status: 409 })),
    );

    // The backend rejects a decision that is not legal from the
    // current status. Saying so matters: the page shows this
    // message rather than appearing to have saved.
    await expect(
      reviewApproval("approval-1", {
        status: "approved",
        reviewer: "operator",
      }),
    ).rejects.toThrow(/status 409/);
  });
});
