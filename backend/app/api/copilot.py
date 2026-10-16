"""
Copilot API (Phase 13).

One endpoint. The copilot has no write surface at all, which is
the point of the phase: it reads verified campus state and returns
prose plus structured evidence, and there is nothing here that
could change a building.

Errors are handled precisely where a specific condition exists.
The local model being unavailable is NOT an error: the copilot
falls back to a deterministic answer composed from the same facts
and says so in `source` and `caveats`, so a demo degrades to
something correct rather than to an error page.
"""

import logging

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from app.ai import llm
from app.ai.schemas import (
    CopilotRequest,
    CopilotResponse,
)
from app.services.copilot_service import process_message
from app.services.digital_twin_service import (
    digital_twin_service,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/copilot",
    tags=["AI Copilot"],
)


FAULT_DETAIL = "The copilot could not answer."


def _resolve_entity(
    entity_id: str,
) -> dict:
    """
    Looks up the entity the question is scoped to.

    Resolution goes through the twin's own lookup, so the copilot
    can only ever discuss a zone the twin already knows about.
    """

    entity = digital_twin_service.entity(entity_id)

    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No campus entity matching '{entity_id}'.",
        )

    return entity.model_dump()


@router.post(
    "/ask",
    response_model=CopilotResponse,
    summary="Ask a question about current campus conditions",
)
async def ask_copilot(
    request: CopilotRequest,
) -> CopilotResponse:
    """
    Answers an operational question from stored campus state.

    The `evidence` and `recommendations` arrays are computed
    deterministically in Python and are correct whether or not a
    language model was involved. `answer` is prose and may be
    model-written or composed directly; `source` says which.

    Every recommendation carries `requires_approval=true`. Nothing
    in this path can apply, schedule or execute anything.
    """

    try:
        snapshot = digital_twin_service.snapshot()

        entity = (
            _resolve_entity(request.entity_id)
            if request.entity_id
            else None
        )

        return await process_message(
            message=request.message,
            twin_snapshot=snapshot.model_dump(),
            entity=entity,
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("The copilot failed to answer")

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=FAULT_DETAIL,
        ) from exc


@router.get(
    "/health",
    summary="Local model runtime status",
)
async def copilot_health() -> dict:
    """
    Whether the local model runtime is reachable.

    Separate from `/ask` so a client can tell "the model is not
    running" apart from "the copilot is broken". The copilot
    answers correctly either way; only the wording of the answer
    changes.
    """

    status_payload = await llm.health()

    return {
        "copilot_available": True,
        "llm": status_payload,
        "deterministic_fallback": True,
    }