"""
Tests for the correlation API.

The endpoint is where a judge will try to make the engine claim
something it cannot support, so the tests cover both the happy
path and the ways a caller might try to smuggle evidence in.
"""

import pytest

from fastapi import HTTPException

from app.schemas.correlation import (
    CorrelationRequest,
    CorrelationResponse,
)


def _verdict(**overrides) -> dict:
    base = {
        "zone_code": "LH01",
        "result_status": "confirmed_candidate",
        "root_cause": (
            "Potential energy waste during low occupancy"
        ),
        "evidence_score": 100.0,
        "confidence_score": 100.0,
        "occupancy": 0.0,
        "energy_kw": 8.5,
        "expected_energy_kw": 2.0,
        "energy_ratio": 4.25,
        "occupancy_ratio": 0.0,
        "occupancy_state": "potentially_unoccupied",
        "schedule_active": True,
        "evidence": [
            {
                "name": "vision_reliable",
                "passed": True,
                "score": 1.0,
                "reason": "ok",
            }
        ],
        "correlation_run_id": "run-1",
    }

    base.update(overrides)

    return base


# ============================================================
# SCHEMAS
# ============================================================


class TestRequestSchema:
    def test_zone_code_is_required(self):
        with pytest.raises(Exception):
            CorrelationRequest()

    def test_zone_code_cannot_be_blank(self):
        with pytest.raises(Exception):
            CorrelationRequest(zone_code="")

    def test_zone_code_length_is_bounded(self):
        with pytest.raises(Exception):
            CorrelationRequest(zone_code="x" * 51)

    def test_schedule_defaults_to_active(self):
        """
        Defaulting to active is the honest default: a zone is
        assumed to be in use unless the caller says otherwise,
        so a forgotten field cannot manufacture a finding
        outside operating hours.
        """

        assert CorrelationRequest(
            zone_code="LH01"
        ).schedule_active is True

    def test_extra_evidence_is_rejected(self):
        """
        A caller cannot post its own occupancy or energy
        figures. The engine reads those from storage, so
        accepting them would let a verdict be manufactured.
        """

        with pytest.raises(Exception):
            CorrelationRequest(
                zone_code="LH01",
                occupancy=0,
                energy_kw=8.5,
            )


class TestResponseSchema:
    def test_round_trips(self):
        response = CorrelationResponse(**_verdict())

        assert response.zone_code == "LH01"
        assert response.result_status == (
            "confirmed_candidate"
        )
        assert response.evidence[0].name == "vision_reliable"

    def test_accepts_a_review_verdict(self):
        response = CorrelationResponse(
            **_verdict(
                result_status="needs_review",
                root_cause=None,
                confidence_score=0.0,
            )
        )

        assert response.root_cause is None
        assert response.confidence_score == 0.0


# ============================================================
# ENDPOINTS
# ============================================================


class TestEndpoints:
    def test_analyze_returns_the_verdict(self, monkeypatch):
        from app.api import correlation as api

        monkeypatch.setattr(
            api.correlation_service,
            "correlate",
            lambda zone_code, schedule_active: _verdict(
                zone_code=zone_code,
                schedule_active=schedule_active,
            ),
        )

        response = api.analyze_zone(
            CorrelationRequest(
                zone_code="LH01", schedule_active=True
            )
        )

        assert response.result_status == (
            "confirmed_candidate"
        )

    def test_analyze_passes_the_schedule_through(
        self, monkeypatch
    ):
        from app.api import correlation as api

        seen = {}

        def fake(zone_code, schedule_active):
            seen["zone_code"] = zone_code
            seen["schedule_active"] = schedule_active

            return _verdict()

        monkeypatch.setattr(
            api.correlation_service, "correlate", fake
        )

        api.analyze_zone(
            CorrelationRequest(
                zone_code="LH01", schedule_active=False
            )
        )

        assert seen["schedule_active"] is False

    def test_analyze_hides_internal_failure(
        self, monkeypatch,
    ):
        """
        A database error names the host and connection detail.
        It is logged and never returned.
        """

        from app.api import correlation as api

        def boom(*args, **kwargs):
            raise RuntimeError(
                "connection to db.supabase.co:5432 failed"
            )

        monkeypatch.setattr(
            api.correlation_service, "correlate", boom
        )

        with pytest.raises(HTTPException) as caught:
            api.analyze_zone(
                CorrelationRequest(zone_code="LH01")
            )

        assert caught.value.status_code == 500

        # The driver's own words must not survive.
        assert "db.supabase.co" not in caught.value.detail
        assert caught.value.detail == (
            "Correlation analysis failed."
        )

    def test_zone_runs_returns_the_trail(self, monkeypatch):
        from app.api import correlation as api

        monkeypatch.setattr(
            api.correlation_service,
            "recent_runs",
            lambda zone_code, limit: [
                {"id": "run-1", "result_status": "normal"}
            ],
        )

        payload = api.zone_runs(zone_code="LH01", limit=20)

        assert payload["zone_code"] == "LH01"
        assert len(payload["runs"]) == 1

    def test_zone_runs_hides_internal_failure(
        self, monkeypatch,
    ):
        from app.api import correlation as api

        def boom(*args, **kwargs):
            raise RuntimeError("relation does not exist")

        monkeypatch.setattr(
            api.correlation_service, "recent_runs", boom
        )

        with pytest.raises(HTTPException) as caught:
            api.zone_runs(zone_code="LH01", limit=20)

        assert caught.value.status_code == 500

        # The driver's own words must not survive. The detail is
        # a fixed sentence.
        assert (
            "relation does not exist"
            not in caught.value.detail
        )
        assert caught.value.detail == (
            "Correlation analysis failed."
        )

    def test_routes_are_registered(self):
        from app.main import app

        paths = {r.path for r in app.routes}

        assert "/api/v1/correlation/analyze" in paths
        assert "/api/v1/correlation/zone/{zone_code}" in paths

    def test_existing_routes_survive(self):
        """
        Adding the correlation engine must not displace anything
        Phase 4 to 7 already registered.
        """

        from app.main import app

        paths = {r.path for r in app.routes}

        for expected in (
            "/health",
            "/api/v1/campus/{campus_code}/twin",
            "/api/v1/incidents",
            "/api/v1/incidents/summary",
            "/api/v1/vision/analyze",
            "/api/v1/vision/status",
            "/api/v1/vision/zone/{zone_code}/latest",
        ):
            assert expected in paths