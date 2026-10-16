/**
 * Types for the AI campus copilot (Phase 13).
 *
 * `answer` is the only field that may come from a language
 * model. `evidence` and `recommendations` are computed in Python
 * and returned beside it, which is what lets a reader verify the
 * prose rather than trust it.
 */

export type CopilotIntent =
  | "OVERVIEW"
  | "ENTITY_ANALYSIS"
  | "INCIDENT_ANALYSIS"
  | "RECOMMENDATION"
  | "WHAT_IF"
  | "EXPLANATION"
  | "UNKNOWN";

export interface CopilotEvidence {
  source: string;
  value: string;
  explanation: string;
}

export interface CopilotRecommendation {
  action: string;
  rationale: string;
  expected_effect: string;

  // Always true. Rendered as a visible badge rather than
  // assumed, so nobody mistakes a suggestion for something that
  // has already happened.
  requires_approval: boolean;

  entity_id: string | null;
  entity_name: string | null;
}

export interface CopilotReply {
  answer: string;
  intent: CopilotIntent;
  evidence: CopilotEvidence[];
  recommendations: CopilotRecommendation[];

  /** "llm" or "deterministic". */
  source: string;

  llm_available: boolean;

  entity_id: string | null;
  entity_name: string | null;
  priority: number | null;

  caveats: string[];

  context: Record<string, unknown>;
}

export interface CopilotMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  reply?: CopilotReply;
  failed?: boolean;
}