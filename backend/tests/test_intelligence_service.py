"""
Tests for the intelligence service.

The service is the part that can spam the incidents table, so
these tests focus on the behaviour that protects it: context
resolution, deduplication, bounded evidence history, and never
letting an intelligence failure raise into the telemetry path.
"""

import itertools
from datetime import datetime, timedelta, timezone

import pytest

from app.services import intelligence_service as module
from app.services.intelligence_service import (
    IntelligenceService,
)


ZONE_ID = "zone-1"
CAMPUS_ID = "campus-1"
BUILDING_ID = "building-1"
FLOOR_ID = "floor-1"
SENSOR_ID = "sensor-1"


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def iso(offset_seconds: float = 0.0) -> str:
    return (
        (NOW + timedelta(seconds=offset_seconds))
        .isoformat()
        .replace("+00:00", "Z")
    )


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """
    Supports the PostgREST chain the service uses:
    select / eq / in_ / order / limit / insert / update.
    """

    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._filters = {}
        self._orders = []
        self._limit = None
        self._payload = None

    def select(self, *_columns):
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def in_(self, column, values):
        self._filters[column] = list(values)
        return self

    def order(self, column, desc=False):
        self._orders.append((column, desc))
        return self

    def limit(self, count):
        self._limit = count
        return self

    def insert(self, payload):
        self._payload = payload
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def _rows(self):
        rows = [
            dict(row)
            for row in self._store.get(self._name, [])
        ]

        for column, wanted in self._filters.items():
            if isinstance(wanted, list):
                rows = [
                    row
                    for row in rows
                    if row.get(column) in wanted
                ]
            else:
                rows = [
                    row
                    for row in rows
                    if row.get(column) == wanted
                ]

        # Chained .order() calls sort by each column in turn,
        # most significant first.
        for column, descending in self._orders:
            rows.sort(
                key=lambda row, c=column: (
                    row.get(c) is None,
                    row.get(c),
                ),
                reverse=descending,
            )

        if self._limit is not None:
            rows = rows[: self._limit]

        return rows

    def execute(self):
        if self._payload is not None:
            return FakeResult(self._apply())

        return FakeResult(self._rows())

    def _apply(self):
        table = self._store.setdefault(self._name, [])

        if self._payload is not None and (
            self._rows()
            and "id" in (self._rows()[0] or {})
        ) and self._filters.get("id"):
            # Update path.
            for row in table:
                if row.get("id") == self._filters["id"]:
                    row.update(self._payload)
                    return [dict(row)]

            return []

        rows = (
            self._payload
            if isinstance(self._payload, list)
            else [self._payload]
        )

        ids = itertools.count(1)

        for row in rows:
            stored = dict(row)
            stored.setdefault(
                "id", f"incident-{next(ids)}"
            )
            stored.setdefault("status", "open")
            table.append(stored)

        return [dict(row) for row in rows]


class FakeClient:
    def __init__(self, store):
        self.store = store
        self.reads = []

    def table(self, name):
        if name not in self.store:
            raise AssertionError(
                f"unexpected table: {name}"
            )

        self.reads.append(name)

        return FakeQuery(self.store, name)


@pytest.fixture
def store():
    return {
        "zones": [
            {
                "id": ZONE_ID,
                "code": "LH01",
                "capacity": 60,
                "floor_id": FLOOR_ID,
            }
        ],
        "floors": [
            {"id": FLOOR_ID, "building_id": BUILDING_ID}
        ],
        "buildings": [
            {"id": BUILDING_ID, "campus_id": CAMPUS_ID}
        ],
        "campuses": [{"id": CAMPUS_ID, "code": "CIT-MAIN"}],
        "sensors": [
            {
                "id": SENSOR_ID,
                "code": "CO2-LH01",
                "zone_id": ZONE_ID,
                "equipment_id": None,
            }
        ],
        "incidents": [],
        "telemetry_readings": [],
    }


@pytest.fixture
def service(store, monkeypatch):
    client = FakeClient(store)

    monkeypatch.setattr(
        module, "get_supabase", lambda: client
    )

    return IntelligenceService(clock=lambda: NOW)


def seed_occupancy(store, people=40.0):
    """
    Occupancy is resolved from stored telemetry, not from the
    triggering reading, so a test that needs occupancy context
    has to have recorded some.
    """

    store["telemetry_readings"] = [
        reading("occupancy", people)
    ]


def reading(
    metric: str,
    value: float,
    offset: float = 0.0,
):
    return {
        "zone_id": ZONE_ID,
        "sensor_id": SENSOR_ID,
        "metric": metric,
        "value": value,
        "unit": "ppm",
        "timestamp": iso(offset),
    }


# ============================================================
# Context resolution
# ============================================================


class TestContext:
    def test_zone_context_is_cached(
        self, service, store, monkeypatch
    ):
        client = FakeClient(store)

        monkeypatch.setattr(
            module, "get_supabase", lambda: client
        )

        for _ in range(5):
            service._zone_context(ZONE_ID)

        assert client.reads.count("zones") == 1

    def test_unknown_zone_returns_none(self, service):
        assert service._zone_context("nope") is None

    def test_campus_is_reached_through_floor_and_building(
        self, service
    ):
        """zones have no campus_id of their own. The traversal
        zones -> floors -> buildings -> campuses is the only way
        to attribute an incident."""

        context = service._zone_context(ZONE_ID)

        assert context.campus_id == CAMPUS_ID
        assert context.building_id == BUILDING_ID
        assert context.floor_id == FLOOR_ID

    def test_missing_floor_drops_the_context(
        self, service, store
    ):
        """A zone whose floor cannot be resolved has no
        defensible campus, so no incident is attributed."""

        store["floors"] = []

        assert service._zone_context(ZONE_ID) is None

    def test_missing_building_drops_the_context(
        self, service, store
    ):
        store["buildings"] = []

        assert service._zone_context(ZONE_ID) is None

    def test_capacity_comes_from_the_zone(
        self, service
    ):
        service._zone_context(ZONE_ID)

        assert service._capacity(ZONE_ID) == 60

    def test_reading_without_zone_is_ignored(
        self, service
    ):
        row = reading("co2", 2000.0)
        row["zone_id"] = None

        assert service.process_reading(row) is None


# ============================================================
# Rule evaluation through the service
# ============================================================


class TestEvaluation:
    def test_healthy_reading_creates_nothing(
        self, service
    ):
        assert (
            service.process_reading(
                reading("co2", 450.0)
            )
            is None
        )
        assert service.created == 0

    def test_co2_breach_creates_incident(
        self, service, store
    ):
        seed_occupancy(store, 40.0)

        incident = service.process_reading(
            reading("co2", 1900.0)
        )

        assert incident is not None
        assert incident["category"] == "environment"
        assert incident["severity"] == "critical"
        assert incident["status"] == "open"
        assert (
            incident["detection_method"]
            == "deterministic_rule"
        )

    def test_evidence_carries_the_full_chain(
        self, service, store
    ):
        seed_occupancy(store, 40.0)

        incident = service.process_reading(
            reading("co2", 1900.0)
        )

        evidence = incident["evidence"][0]

        assert evidence["rule"] == "co2_critical"
        assert evidence["co2_ppm"] == 1900.0
        assert evidence["occupancy"] == 40.0
        assert evidence["zone"] == "LH01"
        assert evidence["sensor_id"] == SENSOR_ID
        assert evidence["capacity"] == 60
        assert evidence["impact_score"] > 0
        assert evidence["confidence_score"] > 0
        assert evidence["observed_at"]

    def test_unknown_metric_is_ignored(
        self, service
    ):
        assert (
            service.process_reading(
                reading("radiation", 5.0)
            )
            is None
        )

    def test_statistics_are_tracked(self, service):
        service.process_reading(
            reading("co2", 450.0)
        )
        service.process_reading(
            reading("co2", 1900.0)
        )

        stats = service.stats

        assert stats["evaluated"] == 2
        assert stats["fired"] == 1
        assert stats["created"] == 1


# ============================================================
# Deduplication
#
# This is what stops a persistent condition from producing one
# incident per reading.
# ============================================================


class TestDeduplication:
    def _breach(self, service, store, value=1900.0):
        seed_occupancy(store, 40.0)

        return service.process_reading(
            reading("co2", value)
        )

    def test_repeated_breach_creates_one_incident(
        self, service, store
    ):
        for _ in range(20):
            self._breach(service, store)

        assert len(store["incidents"]) == 1
        assert service.created == 1

    def test_repeat_refreshes_the_same_incident(
        self, service, store
    ):
        self._breach(service, store)

        second = self._breach(service, store, 2500.0)

        assert second["id"] == "incident-1"
        assert service.deduplicated == 1

    def test_refresh_keeps_the_worst_impact(
        self, service, store
    ):
        self._breach(service, store, 1900.0)
        self._breach(service, store, 3500.0)

        incident = service.list_incidents()[0]

        assert float(incident["impact_score"]) >= 80.0

    def test_observation_history_is_bounded(
        self, service, store
    ):
        for _ in range(60):
            self._breach(service, store)

        incident = service.list_incidents()[0]

        observations = incident["evidence"][0].get(
            "observations", []
        )

        assert len(observations) <= 50

    def test_different_rules_are_separate_incidents(
        self, service, store
    ):
        seed_occupancy(store, 58.0)

        service.process_reading(
            reading("co2", 1900.0)
        )
        service.process_reading(
            reading("temperature", 30.5)
        )

        assert len(store["incidents"]) == 2

    def test_resolved_incident_does_not_absorb_new_ones(
        self, service, store
    ):
        self._breach(service, store)

        store["incidents"][0]["status"] = "resolved"

        service.process_reading(
            reading("co2", 1900.0)
        )

        assert len(store["incidents"]) == 2

    def test_incident_outside_window_is_not_deduped(
        self, service, store
    ):
        self._breach(service, store)

        old = NOW - timedelta(hours=2)
        store["incidents"][0]["detected_at"] = (
            old.isoformat().replace("+00:00", "Z")
        )

        service.process_reading(
            reading("co2", 1900.0)
        )

        assert len(store["incidents"]) == 2


# ============================================================
# Energy baseline
# ============================================================


class TestEnergyBaseline:
    def _seed_energy(self, store, values):
        store["telemetry_readings"] = [
            reading("energy", value, offset=index)
            for index, value in enumerate(values)
        ]

    def test_energy_fires_against_baseline(
        self, service, store
    ):
        self._seed_energy(
            store, [0.35] * 20
        )

        incident = service.process_reading(
            reading("energy", 8.5)
        )

        assert incident is not None
        assert incident["category"] == "energy"

    def test_baseline_ignores_a_sustained_fault(
        self, service, store
    ):
        """The baseline must not chase the fault, or the rule
        would quietly stop firing during a long incident."""

        self._seed_energy(
            store, [0.35] * 10 + [8.5] * 10
        )

        incident = service.process_reading(
            reading("energy", 8.5)
        )

        assert incident is not None

    def test_no_baseline_means_no_incident(
        self, service, store
    ):
        store["telemetry_readings"] = []

        assert (
            service.process_reading(
                reading("energy", 8.5)
            )
            is None
        )


# ============================================================
# Failure isolation
# ============================================================


class TestFailureIsolation:
    def test_a_bad_row_does_not_stop_the_batch(
        self, service
    ):
        rows = [
            {"metric": "co2", "value": None},
            reading("co2", 1900.0),
        ]

        service.process_batch(rows)

        assert service.errors == 0

    def test_exceptions_are_counted_not_raised(
        self, service, monkeypatch
    ):
        def boom(_row):
            raise RuntimeError("database on fire")

        monkeypatch.setattr(
            service, "process_reading", boom
        )

        # Must not raise.
        assert (
            service.process_batch(
                [reading("co2", 1900.0)]
            )
            == []
        )
        assert service.errors == 1


# ============================================================
# Queries
# ============================================================


class TestQueries:
    def test_summary_counts_by_severity(
        self, service, store
    ):
        store["incidents"] = [
            {"campus_id": CAMPUS_ID, "severity": "critical",
             "status": "open",
             "impact_score": 95.0, "detected_at": iso()},
            {"campus_id": CAMPUS_ID, "severity": "high",
             "status": "open",
             "impact_score": 70.0, "detected_at": iso()},
            {"campus_id": CAMPUS_ID, "severity": "high",
             "status": "resolved",
             "impact_score": 65.0, "detected_at": iso()},
        ]

        summary = service.summary("CIT-MAIN")

        assert summary.total_incidents == 3
        assert summary.critical == 1
        assert summary.high == 2
        assert summary.open_incidents == 2
        assert summary.highest_impact == 95.0

    def test_summary_for_unknown_campus_is_zero(
        self, service
    ):
        summary = service.summary("NOPE")

        assert summary.total_incidents == 0

    def test_list_filters_by_severity(
        self, service, store
    ):
        store["incidents"] = [
            {"campus_id": CAMPUS_ID, "severity": "critical",
             "status": "open",
             "impact_score": 95.0, "detected_at": iso()},
            {"campus_id": CAMPUS_ID, "severity": "low",
             "status": "open",
             "impact_score": 30.0, "detected_at": iso()},
        ]

        rows = service.list_incidents(severity="critical")

        assert len(rows) == 1

    def test_list_is_sorted_by_impact(
        self, service, store
    ):
        store["incidents"] = [
            {"campus_id": CAMPUS_ID, "severity": "low",
             "status": "open",
             "impact_score": 20.0, "detected_at": iso()},
            {"campus_id": CAMPUS_ID, "severity": "critical",
             "status": "open",
             "impact_score": 99.0, "detected_at": iso()},
        ]

        rows = service.list_incidents()

        assert rows[0]["impact_score"] == 99.0
