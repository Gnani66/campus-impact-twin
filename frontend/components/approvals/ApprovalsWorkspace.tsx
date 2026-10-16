"use client";

import { useCallback, useEffect, useState } from "react";

import {
  executeApproval,
  getApprovalRequests,
  prepareApproval,
  reviewApproval,
} from "@/lib/api";
import type { ApprovalRequest } from "@/lib/types";

/**
 * The approvals page.
 *
 * THIS IS THE ONLY PAGE IN THE PROJECT THAT CHANGES ANYTHING,
 * and what it changes is a decision record.
 *
 * Three rules shape every decision below:
 *
 * 1. Every action names a person. The backend rejects an approval
 *    or a rejection with no reviewer, so there is no anonymous
 *    button here to press.
 * 2. Nothing here touches the campus. Execution is simulated, and
 *    the label says so on every button, because "Execute" without
 *    that word would be the most dangerous string in the app.
 * 3. Agreeing and doing are separate steps. Approving does not
 *    prepare, and preparing does not execute. Each is its own
 *    signed event, which is the whole point of the queue existing.
 */

const STATUS_STYLES: Record<string, string> = {
  pending: "border-amber-700/50 bg-amber-950/30 text-amber-300",
  approved: "border-sky-700/50 bg-sky-950/30 text-sky-300",
  ready_to_execute: "border-indigo-700/50 bg-indigo-950/30 text-indigo-300",
  executed: "border-emerald-700/50 bg-emerald-950/30 text-emerald-300",
  rejected: "border-rose-800/60 bg-rose-950/30 text-rose-300",
  expired: "border-slate-700 bg-slate-900 text-slate-400",
  cancelled: "border-slate-700 bg-slate-900 text-slate-400",
};

const STATUS_EXPLANATIONS: Record<string, string> = {
  pending: "Waiting for a person to decide.",
  approved: "Agreed, but not yet cleared to run.",
  ready_to_execute:
    "Cleared to run. Still nothing has happened.",
  executed:
    "A simulated execution was recorded. No campus system was touched.",
  rejected: "Declined, with a reason on the record.",
  expired: "Lapsed before anyone decided.",
  cancelled: "Withdrawn.",
};

export function ApprovalsWorkspace() {
  const [requests, setRequests] = useState<
    ApprovalRequest[] | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  const [reviewer, setReviewer] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  /**
   * Loads the queue.
   *
   * There is no `loading` flag here: nothing has arrived yet is
   * already the loading state, and a second flag would mean
   * setting state synchronously the moment an effect runs, which
   * costs a render pass to say something already known.
   */
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const rows = await getApprovalRequests(signal);

      setRequests(rows);
      setError(null);
    } catch (err) {
      if (
        err instanceof DOMException &&
        err.name === "AbortError"
      ) {
        return;
      }

      setError(
        err instanceof Error
          ? err.message
          : "Approvals could not be loaded.",
      );
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    // Declared here rather than called directly, so the effect
    // body itself never touches state: the first thing this does
    // is await the network.
    async function loadQueue() {
      await load(controller.signal);
    }

    void loadQueue();

    return () => controller.abort();
  }, [load]);

  /**
   * Runs one decision and reloads.
   *
   * The list is refetched rather than patched locally: every step
   * appends an immutable event and may move other requests, and a
   * queue showing a status the backend disagrees with is worse than
   * a slow one.
   */
  const act = useCallback(
    async (
      request: ApprovalRequest,
      action: () => Promise<unknown>,
    ) => {
      if (!request.id) {
        return;
      }

      setBusy(request.id);
      setError(null);

      try {
        await action();
        await load();
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "The action could not be completed.",
        );
      } finally {
        setBusy(null);
      }
    },
    [load],
  );

  const reviewerName = reviewer.trim();

  const canDecide = reviewerName.length > 0;

  const pending = requests?.filter(
    (request) => request.status === "pending",
  ).length;

  return (
    <div className="space-y-8">
      <section className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
        <label className="block max-w-md">
          <span className="text-xs uppercase tracking-wider text-slate-500">
            Your name
          </span>

          <input
            type="text"
            value={reviewer}
            onChange={(event) =>
              setReviewer(event.target.value)
            }
            placeholder="Who is reviewing?"
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
          />
        </label>

        <p className="mt-3 text-xs text-slate-500">
          Every decision below is recorded against this name, and
          the backend will not accept an empty one.
        </p>

        {pending !== undefined && (
          <p className="mt-4 text-sm text-slate-400">
            {pending} request{pending === 1 ? "" : "s"}{" "}
            waiting on a decision.
          </p>
        )}
      </section>

      {error && (
        <div className="rounded-2xl border border-red-900 bg-red-950/30 p-6">
          <p className="text-sm text-red-300">{error}</p>
        </div>
      )}

      <section className="space-y-3">
        {!requests && !error && (
          <p className="text-sm text-slate-500">
            Loading the approval queue...
          </p>
        )}

        {requests && requests.length === 0 && (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
            <p className="text-sm text-slate-500">
              No approval requests. Nothing is waiting on a
              person.
            </p>
          </div>
        )}

        {requests?.map((request) => (
          <RequestCard
            key={request.request_code}
            request={request}
            reviewerName={reviewerName}
            canDecide={canDecide}
            busy={busy === request.id}
            onAct={act}
          />
        ))}
      </section>
    </div>
  );
}

function RequestCard({
  request,
  reviewerName,
  canDecide,
  busy,
  onAct,
}: {
  request: ApprovalRequest;
  reviewerName: string;
  canDecide: boolean;
  busy: boolean;
  onAct: (
    request: ApprovalRequest,
    action: () => Promise<unknown>,
  ) => void;
}) {
  const [reason, setReason] = useState("");

  const reasonText = reason.trim();
  const id = request.id;

  const disabled = busy || !canDecide;

  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">{request.title}</h3>

          {request.description && (
            <p className="mt-1 text-sm text-slate-400">
              {request.description}
            </p>
          )}
        </div>

        <span
          className={`shrink-0 rounded-full border px-3 py-1 text-xs uppercase ${
            STATUS_STYLES[request.status] ??
            "border-slate-700 bg-slate-900 text-slate-400"
          }`}
        >
          {request.status.replace(/_/g, " ")}
        </span>
      </div>

      <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-2 text-xs text-slate-500">
        <div>
          <dt className="uppercase tracking-wider">
            Request
          </dt>
          <dd className="mt-1 text-slate-300">
            {request.request_code}
          </dd>
        </div>

        <div>
          <dt className="uppercase tracking-wider">
            Raised by
          </dt>
          <dd className="mt-1 text-slate-300">
            {request.requested_by}
          </dd>
        </div>

        <div>
          <dt className="uppercase tracking-wider">
            Raised
          </dt>
          <dd className="mt-1 text-slate-300">
            {request.requested_at
              ? new Date(
                  request.requested_at,
                ).toLocaleString()
              : "—"}
          </dd>
        </div>

        {request.reviewed_by && (
          <div>
            <dt className="uppercase tracking-wider">
              Decided by
            </dt>
            <dd className="mt-1 text-slate-300">
              {request.reviewed_by}
            </dd>
          </div>
        )}
      </dl>

      <p className="mt-4 text-xs text-slate-500">
        {STATUS_EXPLANATIONS[request.status] ??
          "No further action is available."}
      </p>

      {request.review_reason && (
        <p className="mt-2 rounded-lg border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">
          Reason on the record: {request.review_reason}
        </p>
      )}

      <div className="mt-5 flex flex-col gap-3 border-t border-slate-800 pt-5">
        {(request.status === "pending" ||
          request.status === "approved" ||
          request.status === "ready_to_execute") && (
          <>
            <label className="block max-w-md">
              <span className="text-xs uppercase tracking-wider text-slate-500">
                Reason
              </span>

              <input
                type="text"
                value={reason}
                onChange={(event) =>
                  setReason(event.target.value)
                }
                placeholder="Required to reject"
                className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
              />
            </label>

            <div className="flex flex-wrap gap-3">
              {request.status === "pending" && (
                <>
                  <Action
                    label="Approve"
                    disabled={disabled}
                    busy={busy}
                    onClick={() =>
                      void onAct(request, () =>
                        reviewApproval(id!, {
                          status: "approved",
                          reviewer: reviewerName,
                          reason: reasonText || null,
                        }),
                      )
                    }
                  />

                  <Action
                    label="Reject"
                    tone="danger"
                    // A rejection with no explanation cannot be
                    // reviewed by anyone later, so the backend
                    // requires one. The button is disabled rather
                    // than failing after the click.
                    disabled={
                      busy || !canDecide || !reasonText
                    }
                    busy={busy}
                    onClick={() =>
                      void onAct(request, () =>
                        reviewApproval(id!, {
                          status: "rejected",
                          reviewer: reviewerName,
                          reason: reasonText,
                        }),
                      )
                    }
                  />
                </>
              )}

              {request.status === "approved" && (
                <Action
                  label="Prepare for execution"
                  disabled={disabled}
                  busy={busy}
                  onClick={() =>
                    void onAct(request, () =>
                      prepareApproval(id!, reviewerName),
                    )
                  }
                />
              )}

              {request.status === "ready_to_execute" && (
                <Action
                  label="Run the simulated execution"
                  tone="simulated"
                  disabled={disabled}
                  busy={busy}
                  onClick={() =>
                    void onAct(request, () =>
                      executeApproval(id!, reviewerName),
                    )
                  }
                />
              )}
            </div>

            {!canDecide && (
              <p className="text-xs text-slate-500">
                Enter your name above to enable these.
              </p>
            )}
          </>
        )}

        {request.events.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs text-slate-500">
              {request.events.length} recorded event
              {request.events.length === 1 ? "" : "s"}
            </summary>

            <ol className="mt-3 space-y-2 border-l border-slate-800 pl-4">
              {request.events.map((event, index) => (
                <li
                  key={event.id ?? index}
                  className="text-xs text-slate-400"
                >
                  <span className="text-slate-300">
                    {event.previous_status
                      ? `${event.previous_status} → `
                      : ""}
                    {event.new_status}
                  </span>{" "}
                  by {event.actor}
                  {event.reason && (
                    <span className="block text-slate-500">
                      {event.reason}
                    </span>
                  )}
                </li>
              ))}
            </ol>
          </details>
        )}
      </div>
    </article>
  );
}

function Action({
  label,
  onClick,
  disabled,
  busy,
  tone = "primary",
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  busy: boolean;
  tone?: "primary" | "danger" | "simulated";
}) {
  const tones = {
    primary:
      "border-emerald-700/60 bg-emerald-950/40 text-emerald-200 hover:bg-emerald-950/70",
    danger:
      "border-rose-800/70 bg-rose-950/40 text-rose-200 hover:bg-rose-950/70",
    simulated:
      "border-indigo-700/60 bg-indigo-950/40 text-indigo-200 hover:bg-indigo-950/70",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg border px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40 ${tones[tone]}`}
    >
      {busy ? "Working..." : label}
    </button>
  );
}
