import { CopilotWorkspace } from "@/components/copilot/CopilotWorkspace";

/**
 * Resolves the entity scope from the URL.
 *
 * The parameter is an entity id, not a free-text name. The
 * backend resolves it against the twin's own identifiers, so a
 * crafted URL can only ever name a zone that exists, and the
 * copilot can never be pointed at something the twin has not
 * already judged.
 */
export async function CopilotScope({
  searchParams,
}: {
  searchParams: Promise<
    Record<string, string | string[] | undefined>
  >;
}) {
  const params = await searchParams;

  const raw = params.entity;

  const entityId =
    typeof raw === "string" && raw.trim()
      ? raw.trim().slice(0, 100)
      : null;

  return (
    <CopilotWorkspace entityId={entityId} />
  );
}
