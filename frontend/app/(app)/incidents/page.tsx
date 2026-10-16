import { Suspense } from "react";

import { IncidentsScope } from "@/components/incidents/IncidentsScope";

/**
 * The incidents page.
 *
 * The zone filter lives inside a Suspense boundary for the same
 * reason the copilot's scope does: this Next version has cache
 * components enabled, and a page that reads `searchParams` cannot
 * be prerendered unless the dynamic read is streamed. Keeping the
 * read behind the boundary means the heading and the explanation
 * are part of the static shell and paint immediately, and only the
 * list waits for the URL and then the API.
 */
export default function IncidentsPage({
  searchParams,
}: PageProps<"/incidents">) {
  return (
    <main>
      <div className="mx-auto max-w-7xl py-6">
        <header>
          <h2 className="text-2xl font-semibold tracking-tight">
            Incidents
          </h2>

          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Everything the rules have raised, and why. Each one was
            decided by the backend from stored readings, and this
            page only displays what was decided. Resolved and
            dismissed incidents stay here as history.
          </p>
        </header>

        <div className="mt-6">
          <Suspense fallback={<IncidentsFrame />}>
            <IncidentsScope searchParams={searchParams} />
          </Suspense>
        </div>
      </div>
    </main>
  );
}

/**
 * What the streamed content replaces.
 *
 * The same shape as the loaded page, so arriving here from the
 * twin does not make the layout jump.
 */
function IncidentsFrame() {
  return (
    <section className="rounded-xl border bg-card p-6">
      <p className="text-sm text-muted-foreground">
        Loading incidents...
      </p>
    </section>
  );
}
