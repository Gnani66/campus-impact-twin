import threading

from supabase import (
    Client,
    create_client,
)

from app.core.config import settings


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
    """

    client: Client = getattr(
        _thread_local,
        "client",
        None,
    )

    if client is None:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

        _thread_local.client = client

    return client


supabase: Client = get_supabase()
