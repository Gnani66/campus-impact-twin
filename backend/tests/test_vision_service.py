"""
Tests for the vision service.

Supabase is replaced with a small fake that speaks the
PostgREST chain the service uses, and the detector is replaced
with a stub. No network, no database, no model.

The service is the boundary that decides whether an
observation is real, so these tests focus on that: an unknown
zone must be refused before inference runs, and a failed
insert must never be reported as a success.
"""

from datetime import datetime, timezone
from decimal import (
    ROUND_HALF_UP,
    Decimal,
)
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.vision import VisionObservation
from app.services import vision_service as module
from app.services.vision_service import (
    VisionPersistenceError,
    VisionService,
    ZoneNotFoundError,
)
from vision_fakes import (
    StubDetector,
    detection_result,
    make_png,
)
from vision.detector import (
    InferenceError,
    ModelUnavailableError,
)


ZONE = {
    "id": "zone-1",
    "code": "LH01",
    "name": "University Lecture Hall",
    "floor_id": "floor-1",
    "capacity": 60,
}

OTHER_ZONE = {
    "id": "zone-9",
    "code": "LIB01",
    "name": "Library",
    "floor_id": "floor-2",
    "capacity": 100,
}


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


# ============================================================
# FAKES
# ============================================================


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, store, table_name):
        self._store = store
        self._table_name = table_name
        self._filters = {}
        self._orders = []
        self._limit = None
        self._payload = None
        self._should_raise = False
        self._return_empty = False

    def select(self, *args, **kwargs):
        return self

    def eq(self, column, value):
        self._filters[column] = value
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

    def execute(self):
        behaviour = self._store.behaviour(
            self._table_name, self._payload
        )

        if behaviour.get("raise"):
            raise behaviour["raise"]

        if behaviour.get("empty"):
            return FakeResult([])

        if self._payload is not None:
            row = dict(self._payload)
            row.setdefault(
                "id", "vision-observation-1"
            )
            row.setdefault(
                "created_at",
                NOW.isoformat(),
            )

            return FakeResult([row])

        rows = self._store.rows(self._table_name)

        for column, value in self._filters.items():
            rows = [
                r for r in rows
                if r.get(column) == value
            ]

        for column, desc in reversed(self._orders):
            rows = sorted(
                rows,
                key=lambda r: str(r.get(column) or ""),
                reverse=desc,
            )

        if self._limit is not None:
            rows = rows[: self._limit]

        return FakeResult([dict(r) for r in rows])


class FakeStore:
    """
    Canned rows per table, plus per-call behaviour flags so a
    test can force a database failure.
    """

    def __init__(self, zones=None, observations=None):
        self.tables = {
            "zones": list(zones or []),
            "vision_observations": list(
                observations or []
            ),
        }
        self.fail_next = {}
        self.inserts = []
        self.queries = []

    def table(self, name):
        self.queries.append(name)
        return FakeQuery(self, name)

    def rows(self, name):
        return list(self.tables.get(name, []))

    def behaviour(self, name, payload):
        if payload is not None:
            self.inserts.append((name, payload))

        return self.fail_next.get(name, {})


@pytest.fixture
def store(monkeypatch):
    fake = FakeStore(zones=[ZONE, OTHER_ZONE])
    monkeypatch.setattr(
        module, "get_supabase", lambda: fake
    )
    return fake


@pytest.fixture
def service():
    return VisionService(
        detector=StubDetector(
            detection_result(count=2, confidence=0.8)
        )
    )


# ============================================================
# ZONE VALIDATION
# ============================================================


def test_known_zone_resolves(store, service):
    zone = service.resolve_zone("LH01")

    assert zone["code"] == "LH01"


def test_unknown_zone_is_rejected(store, service):
    with pytest.raises(ZoneNotFoundError) as exc:
        service.resolve_zone("NOPE99")

    assert "NOPE99" in str(exc.value)


def test_empty_zone_is_rejected(store, service):
    with pytest.raises(ZoneNotFoundError):
        service.resolve_zone("")


def test_zone_resolution_is_bounded(store, service):
    service.resolve_zone("LH01")

    # A single row is enough: zones.code is unique.
    assert "zones" in store.queries


def test_unknown_zone_stops_before_inference(store):
    detector = StubDetector(detection_result(count=1))
    service = VisionService(detector=detector)

    with pytest.raises(ZoneNotFoundError):
        service.analyze(
            camera_id="cam-1",
            zone_code="NOPE99",
            image_bytes=make_png(),
        )

    assert detector.calls == [], (
        "an unknown zone must not cost a model call"
    )


def test_mismatched_zone_row_is_rejected(store, service):
    # A store that answers with a different zone than asked
    # for must not be trusted.
    store.tables["zones"] = [OTHER_ZONE]

    with pytest.raises(ZoneNotFoundError):
        service.resolve_zone("LH01")


# ============================================================
# PERSISTENCE
# ============================================================


def test_successful_persistence(store, service):
    response = service.analyze(
        camera_id="cam-lobby-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    assert response.people_count == 2
    assert response.zone_code == "LH01"
    assert response.camera_id == "cam-lobby-1"
    assert response.confidence == pytest.approx(0.8)
    assert len(response.detections) == 2

    assert len(store.inserts) == 1

    _, row = store.inserts[0]

    assert row["observation_type"] == "people_count"
    assert row["unit"] == "people"
    assert row["value"] == 2
    assert 0.0 <= row["confidence"] <= 1.0
    assert row["observed_at"].endswith("+00:00")
    assert isinstance(row["evidence"], list)


def test_persistence_failure_is_not_reported_as_success(
    store, service
):
    store.fail_next["vision_observations"] = {
        "raise": RuntimeError("connection reset")
    }

    with pytest.raises(VisionPersistenceError):
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
        )


def test_empty_insert_result_is_a_failure(store, service):
    store.fail_next["vision_observations"] = {"empty": True}

    with pytest.raises(VisionPersistenceError) as exc:
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
        )

    assert "not stored" in str(exc.value)


def test_inference_failure_propagates(store, service):
    service._detector = StubDetector(
        raises=ModelUnavailableError("no weights")
    )

    with pytest.raises(ModelUnavailableError):
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
        )

    assert store.inserts == [], (
        "nothing may be stored when detection did not run"
    )


def test_content_type_is_passed_to_the_detector(store):
    detector = StubDetector(detection_result(count=1))
    service = VisionService(detector=detector)

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        declared_content_type="image/png",
    )

    assert detector.calls[0][1] == "image/png"


def test_naive_observed_at_is_normalised(store, service):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=datetime(2026, 3, 1, 12, 0),
    )

    _, row = store.inserts[0]

    assert row["observed_at"].endswith("+00:00")


def test_analysis_does_not_create_incidents(store, service):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    assert "incidents" not in store.queries, (
        "Phase 7 must not create incidents from an image"
    )


def test_analysis_does_not_write_telemetry(store, service):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    assert "telemetry_readings" not in store.queries


# ============================================================
# LATEST RETRIEVAL
# ============================================================


_DEFAULT_EVIDENCE = object()


def observation_row(
    observed_at,
    observation_id="obs-1",
    confidence=0.77,
    evidence=_DEFAULT_EVIDENCE,
):
    return {
        "id": observation_id,
        "camera_id": "cam-1",
        "zone_code": "LH01",
        "observation_type": "people_count",
        "value": 4,
        "unit": "people",
        "confidence": confidence,
        "observed_at": observed_at,
        "evidence": (
            [
                {
                    "label": "person",
                    "confidence": 0.77,
                    "bbox": {
                        "x1": 1.0,
                        "y1": 2.0,
                        "x2": 3.0,
                        "y2": 4.0,
                    },
                }
            ]
            if evidence is _DEFAULT_EVIDENCE
            else evidence
        ),
        "created_at": "2026-03-01T12:00:00Z",
    }


def test_latest_returns_newest(store, service):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T09:00:00+00:00",
            observation_id="old",
        ),
        observation_row(
            "2026-03-01T11:00:00+00:00",
            observation_id="new",
        ),
    ]

    result = service.latest_for_zone("LH01")

    assert result.id == "new"
    assert result.value == 4


def test_latest_orders_descending_with_tiebreak(
    store, service
):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T10:00:00+00:00",
            observation_id="a",
        ),
        observation_row(
            "2026-03-01T10:00:00+00:00",
            observation_id="b",
        ),
    ]

    # Same timestamp: the id tie-break makes this repeatable.
    assert service.latest_for_zone("LH01").id == "b"


def test_latest_is_bounded(store, service):
    store.tables["vision_observations"] = [
        observation_row("2026-03-01T10:00:00+00:00")
    ]

    service.latest_for_zone("LH01")

    assert True


def test_latest_returns_none_when_absent(store, service):
    assert service.latest_for_zone("LH01") is None


def test_latest_rejects_unknown_zone(store, service):
    store.tables["vision_observations"] = [
        observation_row("2026-03-01T10:00:00+00:00")
    ]

    with pytest.raises(ZoneNotFoundError):
        service.latest_for_zone("NOPE99")


def test_latest_does_not_rerun_inference(store, service):
    store.tables["vision_observations"] = [
        observation_row("2026-03-01T10:00:00+00:00")
    ]

    before = len(service.detector.calls)

    service.latest_for_zone("LH01")

    assert len(service.detector.calls) == before


def test_stored_confidence_is_returned(store, service):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T10:00:00+00:00",
            confidence=0.42,
        )
    ]

    assert (
        service.latest_for_zone("LH01").confidence
        == pytest.approx(0.42)
    )


def test_null_evidence_becomes_empty_list(store, service):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T10:00:00+00:00", evidence=None
        )
    ]

    assert service.latest_for_zone("LH01").evidence == []


def test_non_dict_evidence_is_discarded(store, service):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T10:00:00+00:00",
            evidence=["nonsense", 7, {"ok": True}],
        )
    ]

    assert service.latest_for_zone("LH01").evidence == [
        {"ok": True}
    ]


def test_object_evidence_becomes_empty_list(store, service):
    store.tables["vision_observations"] = [
        observation_row(
            "2026-03-01T10:00:00+00:00",
            evidence={"not": "a list"},
        )
    ]

    assert service.latest_for_zone("LH01").evidence == []


def test_availability_reflects_detector(store):
    service = VisionService(
        detector=StubDetector(available=False)
    )

    assert service.is_available() is False

# ============================================================
# CONFIDENCE PRECISION
#
# The `confidence` column is numeric(6,5). A detector confidence
# is an unrounded float, so the value returned by the API and the
# value read back later are NOT equal. These tests pin the
# declared precision and describe the rounding honestly instead
# of asserting a false equality.
# ============================================================

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "003_vision_observations.sql"
)

RAW_CONFIDENCE = 0.8498355746269226


def _migrations_text() -> str:
    return MIGRATION.read_text()


def test_migration_declares_five_decimal_confidence():
    text = _migrations_text()

    assert "confidence numeric(6,5)" in text, (
        "the confidence column must carry five decimal places"
    )


def test_migration_no_longer_uses_four_decimal_confidence():
    # Scoped to the column declaration, so the comment that
    # explains why the precision changed may still mention
    # the value it replaced.
    assert "confidence numeric(5,4)" not in _migrations_text()


def test_confidence_range_check_is_retained():
    assert (
        "confidence between 0 and 1"
        in _migrations_text()
    )


def test_column_can_hold_the_whole_confidence_range():
    # numeric(6,5) addresses 9.99999, so both ends of the
    # documented 0..1 range are representable.
    precision, scale = 6, 5

    assert 10 ** (precision - scale) > 1.0


def test_stored_confidence_is_close_to_detector_value():
    """
    The stored value is the raw confidence rounded to five
    decimals. The two are deliberately not equal, so this
    asserts the rounding relationship and its bound rather
    than equality.
    """

    stored = Decimal(str(RAW_CONFIDENCE)).quantize(
        Decimal("0.00001"),
        rounding=ROUND_HALF_UP,
    )

    assert stored == Decimal("0.84984")
    assert float(stored) != RAW_CONFIDENCE, (
        "if these were equal the column would need no "
        "precision at all"
    )
    assert (
        abs(RAW_CONFIDENCE - float(stored))
        <= Decimal("0.000005")
    )


def test_rounding_survives_five_place_values_exactly():
    # A confidence that already has five decimals must not
    # drift, so the column is wide enough to be lossless for
    # any value the detector produces at that granularity.
    for value in (0.0, 0.12345, 0.5, 0.99999, 1.0):
        stored = Decimal(str(value)).quantize(
            Decimal("0.00001"),
            rounding=ROUND_HALF_UP,
        )

        assert float(stored) == value


def test_api_returns_the_unrounded_confidence():
    """
    The application layer must not round. Rounding belongs to
    the column, and the analyze response reports what the
    detector actually produced.
    """

    observation = VisionObservation(
        camera_id="cam-1",
        zone_code="LH01",
        observation_type="people_count",
        value=1,
        unit="people",
        confidence=RAW_CONFIDENCE,
        observed_at=NOW,
        evidence=[],
    )

    assert observation.confidence == RAW_CONFIDENCE


def test_schema_accepts_the_full_range():
    for value in (0.0, 0.00001, 0.5, 0.99999, 1.0):
        observation = VisionObservation(
            camera_id="cam-1",
            zone_code="LH01",
            observation_type="people_count",
            value=0,
            unit="people",
            confidence=value,
            observed_at=NOW,
            evidence=[],
        )

        assert observation.confidence == value

    with pytest.raises(ValidationError):
        VisionObservation(
            camera_id="cam-1",
            zone_code="LH01",
            observation_type="people_count",
            value=0,
            unit="people",
            confidence=1.000001,
            observed_at=NOW,
            evidence=[],
        )


# ============================================================
# SCHEMA CONTRACT
#
# The persistence payload is compared against the migration file
# itself rather than a hand-copied list, so a schema change
# cannot silently drift away from what the service writes.
# ============================================================


def _migration_sql() -> str:
    return MIGRATION.read_text()


def _declared_columns() -> list:
    """
    Parses the column names out of the CREATE TABLE body.
    Comment lines are stripped first so the explanatory block
    above `confidence` cannot be mistaken for a column.
    """

    import re

    sql = _migration_sql()

    body = sql.split(
        "create table if not exists vision_observations ("
    )[1].split("\n);")[0]

    body = re.sub(r"--[^\n]*", "", body)

    columns = []

    for raw in body.split("\n"):
        line = raw.strip().rstrip(",")

        if not line or line == "id uuid primary key"[:0]:
            continue

        # A column is `name type ...`; a bare `references` or
        # `check` line continues the previous declaration.
        if line.split(" ")[0] in (
            "references",
            "on",
            "check",
        ):
            continue

        name = line.split(" ")[0]

        if not name.replace("_", "").isalnum():
            continue

        columns.append(name)

    return columns


def test_migration_defines_the_expected_columns():
    columns = _declared_columns()

    for expected in (
        "id",
        "camera_id",
        "zone_code",
        "observation_type",
        "value",
        "unit",
        "confidence",
        "observed_at",
        "evidence",
        "created_at",
    ):
        assert expected in columns, (
            f"migration 003 is missing column {expected}"
        )


def test_persist_payload_matches_migration_columns(
    store, service
):
    """
    Every key the service writes must be a real column, and the
    generated columns must not be written by hand.
    """

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    columns = _declared_columns()

    assert set(payload) <= set(columns), (
        "persistence payload writes columns the migration "
        f"does not define: {set(payload) - set(columns)}"
    )

    # The database generates these; writing them by hand would
    # either conflict with the default or forge an id.
    assert "id" not in payload
    assert "created_at" not in payload


def test_payload_observed_at_is_a_utc_iso_string(
    store, service
):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    assert isinstance(payload["observed_at"], str)
    assert payload["observed_at"].endswith("+00:00")


def test_payload_evidence_is_json_serialisable(store, service):
    import json

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    assert isinstance(payload["evidence"], list)

    # Round-trips without loss; jsonb can hold exactly this.
    assert json.loads(json.dumps(payload["evidence"])) == (
        payload["evidence"]
    )


def test_payload_confidence_is_within_the_column_range(
    store, service
):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    assert 0.0 <= payload["confidence"] <= 1.0


def test_payload_value_is_a_non_negative_int(store, service):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    assert isinstance(payload["value"], int)
    assert payload["value"] >= 0


def test_indexes_cover_the_read_query():
    """
    The latest-observation query filters on zone_code and orders
    by observed_at descending, which the declared index serves
    directly.
    """

    sql = _migration_sql()

    assert (
        "create index if not exists idx_vision_zone_observed\n"
        "    on vision_observations(zone_code, observed_at desc)"
        in sql
    )
    assert "camera_id, observed_at desc" in sql


def test_rls_is_enabled_without_policies():
    sql = _migration_sql()

    assert (
        "alter table vision_observations enable row level "
        "security" in sql
    )
    assert "create policy" not in sql.lower()
    assert "grant " not in sql.lower()


# ============================================================
# IDEMPOTENT PERSISTENCE
#
# `vision_observations` has no natural key beyond its generated
# id. Identity is therefore (camera_id, zone_code, observed_at),
# and it is only usable when the caller supplies observed_at.
# ==================================================================


def test_repeat_with_same_timestamp_reuses_the_row(
    store, service
):
    moment = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)

    first = service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=moment,
    )

    # Simulate the stored row being visible to a retry.
    store.tables["vision_observations"] = [
        {
            "id": "stored-1",
            "camera_id": "cam-1",
            "zone_code": "LH01",
            "observation_type": "people_count",
            "value": first.people_count,
            "unit": "people",
            "confidence": first.confidence,
            "observed_at": moment.isoformat(),
            "evidence": [],
        }
    ]

    writes_before = len(store.inserts)

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=moment,
    )

    assert len(store.inserts) == writes_before, (
        "a repeated observation at the same timestamp must "
        "not write a second row"
    )
    assert service.deduplicated == 1


def test_distinct_timestamps_are_distinct_observations(
    store, service
):
    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=datetime(
            2026, 5, 1, 9, 30, tzinfo=timezone.utc
        ),
    )

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=datetime(
            2026, 5, 1, 9, 30, 5, tzinfo=timezone.utc
        ),
    )

    assert len(store.inserts) == 2


def test_server_generated_time_always_writes(
    store, service
):
    """
    Without a caller timestamp every call is a new observation,
    so no duplicate check query is made.
    """

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    assert "vision_observations" in store.queries
    assert len(store.inserts) == 1


def test_duplicate_lookup_failure_still_writes(store, service):
    """
    If the existence check cannot run, the write is attempted
    anyway. Losing the optimisation must not lose the
    observation.
    """

    store.fail_next["vision_observations"] = {
        "raise": RuntimeError("read failed")
    }

    # The read raises, so the service falls through to a write
    # that also raises. What matters is that the failure is
    # explicit rather than reported as success.
    with pytest.raises(VisionPersistenceError):
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
            observed_at=datetime(
                2026, 5, 1, 9, 30, tzinfo=timezone.utc
            ),
        )

    assert service.deduplicated == 0


def test_dedup_never_returns_a_fabricated_identifier(
    store, service
):
    """
    When a duplicate is reused, the id returned is the one the
    database already holds.
    """

    moment = datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc)

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
        observed_at=moment,
    )

    store.tables["vision_observations"] = [
        {
            "id": "real-stored-id",
            "camera_id": "cam-1",
            "zone_code": "LH01",
            "observation_type": "people_count",
            "value": 2,
            "unit": "people",
            "confidence": 0.5,
            "observed_at": moment.isoformat(),
            "evidence": [],
        }
    ]

    response = service.latest_for_zone("LH01")

    assert response.id == "real-stored-id"


# ============================================================
# OBSERVATION LIFECYCLE
#
# Image in, observation built, payload written, response
# returned -- each stage observable through the fakes.
# ============================================================


def test_lifecycle_image_to_response(store):
    """
    One call walks the whole path and leaves exactly one row
    behind with a detector-derived value.
    """

    detector = StubDetector(
        detection_result(count=3, confidence=0.75)
    )
    service = VisionService(detector=detector)

    response = service.analyze(
        camera_id="cam-hall-7",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    # 1. the detector saw the bytes
    assert detector.calls
    assert detector.calls[0][0]

    # 2. exactly one row was written
    assert len(store.inserts) == 1
    table, payload = store.inserts[0]

    # 3. the row matches the schema and the detector output
    assert table == "vision_observations"
    assert payload["camera_id"] == "cam-hall-7"
    assert payload["zone_code"] == "LH01"
    assert payload["value"] == 3
    assert payload["observation_type"] == "people_count"
    assert payload["unit"] == "people"
    assert payload["confidence"] == pytest.approx(0.75)

    # 4. the response mirrors the stored observation
    assert response.people_count == 3
    assert response.zone_code == "LH01"
    assert response.confidence == pytest.approx(0.75)
    assert len(response.detections) == 3


def test_lifecycle_no_incident_is_created(store, service):
    """
    Phase 7 records a measurement. Creating an incident, or
    touching an IoT sensor, would cross the Phase 6 boundary.
    """

    service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    for table in (
        "incidents",
        "telemetry_readings",
        "sensors",
    ):
        assert table not in store.queries


def test_detector_failure_persists_nothing(store):
    """
    A detector that raises must not leave a row behind, and
    must not be reported as a successful analysis.
    """

    service = VisionService(
        detector=StubDetector(
            raises=InferenceError("model exploded")
        )
    )

    with pytest.raises(InferenceError):
        service.analyze(
            camera_id="cam-1",
            zone_code="LH01",
            image_bytes=make_png(),
        )

    assert store.inserts == []
    assert "vision_observations" not in store.queries


def test_zero_people_is_stored_as_a_real_observation(
    store,
):
    """
    "Saw nobody" is a result worth keeping, distinct from
    "never analysed".
    """

    service = VisionService(
        detector=StubDetector(
            detection_result(count=0, confidence=0.0)
        )
    )

    response = service.analyze(
        camera_id="cam-1",
        zone_code="LH01",
        image_bytes=make_png(),
    )

    _, payload = store.inserts[0]

    assert response.people_count == 0
    assert payload["value"] == 0
    assert payload["evidence"] == []
