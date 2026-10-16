"""
Tests for the configured CORS origin list.

The failure this guards against is quiet. A browser asking for an
origin that is not allowed gets back a perfectly good response
with no Access-Control-Allow-Origin header, and reports it as
ERR_FAILED. To a developer watching the console that is
indistinguishable from the API being down, so it gets fixed in
the wrong place — by restarting a backend that was already fine.
"""

from app.core.config import Settings


def _settings(value: str) -> Settings:
    return Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
        cors_allowed_origins=value,
    )


def test_default_allows_both_loopback_spellings():
    """
    localhost and 127.0.0.1 are different origins to a browser
    even on one machine, so a developer reaches the frontend as
    one or the other without noticing.
    """

    origins = Settings(
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-key",
    ).cors_origin_list

    assert "http://localhost:3000" in origins
    assert "http://127.0.0.1:3000" in origins


def test_split_on_commas():
    origins = _settings(
        "http://localhost:3000,http://127.0.0.1:3000"
    ).cors_origin_list

    assert origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]


def test_surrounding_whitespace_is_ignored():
    """
    A space after a comma is easy to leave in a .env line and
    would otherwise become part of the origin string, which then
    never matches anything.
    """

    origins = _settings(
        "http://localhost:3000, http://localhost:3001"
    ).cors_origin_list

    assert origins == [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_empty_entries_are_dropped():
    """
    A trailing comma, or a blank line in the middle of the list,
    must not produce an empty origin. An empty string in
    allow_origins is matched by nothing and, depending on the
    version, has been a way to end up allowing everything.
    """

    origins = _settings(
        "http://localhost:3000,,http://localhost:3001,"
    ).cors_origin_list

    assert origins == [
        "http://localhost:3000",
        "http://localhost:3001",
    ]


def test_a_second_frontend_port_can_be_added():
    """
    `next dev` falls back to 3001 when something already holds
    3000. That is the situation this setting exists for.
    """

    origins = _settings(
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001"
    ).cors_origin_list

    assert "http://localhost:3001" in origins
    assert "http://127.0.0.1:3001" in origins