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
  getCampusTwin,
  getDigitalTwinEntity,
  getDigitalTwinSnapshot,
  getLatestTelemetry,
} from "@/lib/api";

function stubFetch(implementation: () => Promise<Response>) {
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
