"""
The local model seam (Phase 13).

Everything model-specific lives in this file. Swapping Ollama for
another runtime, or for a hosted API, is a change here and nowhere
else.

THE DETERMINISTIC FALLBACK IS THE POINT, NOT A CONVENIENCE.

`generate` returns None whenever the model is unreachable, slow,
or unusable. It never raises. Ollama is frequently not running on a
fresh machine, a demo laptop may have no model pulled, and a 3B
model can take tens of seconds on first token. If the copilot
depended on this call succeeding it would dead-end at exactly the
wrong moment. The caller composes its own answer from the same
facts when this returns None, so the copilot answers every
question correctly with the model switched off.

That is also why the timeout is generous but finite, and why a
failure is reported rather than retried. Retrying a local
inference that has timed out just delays the deterministic answer
by another minute.
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx


logger = logging.getLogger(__name__)


OLLAMA_URL = os.getenv(
    "OLLAMA_URL", "http://127.0.0.1:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL", "qwen2.5:3b"
)

# Short enough that a demo does not appear to hang, long enough
# that a 3B model on CPU finishes a short answer. A cold start
# with no model loaded is the slow case.
REQUEST_TIMEOUT_SECONDS = float(
    os.getenv("COPILOT_TIMEOUT_SECONDS", "45")
)

# Low temperature on purpose. The prose restates supplied facts;
# creativity is not the goal and a higher temperature only
# invites variation from the evidence.
TEMPERATURE = float(
    os.getenv("COPILOT_TEMPERATURE", "0.2")
)

# Caps generation length. The copilot answers operational
# questions, and a 3B model left to ramble will pad an answer
# that should be three lines.
MAX_TOKENS = int(
    os.getenv("COPILOT_MAX_TOKENS", "600")
)


class LLMUnavailable(Exception):
    """The local model could not be used."""


async def is_available() -> bool:
    """
    Whether the local runtime is reachable.

    Used to label the copilot's response source so a reader knows
    whether prose was written by a model or composed by code.
    """

    try:
        async with httpx.AsyncClient(
            timeout=3
        ) as client:
            response = await client.get(
                f"{OLLAMA_URL}/api/tags"
            )

            return response.status_code == 200

    except Exception:
        return False


async def generate(
    system_prompt: str,
    user_prompt: str,
) -> Optional[str]:
    """
    Generates an explanation.

    Returns the model's text, or None if it could not be reached
    or returned nothing usable. Never raises: an unavailable model
    is an expected condition on a machine that may not have one
    running, and the caller has a deterministic answer ready.
    """

    payload: Dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": MAX_TOKENS,
        },
    }

    try:
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
            )

            response.raise_for_status()

            body = response.json()

    except Exception as exc:
        # Logged once at info: this is an expected condition, not
        # an error, and a stack trace on every request would be
        # noise.
        logger.info(
            "Local model unavailable (%s: %s); the "
            "deterministic answer will be used instead",
            type(exc).__name__,
            exc,
        )

        return None

    text = (body.get("response") or "").strip()

    if not text:
        logger.info(
            "Local model returned no usable text; using the "
            "deterministic answer"
        )

        return None

    return text


async def health() -> Dict[str, Any]:
    """
    Runtime status, for diagnostics and the copilot response.
    """

    try:
        async with httpx.AsyncClient(
            timeout=3
        ) as client:
            response = await client.get(
                f"{OLLAMA_URL}/api/tags"
            )

            if response.status_code != 200:
                return {
                    "available": False,
                    "model": OLLAMA_MODEL,
                    "url": OLLAMA_URL,
                }

            models = [
                entry.get("name")
                for entry in response.json().get("models", [])
            ]

            return {
                "available": True,
                "model": OLLAMA_MODEL,
                "url": OLLAMA_URL,
                "installed_models": models,
                "configured_model_installed": (
                    OLLAMA_MODEL in models
                    or any(
                        name
                        and name.split(":")[0]
                        == OLLAMA_MODEL.split(":")[0]
                        for name in models
                    )
                ),
            }

    except Exception as exc:
        return {
            "available": False,
            "model": OLLAMA_MODEL,
            "url": OLLAMA_URL,
            "error": type(exc).__name__,
        }