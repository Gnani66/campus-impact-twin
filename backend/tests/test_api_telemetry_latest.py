"""
Latest telemetry endpoint tests.

Offline: a fake PostgREST client and a fake registry, so no
Supabase credentials, no network and no MQTT are involved.

The fake records every operation it is asked to perform, and
raises on any write, which is how "this endpoint never writes"
is asserted rather than assumed.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api import campus as campus_api
from app.main import app


UTC = timezone.utc

CAMPUS_ID = "0287767e-0000-4000-8000-000000000001"
BUILDING_ID = "94362040-0000-4000-8000-000000000002"
FLOOR_ID = "66467706-0000-4000-8000-000000000003"
ZONE_ID = "26f134ea-0000-4000-8000-000000000004"

OTHER_ZONE_ID = "aaaaaaaa-0000-4000-8000-0000000000aa"
OTHER_CAMPUS_ID = "cccccccc-0000-4000-8000-0000000000cc"

URL = "/api/v1/campus/CIT-MAIN/telemetry/latest"

T0 = datetime(2026, 3, 3, 10, 0, tzinfo=UTC)


def sensor_ids() -> dict:
    return {
        "CO2-LH01": "f19733c7-0000-4000-8000-00000000000c",
        "ENERGY-LH01": "d1acf785-0000-4000-8000-00000000000e",
        "HUM-LH01": "07c1dda4-0000-4000-8000-00000000000d",
        "OCC-LH01": "107705e8-0000-4000-8000-00000000000f",
        "TEMP-LH01": "e15e0fc8-0000-4000-8000-00000000000a",
    }


UNITS = {
    "CO2-LH01": ("co2", "ppm"),
    "ENERGY-LH01": ("energy", "kW"),
    "HUM-LH01": ("humidity", "%"),
    "OCC-LH01": ("occupancy", "people"),
    "TEMP-LH01": ("temperature", "°C"),
}


class FakeEntry:
    """Minimal stand-in for a registry SensorEntry."""

    def __init__(
        self, code, sensor_id, zone_id=ZONE_ID,
        zone_code="LH01",
    ):
        metric, unit = UNITS[code]

        # The real registry holds UUID objects, not strings.
        self.sensor_id = UUID(sensor_id)
        self.sensor_code = code
        self.sensor_type = metric
        self.unit = unit
        self.status = "active"
        self.metric = metric

        self.campus_code = "CIT-MAIN"
        self.campus_id = CAMPUS_ID
        self.building_code = "ACADEMIC-BLK-A"
        self.building_id = BUILDING_ID
        self.floor_code = "A-F1"
        self.floor_id = FLOOR_ID
        self.zone_code = zone_code
        self.zone_id = zone_id


class FakeRegistry:
    def __init__(self, entries):
        self._entries = list(entries)

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)

    def get_by_id(self, sensor_id):
        for entry in self._entries:
            if entry.sensor_id == sensor_id:
                return entry

        raise KeyError(str(sensor_id))


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    """
    Records the operation chain. Any write verb raises, so the
    endpoint cannot pass these tests if it writes.
    """

    def __init__(self, name, store, calls):
        self._name = name
        self._store = store
        self._calls = calls
        self._filters = {}
        self._order = []
        self._limit = None

    def _record(self, verb, column=None, value=None):
        self._calls.append(
            {
                "table": self._name,
                "verb": verb,
                "column": column,
                "value": value,
                "limit": self._limit,
                "order": list(self._order),
            }
        )

    def select(self, columns):
        self._record("select", value=columns)
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def in_(self, column, values):
        self._filters[column] = list(values)
        return self

    def order(self, column, desc=False):
        self._order.append((column, desc))
        return self

    def limit(self, size):
        self._limit = size
        return self

    def insert(self, *_args, **_kwargs):
        raise AssertionError("endpoint must never insert")

    def update(self, *_args, **_kwargs):
        raise AssertionError("endpoint must never update")

    def delete(self, *_args, **_kwargs):
        raise AssertionError("endpoint must never delete")

    def upsert(self, *_args, **_kwargs):
        raise AssertionError("endpoint must never upsert")

    def execute(self):
        # Record the finished query, including limit and
        # order, which are applied after select().
        self._calls.append(
            {
                "table": self._name,
                "verb": "execute",
                "column": None,
                "value": dict(self._filters),
                "limit": self._limit,
                "order": list(self._order),
            }
        )

        rows = [
            dict(row)
            for row in self._store.get(self._name, [])
        ]

        for column, value in self._filters.items():
            if isinstance(value, list):
                rows = [
                    row
                    for row in rows
                    if row.get(column) in value
                ]
            else:
                rows = [
                    row
                    for row in rows
                    if row.get(column) == value
                ]

        for column, desc in reversed(self._order):
            rows.sort(
                key=lambda row: str(row.get(column)),
                reverse=desc,
            )

        if self._limit is not None:
            rows = rows[: self._limit]

        return FakeResult(rows)


class FakeSupabase:
    def __init__(self, rows=None, error: Exception = None):
        self.tables = {
            "campuses": [
                {"id": CAMPUS_ID, "code": "CIT-MAIN"}
            ],
            "telemetry_readings": rows or [],
        }
        self.calls = []
        self._error = error

    def table(self, name):
        self.calls.append(name)

        if self._error is not None:
            raise self._error

        return FakeTable(name, self.tables, self.calls)


def reading(
    code,
    value,
    timestamp,
    row_id="00000000-0000-4000-8000-000000000000",
    zone_id=ZONE_ID,
    source="simulator",
    quality="good",
    metadata=None,
):
    metric, unit = UNITS[code]

    return {
        "id": row_id,
        "sensor_id": sensor_ids()[code],
        "metric": metric,
        "value": value,
        "unit": unit,
        "timestamp": timestamp.isoformat(),
        "source": source,
        "quality": quality,
        "campus_id": CAMPUS_ID,
        "building_id": BUILDING_ID,
        "floor_id": FLOOR_ID,
        "zone_id": zone_id,
        "equipment_id": None,
        "metadata": (
            metadata if metadata is not None else {"simulated": True}
        ),
    }


@pytest.fixture
def registry() -> FakeRegistry:
    return FakeRegistry(
        [
            FakeEntry(code, sensor_id)
            for code, sensor_id in sensor_ids().items()
        ]
    )


@pytest.fixture
def client(monkeypatch, registry) -> TestClient:
    """
    Patches the module-level Supabase access and the registry,
    then returns a TestClient for the real application.

    The lifespan is not entered, so nothing is started.
    """

    fake = FakeSupabase()

    def install(rows=None, supabase=None, reg=None):
        instance = supabase or FakeSupabase(rows)
        monkeypatch.setattr(
            campus_api, "get_supabase", lambda: instance
        )
        monkeypatch.setattr(
            campus_api,
            "get_registry",
            lambda: (reg if reg is not None else registry),
        )
        return instance

    install()

    return TestClient(app)


def make_client(monkeypatch, rows=None, supabase=None,
                registry=None) -> TestClient:
    fake = supabase or FakeSupabase(rows)

    monkeypatch.setattr(
        campus_api, "get_supabase", lambda: fake
    )
    monkeypatch.setattr(
        campus_api,
        "get_registry",
        lambda: registry
        if registry is not None
        else FakeRegistry(
            [
                FakeEntry(code, sensor_id)
                for code, sensor_id in sensor_ids().items()
            ]
        ),
    )

    return TestClient(app), fake


# --- Success -----------------------------------------------------


def test_returns_latest_reading_for_each_sensor(
    monkeypatch, registry
):
    rows = [
        reading("CO2-LH01", 820.0, T0, "id-1"),
        reading("TEMP-LH01", 24.5, T0, "id-2"),
        reading("HUM-LH01", 55.0, T0, "id-3"),
        reading("OCC-LH01", 42.0, T0, "id-4"),
        reading("ENERGY-LH01", 2.4, T0, "id-5"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    response = client.get(URL)

    assert response.status_code == 200

    body = response.json()

    assert body["campus_code"] == "CIT-MAIN"
    assert body["campus_id"] == CAMPUS_ID
    assert body["sensors_considered"] == 5
    assert body["reading_count"] == 5
    assert len(body["readings"]) == 5
    assert body["sensors_without_readings"] == []

    codes = {
        item["sensor_code"] for item in body["readings"]
    }

    assert codes == set(sensor_ids())


def test_reading_carries_sensor_and_location_identity(
    monkeypatch, registry
):
    rows = [reading("TEMP-LH01", 24.5, T0, "id-1")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    item = client.get(URL).json()["readings"][0]

    assert item["sensor_id"] == sensor_ids()["TEMP-LH01"]
    assert item["sensor_code"] == "TEMP-LH01"
    assert item["sensor_type"] == "temperature"
    assert item["metric"] == "temperature"
    assert item["unit"] == "°C"
    assert item["value"] == 24.5
    assert item["campus_id"] == CAMPUS_ID
    assert item["building_id"] == BUILDING_ID
    assert item["floor_id"] == FLOOR_ID
    assert item["zone_id"] == ZONE_ID
    assert item["campus_code"] == "CIT-MAIN"
    assert item["building_code"] == "ACADEMIC-BLK-A"
    assert item["floor_code"] == "A-F1"
    assert item["zone_code"] == "LH01"
    assert item["source"] == "simulator"
    assert item["quality"] == "good"
    assert item["metadata"] == {"simulated": True}


def test_timestamp_serialises_as_iso8601(monkeypatch, registry):
    when = datetime(2026, 3, 3, 14, 30, 15, tzinfo=UTC)

    client, _fake = make_client(
        monkeypatch,
        [reading("TEMP-LH01", 21.0, when, "id-1")],
        registry=registry,
    )

    body = client.get(URL).json()

    stamp = body["readings"][0]["timestamp"]

    assert stamp.startswith("2026-03-03T14:30:15")

    parsed = datetime.fromisoformat(stamp)

    assert parsed == when
    assert parsed.tzinfo is not None


def test_generated_at_is_timezone_aware(monkeypatch, registry):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    generated = client.get(URL).json()["generated_at"]

    parsed = datetime.fromisoformat(generated)

    assert parsed.tzinfo is not None


def test_results_are_sorted_by_metric_then_sensor(
    monkeypatch, registry
):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        reading("CO2-LH01", 820.0, T0, "id-2"),
        reading("HUM-LH01", 55.0, T0, "id-3"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(URL)

    metrics = [item["metric"] for item in body.json()["readings"]]

    assert metrics == sorted(metrics)


def test_ordering_is_stable_across_repeated_calls(
    monkeypatch, registry
):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        reading("CO2-LH01", 820.0, T0, "id-2"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    first = client.get(URL).json()["readings"]
    second = client.get(URL).json()["readings"]

    assert first == second


# --- Latest-per-sensor ------------------------------------------


def test_only_the_latest_reading_per_sensor_is_returned(
    monkeypatch, registry
):
    rows = [
        reading("TEMP-LH01", 30.0, T0, "id-old"),
        reading(
            "TEMP-LH01",
            22.5,
            T0 + timedelta(seconds=5),
            "id-new",
        ),
        reading("CO2-LH01", 900.0, T0, "id-co2"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(URL).json()

    temperatures = [
        item
        for item in body["readings"]
        if item["metric"] == "temperature"
    ]

    assert len(temperatures) == 1
    assert temperatures[0]["value"] == 22.5
    assert body["reading_count"] == 2


def test_identical_timestamps_are_broken_deterministically(
    monkeypatch, registry
):
    """
    Two rows for one sensor share a timestamp, so the larger
    id wins every time.
    """

    rows = [
        reading("TEMP-LH01", 19.0, T0, "id-aaa"),
        reading("TEMP-LH01", 29.0, T0, "id-zzz"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    first = client.get(URL).json()["readings"]
    second = client.get(URL).json()["readings"]

    assert len(first) == 1
    assert first[0]["value"] == 29.0
    assert first == second


def test_rows_outside_the_scan_window_are_reported_as_missing(
    monkeypatch, registry
):
    client, fake = make_client(
        monkeypatch,
        [reading("TEMP-LH01", 24.5, T0, "id-1")],
        registry=registry,
    )

    body = client.get(URL).json()

    assert body["reading_count"] == 1
    assert body["sensors_without_readings"] == [
        "CO2-LH01",
        "ENERGY-LH01",
        "HUM-LH01",
        "OCC-LH01",
    ]

    scans = [
        call
        for call in fake.calls
        if isinstance(call, dict)
        and call["table"] == "telemetry_readings"
        and call["verb"] == "execute"
    ]

    # The scan is bounded and ordered newest first.
    assert len(scans) == 1
    assert scans[0]["limit"] == 500
    assert scans[0]["order"] == [
        ("timestamp", True),
        ("id", True),
    ]


# --- Missing data -----------------------------------------------


def test_sensor_without_readings_is_not_invented(
    monkeypatch, registry
):
    rows = [reading("TEMP-LH01", 24.5, T0, "id-1")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(URL).json()

    reported = {item["sensor_code"] for item in body["readings"]}

    assert reported == {"TEMP-LH01"}
    assert body["sensors_considered"] == 5
    assert len(body["sensors_without_readings"]) == 4


def test_empty_result_uses_the_empty_response_shape(
    monkeypatch, registry
):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    response = client.get(URL)

    assert response.status_code == 200

    body = response.json()

    assert body["readings"] == []
    assert body["reading_count"] == 0
    assert body["sensors_considered"] == 5
    assert body["sensors_without_readings"] == sorted(
        sensor_ids()
    )
    assert body["zone_code"] is None


def test_reading_for_an_unknown_sensor_is_ignored(
    monkeypatch, registry
):
    stray = reading("TEMP-LH01", 24.5, T0, "id-1")
    stray["sensor_id"] = "ffffffff-0000-4000-8000-00000000ffff"

    rows = [stray, reading("TEMP-LH01", 23.0, T0, "id-2")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(URL).json()

    assert body["reading_count"] == 1
    assert body["readings"][0]["value"] == 23.0


# --- Campus and zone boundaries ----------------------------------


def test_unknown_campus_returns_404(monkeypatch, registry):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    response = client.get(
        "/api/v1/campus/NOPE/telemetry/latest"
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_readings_from_another_campus_are_excluded(
    monkeypatch, registry
):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        {
            **reading("CO2-LH01", 800.0, T0, "id-2"),
            "campus_id": OTHER_CAMPUS_ID,
        },
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(URL).json()

    codes = {item["sensor_code"] for item in body["readings"]}

    # The stray row was filtered out by sensor_id, so the CO2
    # sensor is simply reported as having no readings.
    assert codes == {"TEMP-LH01"}
    assert "CO2-LH01" in body["sensors_without_readings"]


def test_zone_filter_narrows_the_response(monkeypatch, registry):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        reading("CO2-LH01", 800.0, T0, "id-2"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(f"{URL}?zone=LH01").json()

    assert body["zone_code"] == "LH01"
    assert body["sensors_considered"] == 5
    assert body["reading_count"] == 2


def test_unknown_zone_is_rejected(monkeypatch, registry):
    rows = [reading("TEMP-LH01", 24.5, T0, "id-1")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    response = client.get(f"{URL}?zone=ZZ99")

    assert response.status_code == 400
    assert "ZZ99" in response.json()["detail"]


def test_zone_filter_excludes_rows_from_another_zone(
    monkeypatch
):
    """
    A registry whose sensors sit in different zones: only the
    requested zone's sensors are considered, and a row that
    carries a foreign zone id never appears.
    """

    temp_id = sensor_ids()["TEMP-LH01"]
    co2_id = sensor_ids()["CO2-LH01"]

    mixed = FakeRegistry(
        [
            FakeEntry("TEMP-LH01", temp_id, ZONE_ID),
            FakeEntry(
                "CO2-LH01",
                co2_id,
                OTHER_ZONE_ID,
                zone_code="ZZ99",
            ),
        ]
    )

    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        {
            **reading("CO2-LH01", 800.0, T0, "id-2"),
            "zone_id": OTHER_ZONE_ID,
        },
    ]

    client, _fake = make_client(
        monkeypatch, rows, registry=mixed
    )

    body = client.get(f"{URL}?zone=LH01").json()

    codes = {item["sensor_code"] for item in body["readings"]}

    assert codes == {"TEMP-LH01"}
    assert body["sensors_considered"] == 1


# --- Parameter validation ----------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "?limit=0",
        "?limit=-1",
        "?limit=201",
        "?limit=abc",
        "?limit=",
    ],
)
def test_invalid_limit_is_rejected(monkeypatch, registry, query):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    response = client.get(f"{URL}{query}")

    assert response.status_code == 422


def test_limit_truncates_the_response(monkeypatch, registry):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        reading("CO2-LH01", 800.0, T0, "id-2"),
        reading("HUM-LH01", 55.0, T0, "id-3"),
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(f"{URL}?limit=2").json()

    assert body["reading_count"] == 2
    assert len(body["readings"]) == 2

    # Whatever was dropped is reported as missing.
    assert len(body["sensors_without_readings"]) == 3


def test_limit_of_one_is_allowed(monkeypatch, registry):
    rows = [reading("TEMP-LH01", 24.5, T0, "id-1")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    response = client.get(f"{URL}?limit=1")

    assert response.status_code == 200
    assert response.json()["reading_count"] == 1


def test_result_cap_never_exceeds_the_registered_sensors(
    monkeypatch, registry
):
    rows = [
        reading(code, 1.0, T0, f"id-{code}")
        for code in sensor_ids()
    ]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    body = client.get(f"{URL}?limit=200").json()

    assert body["reading_count"] <= 5
    assert body["reading_count"] == body["sensors_considered"]


# --- Failure modes ----------------------------------------------


def test_query_failure_returns_a_safe_error(monkeypatch, registry):
    supabase = FakeSupabase(
        error=RuntimeError(
            "connection to https://secret-host.supabase.co failed"
        )
    )

    client, _fake = make_client(
        monkeypatch, supabase=supabase, registry=registry
    )

    response = client.get(URL)

    assert response.status_code == 503

    detail = response.json()["detail"]

    assert "secret-host" not in detail
    assert "supabase" not in detail.lower()
    assert "key" not in detail.lower()


def test_execute_failure_returns_500_without_internals(
    monkeypatch, registry
):
    class FailingTable(FakeTable):
        def execute(self):
            if self._name == "telemetry_readings":
                raise RuntimeError(
                    "postgrest 500 at /rest/v1/"
                    "telemetry_readings with apikey "
                    "sk-live-abc123"
                )

            return super().execute()

    supabase = FakeSupabase()

    def table(name):
        supabase.calls.append(name)

        return FailingTable(name, supabase.tables, supabase.calls)

    supabase.table = table

    client, _fake = make_client(
        monkeypatch, supabase=supabase, registry=registry
    )

    response = client.get(URL)

    assert response.status_code == 500

    detail = response.json()["detail"]

    assert "sk-live" not in detail
    assert "apikey" not in detail
    assert "postgrest" not in detail.lower()


def test_missing_registry_returns_503(monkeypatch, registry):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    def boom():
        raise RuntimeError("no database configuration")

    import app.api.campus as module

    original = module.get_registry
    module.get_registry = boom

    try:
        response = client.get(URL)
    finally:
        module.get_registry = original

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"].lower()


def test_missing_client_configuration_returns_503(
    monkeypatch, registry
):
    client, _fake = make_client(monkeypatch, [], registry=registry)

    def boom():
        raise RuntimeError("SUPABASE_URL missing")

    monkeypatch.setattr(campus_api, "get_supabase", boom)

    response = client.get(URL)

    assert response.status_code == 503
    assert "SUPABASE_URL" not in response.json()["detail"]


# --- Read-only guarantees ---------------------------------------


def test_endpoint_performs_no_write_operation(
    monkeypatch, registry
):
    rows = [
        reading("TEMP-LH01", 24.5, T0, "id-1"),
        reading("CO2-LH01", 800.0, T0, "id-2"),
    ]

    client, fake = make_client(
        monkeypatch, rows, registry=registry
    )

    client.get(URL)

    verbs = {
        call["verb"]
        for call in fake.calls
        if isinstance(call, dict)
    }

    # Only read verbs were issued; insert/update/delete/upsert
    # raise inside the fake if they are ever reached.
    assert verbs == {"select", "execute"}

    assert "telemetry_readings" in fake.calls


def test_only_two_tables_are_touched(monkeypatch, registry):
    client, fake = make_client(
        monkeypatch,
        [reading("TEMP-LH01", 24.5, T0, "id-1")],
        registry=registry,
    )

    client.get(URL)

    # One campuses lookup and one telemetry scan. No per-sensor
    # query loop.
    assert fake.calls.count("telemetry_readings") == 1
    assert fake.calls.count("campuses") == 1


def test_endpoint_does_not_require_mqtt(monkeypatch, registry):
    """
    A plain read: MQTT state is irrelevant, so this works with
    the default MQTT_ENABLED=false.
    """

    from app.core.config import settings

    assert settings.mqtt_enabled is False

    rows = [reading("TEMP-LH01", 24.5, T0, "id-1")]

    client, _fake = make_client(monkeypatch, rows, registry=registry)

    assert client.get(URL).status_code == 200


# --- Existing routes remain compatible ---------------------------


def test_existing_routes_still_work(monkeypatch, registry):
    client, fake = make_client(monkeypatch, [], registry=registry)

    root = client.get("/")
    health = client.get("/health")

    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"

    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_campus_twin_route_still_works(monkeypatch, registry):
    supabase = FakeSupabase()

    stamp = T0.isoformat()

    supabase.tables["campuses"] = [
        {
            "id": CAMPUS_ID,
            "code": "CIT-MAIN",
            "name": "Cambridge Institute of Technology",
            "description": None,
            "timezone": "Asia/Kolkata",
            "metadata": {},
            "created_at": stamp,
            "updated_at": stamp,
        }
    ]

    supabase.tables.update(
        {
            "buildings": [
                {
                    "id": BUILDING_ID,
                    "campus_id": CAMPUS_ID,
                    "code": "ACADEMIC-BLK-A",
                    "name": "Academic Block A",
                    "description": None,
                    "latitude": None,
                    "longitude": None,
                    "metadata": {},
                    "created_at": T0.isoformat(),
                    "updated_at": T0.isoformat(),
                }
            ],
            "floors": [
                {
                    "id": FLOOR_ID,
                    "building_id": BUILDING_ID,
                    "code": "A-F1",
                    "name": "Ground Floor",
                    "floor_number": 1,
                    "metadata": {},
                    "created_at": T0.isoformat(),
                    "updated_at": T0.isoformat(),
                }
            ],
            "zones": [
                {
                    "id": ZONE_ID,
                    "floor_id": FLOOR_ID,
                    "code": "LH01",
                    "name": "Lecture Hall",
                    "zone_type": "lecture_hall",
                    "capacity": 60,
                    "area_sq_meters": 120.0,
                    "schedule_start_hour": 8,
                    "schedule_end_hour": 18,
                    "active_days": [1, 2, 3, 4, 5, 6],
                    "twin_model_object": None,
                    "metadata": {},
                    "created_at": T0.isoformat(),
                    "updated_at": T0.isoformat(),
                }
            ],
            "equipment": [],
            "sensors": [],
            "incidents": [],
        }
    )

    client, _fake = make_client(
        monkeypatch, supabase=supabase, registry=registry
    )

    response = client.get("/api/v1/campus/CIT-MAIN/twin")

    assert response.status_code == 200

    body = response.json()

    assert body["campus"]["code"] == "CIT-MAIN"
    assert body["zones"][0]["code"] == "LH01"


def test_route_list_is_unchanged_apart_from_the_new_route():
    routes = sorted(route.path for route in app.routes)

    assert "/api/v1/campus/{campus_code}/telemetry/latest" in routes

    for existing in (
        "/",
        "/health",
        "/api/v1/campus/{campus_code}/twin",
    ):
        assert existing in routes