"""
Tests for the incidents API surface.

Two things this endpoint owes a caller, both of which are easy to
regress and invisible in the response otherwise:

  - the query parameters arrive at the service under the names the
    service uses. `?zone=` in the URL is `zone_code` in Python, and
    a mismatch would not raise: the filter would simply never be
    applied, and every list would silently ignore the zone a person
    asked for.
  - the zone code is in the response. An incident stores a zone id,
    which is not a label.

Filtering and labelling themselves are covered against the fake
store in `tests/test_intelligence_service.py`; these tests are
about the wiring between the two.
"""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def _capture(monkeypatch, rows=None):
    """
    Replaces the service call and returns the arguments it was
    given, so the test can assert on what the endpoint passed on.
    """

    captured = {}

    def _record(**kwargs):
        captured.update(kwargs)

        return list(rows or [])

    monkeypatch.setattr(
        "app.services.intelligence_service."
        "intelligence_service.list_incidents",
        _record,
    )

    return captured


def _incident_row(**overrides):
    row = {
        "id": "incident-1",
        "category": "environment",
        "severity": "critical",
        "status": "open",
        "title": "Overheating in an occupied zone",
        "description": "Temperature above the safe band.",
        "impact_score": 91.0,
        "confidence_score": 0.94,
        "detection_method": "deterministic_rule",
        "evidence": [],
        "campus_id": "campus-1",
        "building_id": "building-1",
        "zone_id": "zone-1",
        "zone_code": "LH01",
        "sensor_id": "sensor-1",
        "equipment_id": None,
        "detected_at": "2026-10-16T01:00:00Z",
    }

    row.update(overrides)

    return row


# ============================================================
# THE ZONE PARAMETER
# ============================================================


class TestZoneParameter:
    def test_zone_in_the_url_arrives_as_zone_code(
        self, monkeypatch
    ):
        """
        The twin's entity panel links here as `?zone=LH01`.
        """

        captured = _capture(monkeypatch)

        response = client.get("/api/v1/incidents?zone=LH01")

        assert response.status_code == 200
        assert captured["zone_code"] == "LH01"

    def test_no_zone_leaves_the_filter_unset(
        self, monkeypatch
    ):
        captured = _capture(monkeypatch)

        assert client.get("/api/v1/incidents").status_code == 200
        assert captured["zone_code"] is None

    def test_zone_composes_with_the_existing_filters(
        self, monkeypatch
    ):
        captured = _capture(monkeypatch)

        client.get(
            "/api/v1/incidents"
            "?zone=LH01&status=open&severity=critical"
            "&category=environment&limit=5"
        )

        assert captured["zone_code"] == "LH01"
        assert captured["status"] == "open"
        assert captured["severity"] == "critical"
        assert captured["category"] == "environment"
        assert captured["limit"] == 5


# ============================================================
# THE RESPONSE
# ============================================================


class TestResponse:
    def test_zone_code_is_returned(self, monkeypatch):
        _capture(monkeypatch, rows=[_incident_row()])

        body = client.get("/api/v1/incidents").json()

        assert body[0]["zone_code"] == "LH01"

    def test_incident_without_a_zone_reports_null(
        self, monkeypatch
    ):
        _capture(
            monkeypatch,
            rows=[
                _incident_row(
                    zone_id=None, zone_code=None
                )
            ],
        )

        body = client.get("/api/v1/incidents").json()

        assert body[0]["zone_code"] is None

    def test_zone_code_is_optional_for_older_rows(
        self, monkeypatch
    ):
        """
        A row stored before the field existed has no code. It must
        still be served, with the field simply absent, rather than
        failing the whole list.
        """

        row = _incident_row()
        row.pop("zone_code")

        _capture(monkeypatch, rows=[row])

        body = client.get("/api/v1/incidents").json()

        assert body[0]["zone_code"] is None
        assert body[0]["id"] == "incident-1"

    def test_empty_result_is_an_empty_list(
        self, monkeypatch
    ):
        _capture(monkeypatch, rows=[])

        body = client.get("/api/v1/incidents").json()

        assert body == []
