"""
Tests for error-detail disclosure across the read APIs.

An unexpected exception carries whatever the database or driver
had to say: table names, column names, hostnames, connection
strings, occasionally a fragment of a query. None of that may
reach a client, because these endpoints are reachable by anyone
who can reach the port and the backend has no authentication.

The rule under test: the traceback goes to the log, the client
gets a fixed message. Every case here fails a request whose
exception text contains a recognisable secret, so a regression
that interpolates the exception into the response is caught by
asserting on the body rather than by inspection.
"""

import pytest

from fastapi import HTTPException


# The marker stands in for the internal detail a real driver
# exception would carry. It must never appear in a response.
SECRET = "supabase-xyz.supabase.co:5432/postgres"


def _boom(*args, **kwargs):
    raise RuntimeError(
        f"connection to {SECRET} failed: "
        "relation public.incidents does not exist"
    )


def _response_body(exc: HTTPException) -> str:
    return str(exc.detail)


# ============================================================
# INCIDENTS
# ============================================================


def test_incident_summary_hides_the_exception(
    monkeypatch,
):
    from app.api.incidents import get_incident_summary

    monkeypatch.setattr(
        "app.services.intelligence_service."
        "intelligence_service.summary",
        _boom,
    )

    with pytest.raises(HTTPException) as caught:
        get_incident_summary(campus_code="CIT-MAIN")

    assert SECRET not in _response_body(caught.value)
    assert (
        "relation" not in _response_body(caught.value)
    )


def test_incident_summary_logs_the_traceback(
    monkeypatch, caplog
):
    """
    The detail is removed from the response, not merely hidden.
    It must still reach the log, or the failure becomes
    invisible and undebuggable.
    """

    from app.api.incidents import get_incident_summary

    monkeypatch.setattr(
        "app.services.intelligence_service."
        "intelligence_service.summary",
        _boom,
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(HTTPException):
            get_incident_summary(campus_code="CIT-MAIN")

    assert SECRET in caplog.text


def test_incident_list_hides_the_exception(monkeypatch):
    from app.api.incidents import get_incidents

    monkeypatch.setattr(
        "app.services.intelligence_service."
        "intelligence_service.list_incidents",
        _boom,
    )

    with pytest.raises(HTTPException) as caught:
        get_incidents(
            campus_code="CIT-MAIN",
            status_filter=None,
            severity=None,
            category=None,
            zone_code=None,
            limit=50,
        )

    assert SECRET not in _response_body(caught.value)


def test_incident_list_logs_the_traceback(
    monkeypatch, caplog
):
    from app.api.incidents import get_incidents

    monkeypatch.setattr(
        "app.services.intelligence_service."
        "intelligence_service.list_incidents",
        _boom,
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(HTTPException):
            get_incidents(
                campus_code="CIT-MAIN",
                status_filter=None,
                severity=None,
                category=None,
                zone_code=None,
                limit=50,
            )

    assert SECRET in caplog.text


# ============================================================
# CAMPUS TWIN
# ============================================================


def test_campus_twin_hides_the_exception(monkeypatch):
    from app.api import campus

    # The twin route reads through the shared Supabase client,
    # so the failure is injected at that boundary.
    monkeypatch.setattr(
        campus, "get_supabase", _boom
    )

    with pytest.raises(HTTPException) as caught:
        campus.get_campus_twin(campus_code="CIT-MAIN")

    body = _response_body(caught.value)

    assert SECRET not in body
    assert "relation" not in body


def test_campus_twin_logs_the_traceback(
    monkeypatch, caplog
):
    from app.api import campus

    monkeypatch.setattr(
        campus, "get_supabase", _boom
    )

    with caplog.at_level("ERROR"):
        with pytest.raises(HTTPException):
            campus.get_campus_twin(campus_code="CIT-MAIN")

    assert SECRET in caplog.text


# ============================================================
# WHOLE-SURFACE GUARD
# ============================================================

# Endpoints that surface an unexpected failure to a client.
PROTECTED = (
    ("app.api.incidents", "get_incident_summary"),
    ("app.api.incidents", "get_incidents"),
    ("app.api.campus", "get_campus_twin"),
)


@pytest.mark.parametrize(
    "module_name,function_name", PROTECTED
)
def test_module_defines_a_logger(module_name, function_name):
    """
    Every module that converts an exception into a response must
    have a logger. `incidents.py` previously had none, so its
    failures were disclosed to the client and recorded nowhere.
    """

    import importlib

    module = importlib.import_module(module_name)

    assert hasattr(module, "logger"), (
        f"{module_name} builds HTTP error responses but "
        f"defines no logger; failures would be invisible"
    )
    assert callable(getattr(module, function_name))