import { ApprovalsWorkspace } from "@/components/approvals/ApprovalsWorkspace";

/**
 * The approvals page.
 *
 * No Suspense boundary is needed here: this page reads no
 * `searchParams` and fetches nothing on the server, so it
 * prerenders as static content and the workspace takes over on the
 * client. That is deliberate - the queue is personal and must not
 * be baked into a prerendered page.
 */
export default function ApprovalsPage() {
  return (
    <main>
      <div className="mx-auto max-w-5xl py-6">
        <header>
          <h2 className="text-2xl font-semibold tracking-tight">
            Approvals
          </h2>

          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Recommendations waiting on a person. Approving here
            records a decision; it does not act on the campus.
            Execution is simulated, and each step - agreeing,
            preparing, running - is signed separately so the record
            shows who authorised what and when.
          </p>
        </header>

        <div className="mt-6">
          <ApprovalsWorkspace />
        </div>
      </div>
    </main>
  );
}
