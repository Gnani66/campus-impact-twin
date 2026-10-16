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
    <main className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="mx-auto w-full max-w-7xl px-1 pt-6">
        <h2 className="text-2xl font-semibold tracking-tight">
          Digital Twin
        </h2>

        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Live visual representation of campus operations. Status
          is determined on the backend from stored sensor readings,
          so the model and the incident record cannot disagree.
        </p>
      </div>

      <div className="mx-auto min-h-0 w-full max-w-7xl flex-1 px-1 pt-4">
        <DigitalTwin />
      </div>
    </main>
  );
}
