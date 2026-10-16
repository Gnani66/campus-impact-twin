"use client";

import { useEffect, useState } from "react";

import { Copilot } from "@/components/copilot/Copilot";

import { getDigitalTwinSnapshot } from "@/lib/api";

interface CopilotWorkspaceProps {
  entityId: string | null;
}

interface Scope {
  id: string | null;
  name: string | null;
  resolved: boolean;
}

/**
 * The copilot page body.
 *
 * RESOLVES THE SCOPE, IT DOES NOT ASSUME IT.
 *
 * A URL can carry an entity id that no longer exists, because
 * zones are deleted and URLs are shared and bookmarked. Rather
 * than labelling the panel with a raw id and letting the first
 * question fail with a 404, the twin is read once to resolve a
 * display name. If the entity is not there, the scope is dropped
 * and the copilot falls back to campus-wide answers, which still
 * works.
 */
export function CopilotWorkspace({
  entityId,
}: CopilotWorkspaceProps) {
  const [scope, setScope] = useState<Scope>(() => ({
    id: entityId,
    name: null,
    resolved: entityId === null,
  }));

  useEffect(() => {
    if (!entityId) {
      // Nothing to resolve. The rendered scope is derived below
      // rather than pushed into state from here, because setting
      // state during an effect body forces a second render pass
      // to reach a value already known from props.
      return;
    }

    let active = true;

    const controller = new AbortController();

    async function resolve() {
      try {
        const snapshot = await getDigitalTwinSnapshot(
          controller.signal,
        );

        if (!active) {
          return;
        }

        const match = snapshot.entities.find(
          (entity) => entity.id === entityId,
        );

        if (match) {
          setScope({
            id: entityId,
            name: match.name,
            resolved: true,
          });
        } else {
          // The zone is not in the twin. Widen the scope rather
          // than showing a panel that answers nothing.
          setScope({ id: null, name: null, resolved: true });
        }
      } catch (err) {
        if (!active) {
          return;
        }

        if (
          err instanceof DOMException &&
          err.name === "AbortError"
        ) {
          return;
        }

        setScope({ id: null, name: null, resolved: true });
      }
    }

    void resolve();

    return () => {
      active = false;
      controller.abort();
    };
  }, [entityId]);

  // The URL is the source of truth for whether a scope was asked
  // for; the resolved name is the only thing that came back from
  // the network. An unresolved scope is shown optimistically and
  // falls back to campus-wide only once the twin has confirmed
  // the zone does not exist.
  const active =
    entityId === null
      ? { id: null, name: null }
      : scope.id === entityId
        ? { id: entityId, name: scope.name }
        : scope.resolved
          ? { id: null, name: null }
          : { id: entityId, name: null };

  return (
    <div className="h-full">
      <Copilot
        entityId={active.id}
        entityName={active.name}
      />
    </div>
  );
}
