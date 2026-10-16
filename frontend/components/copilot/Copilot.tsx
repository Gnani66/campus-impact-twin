"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { askCopilot } from "@/lib/api";

import type {
  CopilotMessage,
  CopilotReply,
} from "@/lib/copilot";

/**
 * Suggested questions.
 *
 * Seeded from the intents the backend actually classifies, rather
 * than generic prompts. Each one is a request the copilot can
 * answer from stored data, so a first-time visitor sees something
 * that works instead of a blank box.
 */
const SUGGESTIONS = [
  "What needs attention right now?",
  "Why is the lecture hall critical?",
  "What should we do about it?",
];

function messageId(): string {
  return `m-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

/**
 * The copilot panel.
 *
 * SHOWS ITS OWN PROVENANCE.
 *
 * Every reply renders the answer beside the evidence the backend
 * computed and a badge saying whether the prose came from the
 * local model or was composed directly. A copilot that silently
 * answers from a model the operator cannot see is worse than no
 * copilot, because it invites trust that has not been earned.
 */
export function Copilot({
  entityId,
  entityName,
}: {
  entityId?: string | null;
  entityName?: string | null;
}) {
  const [messages, setMessages] = useState<
    CopilotMessage[]
  >([]);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const endRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "end",
    });
  }, [messages, loading]);

  const ask = useCallback(
    async (raw: string) => {
      const message = raw.trim();

      if (!message || loading) {
        return;
      }

      setInput("");

      setMessages((current) => [
        ...current,
        {
          id: messageId(),
          role: "user",
          content: message,
        },
      ]);

      setLoading(true);

      try {
        const reply: CopilotReply =
          await askCopilot(message, entityId);

        setMessages((current) => [
          ...current,
          {
            id: messageId(),
            role: "assistant",
            content: reply.answer,
            reply,
          },
        ]);
      } catch (err) {
        setMessages((current) => [
          ...current,
          {
            id: messageId(),
            role: "assistant",
            content:
              err instanceof Error
                ? err.message
                : "The copilot is unreachable.",
            failed: true,
          },
        ]);
      } finally {
        setLoading(false);
        inputRef.current?.focus();
      }
    },
    [entityId, loading],
  );

  const scoped = Boolean(entityId);

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-200 p-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          AI Operations Copilot
        </p>

        <h2 className="mt-1 text-lg font-semibold text-slate-900">
          Ask the campus
        </h2>

        <p className="mt-1 text-sm text-slate-500">
          {scoped ? (
            <>
              Scoped to{" "}
              <span className="font-medium text-slate-700">
                {entityName ?? entityId}
              </span>
              . Answers cite readings stored for this zone.
            </>
          ) : (
            "Answers are built from stored sensor readings. The model explains; it never decides."
          )}
        </p>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-5">
        {messages.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-slate-500">
              Try one of these:
            </p>

            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => ask(suggestion)}
                className="block w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

        {messages.map((message) =>
          message.role === "user" ? (
            <div
              key={message.id}
              className="ml-8 rounded-xl bg-slate-900 p-3 text-sm whitespace-pre-wrap text-white"
            >
              {message.content}
            </div>
          ) : (
            <div
              key={message.id}
              className="mr-8 space-y-3"
            >
              <div
                className={`rounded-xl p-3 text-sm whitespace-pre-wrap ${
                  message.failed
                    ? "bg-red-50 text-red-700"
                    : "bg-slate-100 text-slate-800"
                }`}
              >
                {message.content}
              </div>

              {message.reply && (
                <ReplyDetails reply={message.reply} />
              )}
            </div>
          ),
        )}

        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <span className="h-2 w-2 animate-pulse rounded-full bg-slate-400" />

            Reading stored campus state...
          </div>
        )}

        <div ref={endRef} />
      </div>

      <div className="border-t border-slate-200 p-4">
        <div className="flex gap-2">
          <input
            ref={inputRef}
            value={input}
            onChange={(event) =>
              setInput(event.target.value)
            }
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                void ask(input);
              }
            }}
            placeholder={
              scoped
                ? `Ask about ${entityName ?? "this zone"}...`
                : "Ask about the campus..."
            }
            className="flex-1 rounded-xl border border-slate-300 px-4 py-3 text-sm outline-none focus:border-slate-500"
          />

          <button
            type="button"
            onClick={() => void ask(input)}
            disabled={loading || !input.trim()}
            className="rounded-xl bg-slate-900 px-5 py-3 text-sm font-medium text-white disabled:opacity-50"
          >
            Ask
          </button>
        </div>
      </div>
    </section>
  );
}

/**
 * The verified basis for an answer.
 *
 * Rendered by default for every reply. The prose is the
 * model's, and the evidence beside it is not, so a reader can
 * check the answer instead of taking it on faith.
 */
function ReplyDetails({
  reply,
}: {
  reply: CopilotReply;
}) {
  const [open, setOpen] = useState(false);

  const count = reply.evidence.length;

  return (
    <div className="rounded-xl border border-slate-200">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs text-slate-500 transition hover:bg-slate-50"
      >
        <span className="flex items-center gap-2">
          <span
            className={`inline-block h-2 w-2 rounded-full ${
              reply.llm_available
                ? "bg-emerald-500"
                : "bg-amber-400"
            }`}
          />

          {reply.llm_available
            ? "Explained by the local model"
            : "Composed from stored readings"}

          <span className="text-slate-400">
            · {count} verified{" "}
            {count === 1 ? "fact" : "facts"}
          </span>
        </span>

        <span className="text-slate-400">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-100 p-3">
          {reply.evidence.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-slate-400">
                Verified evidence
              </p>

              <ul className="space-y-1.5">
                {reply.evidence.map((item, index) => (
                  <li
                    key={`${item.source}-${index}`}
                    className="text-xs"
                  >
                    <div className="text-slate-600">
                      <span className="font-medium text-slate-800">
                        {item.value}
                      </span>{" "}
                      <span className="text-slate-400">
                        ({item.source})
                      </span>
                    </div>

                    {/*
                      The explanation is what makes a bare value
                      checkable. A threshold breach reads as
                      "exceeded" until you see which threshold,
                      so it is shown rather than hidden.
                    */}
                    {item.explanation && (
                      <p className="text-slate-500">
                        {item.explanation}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {reply.recommendations.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-slate-400">
                Suggested actions
              </p>

              <ul className="space-y-2">
                {reply.recommendations.map(
                  (item, index) => (
                    <li
                      key={index}
                      className="rounded-lg bg-amber-50 p-2 text-xs text-slate-700"
                    >
                      <p className="font-medium">
                        {item.action}
                      </p>

                      <p className="mt-0.5 text-slate-500">
                        {item.rationale}
                      </p>

                      {item.requires_approval && (
                        <span className="mt-1 inline-block rounded bg-amber-200 px-1.5 py-0.5 text-[10px] font-medium text-amber-900">
                          Requires human approval
                        </span>
                      )}
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}

          {reply.caveats.length > 0 && (
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-widest text-slate-400">
                Notes
              </p>

              <ul className="space-y-1">
                {reply.caveats.map((caveat, index) => (
                  <li
                    key={index}
                    className="text-xs text-slate-500"
                  >
                    {caveat}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-[10px] text-slate-400">
            Intent: {reply.intent.toLowerCase()}
            {reply.priority !== null && (
              <>
                {" "}
                · priority {reply.priority}
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}