import { Suspense } from "react";

import { CopilotScope } from "@/components/copilot/CopilotScope";

/**
 * The copilot page.
 *
 * The scope lives in a Suspense boundary on purpose. This Next
 * version has cache components enabled, and a page that reads
 * `searchParams` cannot be prerendered unless the dynamic read is
 * streamed. Putting the boundary around the part that needs the
 * URL keeps the page chrome in the static shell, so the heading
 * and the copilot frame paint immediately and only the scope
 * waits.
 */
export default function CopilotPage({
  searchParams,
}: PageProps<"/copilot">) {
  return (
    // `100vh - 3.5rem` is the viewport minus the sticky shell
    // header. `h-screen` here would push a scrollbar onto the page
    // and cut the conversation off at the bottom.
    <main className="flex h-[calc(100vh-3.5rem)] flex-col">
      <div className="mx-auto w-full max-w-7xl px-1 pt-6">
        <h2 className="text-2xl font-semibold tracking-tight">
          AI Operations Copilot
        </h2>

        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Ask what needs attention, why a zone holds its status, or
          what might be done about it. The backend reads stored
          sensor readings and decides; the local model only explains
          what was already decided.
        </p>
      </div>

      <div className="mx-auto min-h-0 w-full max-w-7xl flex-1 px-1 pt-4">
        <Suspense fallback={<CopilotFrame />}>
          <CopilotScope searchParams={searchParams} />
        </Suspense>
      </div>
    </main>
  );
}

/**
 * The shell the streamed panel replaces.
 *
 * Deliberately the same shape as the loaded panel, so arriving at
 * the copilot does not make the page jump. It says it is loading
 * rather than showing an empty chat box, because an empty box
 * reads as "there is nothing to ask" when it actually means "not
 * ready yet".
 */
function CopilotFrame() {
  return (
    <section className="flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex-1 flex items-center justify-center p-5 text-sm text-slate-400">
        Preparing the campus copilot...
      </div>
    </section>
  );
}
