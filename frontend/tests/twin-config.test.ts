/**
 * Tests for twin configuration (Phase 12).
 *
 * The failure these defend against is the one that reached a
 * deployment: NEXT_PUBLIC_MODEL_URL was declared but empty, so
 * the model path resolved to nothing and every request asked the
 * frontend's own origin for a 260 MB GLB. It surfaced as a 404
 * from the frontend for an asset that exists, which reads as a
 * missing file rather than a missing hostname.
 *
 * The same shape as the API address bug, and fixed the same way:
 * a blank value is a value that says nothing, not an address.
 */

import { describe, expect, it } from "vitest";

import { resolveModelPath } from "@/lib/twin/config";

describe("resolveModelPath", () => {
  it("uses a configured absolute URL", () => {
    expect(
      resolveModelPath(
        "https://project.supabase.co/storage/v1/object/public/twin/lecture-hall.glb",
      ),
    ).toBe(
      "https://project.supabase.co/storage/v1/object/public/twin/lecture-hall.glb",
    );
  });

  it("keeps a configured local path", () => {
    expect(resolveModelPath("/models/other.glb")).toBe(
      "/models/other.glb",
    );
  });

  it("falls back when the variable is unset", () => {
    expect(resolveModelPath(undefined)).toBe(
      "/models/lecture-hall.glb",
    );
  });

  it("falls back when the variable is an empty string", () => {
    expect(resolveModelPath("")).toBe("/models/lecture-hall.glb");
  });

  it("falls back when the variable is only whitespace", () => {
    expect(resolveModelPath("  \n ")).toBe(
      "/models/lecture-hall.glb",
    );
  });

  it("trims a configured URL", () => {
    // Untrimmed, this requests "...glb /api" and fails as a
    // malformed URL rather than a missing file.
    expect(resolveModelPath("  https://cdn.test/a.glb ")).toBe(
      "https://cdn.test/a.glb",
    );
  });

  it("never resolves to an empty path", () => {
    for (const raw of [undefined, null, "", "   "]) {
      expect(resolveModelPath(raw)).not.toBe("");
    }
  });
});
