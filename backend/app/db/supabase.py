"""
Supabase access.

THE ONE PLACE A RESPONSE IS REPAIRED.

postgrest-py parses a response with pydantic's JSON validator and,
on failure, silently falls back to returning the raw JSON *text*:

    try:
        data = JSONAdapter.validate_json(request_response.content)
    except ValidationError:
        data = request_response.text ...

`validate_json` is recursive, so a deeply nested jsonb column
exceeds Python's recursion limit and raises. The caller then
receives a `str` where the type says `List[Dict]`, and the failure
surfaces far away from the cause: an incident row that cannot be
`**`-unpacked, or `row.get(...)` on a single character.

That is not hypothetical. The `incidents` table stores an
`evidence` jsonb array, and every read of it came back as text:

  - GET /api/v1/campus/{code}/twin returned 500 on
    `IncidentResponse(**incident)`.
  - `intelligence_service._find_open_incident` raised
    `AttributeError: 'str' object has no attribute 'get'` for every
    reading, so incident de-duplication silently stopped working
    and the same incident was raised again and again.

Rather than patch twelve call sites, `get_supabase()` returns a
client whose queries parse that fallback with `json.loads`, which
is iterative and handles the payload the dependency could not.
Everything else is delegated unchanged, so callers are unaware.

This is a workaround for a dependency defect, deliberately
confined to the boundary where the dependency is used. It should
be deleted once postgrest stops swallowing the error, or once its
parser is not recursive.
"""

import json
import logging
import threading
from typing import Any

from supabase import (
    Client,
    create_client,
)

from app.core.config import settings


logger = logging.getLogger(__name__)


# ============================================================
# RESPONSE REPAIR
# ============================================================


def _parse_if_text(response: Any) -> Any:
    """
    Parses `response.data` when the dependency left it as text.

    Returns the response either way, so this can wrap an
    `execute()` call inline.
    """

    data = getattr(response, "data", None)

    if not isinstance(data, str):
        return response

    try:
        parsed = json.loads(data)
    except ValueError as exc:
        # Not JSON at all, so the dependency's fallback was not
        # the cause. Raising here keeps the failure at the
        # boundary instead of letting a string travel on as
        # though it were rows.
        raise TypeError(
            "Supabase returned a response body that is "
            "neither rows nor JSON."
        ) from exc

    response.data = parsed

    return response


class _Query:
    """
    A query builder that repairs its own response.

    The postgrest builder is fluent, so every intermediate call
    returns another builder. Each of those is wrapped too, so the
    repair applies at the end of a chain of any length without
    the caller knowing.
    """

    __slots__ = ("_builder",)

    def __init__(self, builder: Any) -> None:
        self._builder = builder

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._builder, name)

        if not callable(attribute):
            return attribute

        def call(*args: Any, **kwargs: Any) -> Any:
            result = attribute(*args, **kwargs)

            # Still a builder: keep wrapping so `.eq(...)`,
            # `.order(...)` and the rest chain as usual.
            if hasattr(result, "execute"):
                return _Query(result)

            return result

        return call

    def execute(self) -> Any:
        return _parse_if_text(self._builder.execute())


class _TableBuilder:
    """The client surface this project uses: `.table(name)`."""

    __slots__ = ("_client",)

    def __init__(self, client: Any) -> None:
        self._client = client

    def table(self, name: str) -> _Query:
        return _Query(self._client.table(name))

    def __getattr__(self, name: str) -> Any:
        # Anything else the client exposes (`auth`, `storage`,
        # `rpc`) is passed straight through. None of it is used
        # here, so nothing is wrapped that has not been checked.
        return getattr(self._client, name)


# ============================================================
# CLIENT
# ============================================================


_thread_local = threading.local()


def get_supabase() -> Client:
    """
    Returns a Supabase client bound to the current thread.

    supabase-py builds on httpx, which negotiates HTTP/2 with
    PostgREST. An httpx client is not safe to share across
    threads: two concurrent requests can corrupt the same
    HTTP/2 connection and fail with
    `httpx.ReadError: [Errno 35]`.

    FastAPI runs synchronous endpoints in a thread pool, so
    each worker thread gets its own client. Connections are
    still pooled and reused within a thread.

    The return type is the `Client` interface the callers use.
    The value is a wrapper that repairs responses; see the module
    docstring for why.
    """

    client = getattr(_thread_local, "client", None)

    if client is None:
        client = _TableBuilder(
            create_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
        )

        _thread_local.client = client

    return client  # type: ignore[return-value]


supabase: Client = get_supabase()
