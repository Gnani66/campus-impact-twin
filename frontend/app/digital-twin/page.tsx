"use client";

import dynamic from "next/dynamic";

/**
 * The digital twin view.
 *
 * The scene is loaded dynamically with `ssr: false` because
 * Three.js touches `window` at import time, so a server render
 * would throw on a module that is perfectly valid in the
 * browser. Loading it client-side is not a workaround, it is the
 * only correct arrangement.
 */
const DigitalTwin = dynamic(
  () =>
    import("@/components/digital-twin/DigitalTwin").then(
      (module) => module.DigitalTwin,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center rounded-2xl bg-slate-950 text-sm text-slate-400">
        Loading digital twin...
      </div>
    ),
  },
);

export default function DigitalTwinPage() {
  return (
    <main className="flex h-screen flex-col bg-slate-100 p-6">
      <div className="mb-4 flex items-end justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Smart Campus
          </p>

          <h1 className="text-2xl font-semibold text-slate-900">
            Digital Twin
          </h1>

          <p className="mt-1 text-sm text-slate-600">
            Live visual representation of campus operations. Status is
            determined on the backend from stored sensor readings.
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1">
        <DigitalTwin />
      </div>
    </main>
  );
}
