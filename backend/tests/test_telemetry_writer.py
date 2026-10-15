"""
Batch writer tests.

Fully offline: the insert function is injected, so no Supabase
credentials, no network and no MQTT are involved.
"""

import asyncio
import threading
from datetime import datetime, timezone

import pytest

from app.telemetry.models import TelemetryMessage
from app.telemetry.writer import (
    TABLE,
    FlushResult,
    TelemetryWriter,
    TelemetryWriterClosed,
    TelemetryWriterError,
)


SENSOR_ID = "d1acf785-0000-4000-8000-00000000000a"
ZONE_ID = "26f134ea-0000-4000-8000-000000000004"

TICK_AT = datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc)


class RecordingInsert:
    """
    Records every batch it is handed. `fail_times` makes the
    first N calls raise, so retry and recovery are testable.
    """

    def __init__(self, fail_times: int = 0) -> None:
        self.batches = []
        self.rows = []
        self.fail_times = fail_times
        self.calls = 0
        self.thread_ids = []

    def __call__(self, rows) -> None:
        self.calls += 1
        self.thread_ids.append(threading.get_ident())

        if self.calls <= self.fail_times:
            raise RuntimeError("postgrest unavailable")

        self.batches.append([dict(row) for row in rows])
        self.rows.extend(dict(row) for row in rows)

    @property
    def metrics(self):
        return [row["metric"] for row in self.rows]


def message(
    metric="temperature",
    unit="°C",
    value=24.5,
    timestamp=TICK_AT,
    source="simulator",
    quality="good",
    **extra,
) -> TelemetryMessage:
    return TelemetryMessage(
        sensor_id=SENSOR_ID,
        metric=metric,
        value=value,
        unit=unit,
        timestamp=timestamp,
        source=source,
        quality=quality,
        zone_id=ZONE_ID,
        **extra,
    )


def writer(insert=None, **kwargs) -> TelemetryWriter:
    return TelemetryWriter(
        insert_fn=insert or RecordingInsert(),
        # Never actually sleep in tests.
        sleep_fn=lambda _seconds: None,
        **kwargs,
    )


# --- Enqueue and flush ------------------------------------------


def test_single_reading_round_trip():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())

    assert w.buffer_size == 1

    result = w.flush()

    assert result.inserted_rows == 1
    assert result.chunks == 1
    assert result.buffer_size == 0
    assert len(insert.rows) == 1


def test_multiple_readings_keep_enqueue_order():
    insert = RecordingInsert()

    w = writer(insert)

    for index in range(5):
        w.enqueue(message(value=20.0 + index))

    w.flush()

    assert [row["value"] for row in insert.rows] == [
        20.0, 21.0, 22.0, 23.0, 24.0
    ]


def test_flush_is_a_noop_on_empty_buffer():
    insert = RecordingInsert()

    w = writer(insert)

    result = w.flush()

    assert result == FlushResult(
        inserted_rows=0, chunks=0, buffer_size=0
    )
    assert insert.calls == 0


def test_repeated_flush_after_drain_is_safe():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())
    w.flush()

    for _ in range(3):
        assert w.flush().inserted_rows == 0

    assert len(insert.rows) == 1


def test_flush_clears_the_buffer():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())
    w.flush()

    assert w.buffer_size == 0


# --- Chunking ---------------------------------------------------


def test_rows_are_chunked_below_the_postgrest_ceiling():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=200, max_buffer_rows=500)

    for index in range(450):
        w.enqueue(message(value=float(index)))

    w.flush()

    # 450 rows at 200 per chunk: 200 + 200 + 50.
    assert [len(batch) for batch in insert.batches] == [
        200, 200, 50
    ]
    assert all(len(batch) <= 200 for batch in insert.batches)
    assert all(
        len(batch) < 1000 for batch in insert.batches
    )


def test_custom_chunk_size_is_respected():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=3, max_buffer_rows=10)

    for index in range(5):
        w.enqueue(message(value=float(index)))

    w.flush()

    # 5 rows at 3 per chunk: 3 + 2.
    assert [len(batch) for batch in insert.batches] == [
        3, 2
    ]
    assert w.flush().chunks == 0


def test_flush_result_reports_chunk_count():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=2, max_buffer_rows=10)

    for index in range(5):
        w.enqueue(message(value=float(index)))

    assert w.flush().chunks == 3


# --- Bounded buffer ---------------------------------------------


def test_buffer_is_bounded_and_forces_a_flush():
    insert = RecordingInsert()

    w = writer(
        insert, chunk_size=2, max_buffer_rows=4
    )

    for index in range(4):
        w.enqueue(message(value=float(index)))

    # Reaching the bound flushed without an explicit call:
    # four rows went out as two chunks of two.
    assert [len(batch) for batch in insert.batches] == [
        2, 2
    ]
    assert len(insert.rows) == 4
    assert w.buffer_size == 0
    assert w.stats.forced_flushes == 1
    assert w.stats.flushes == 1


def test_buffer_never_exceeds_its_bound():
    insert = RecordingInsert()

    w = writer(
        insert, chunk_size=10, max_buffer_rows=20
    )

    for index in range(200):
        w.enqueue(message(value=float(index)))
        assert w.buffer_size <= 20

    assert w.buffer_size <= 20


def test_invalid_bounds_are_rejected():
    with pytest.raises(ValueError):
        TelemetryWriter(
            insert_fn=RecordingInsert(), chunk_size=0
        )

    with pytest.raises(ValueError):
        TelemetryWriter(
            insert_fn=RecordingInsert(),
            chunk_size=500,
            max_buffer_rows=100,
        )


def test_only_validated_messages_are_accepted():
    w = writer()

    with pytest.raises(TypeError):
        w.enqueue({"metric": "temperature", "value": 1.0})


# --- Row payloads -----------------------------------------------


def test_rows_match_to_row_output():
    insert = RecordingInsert()

    w = writer(insert)
    original = message(
        metadata={"simulated": True},
        equipment_id="c19ffcca-0000-4000-8000-000000000005",
    )

    w.enqueue(original)
    w.flush()

    assert insert.rows[0] == original.to_row()


def test_source_quality_timestamp_and_metadata_survive():
    insert = RecordingInsert()

    w = writer(insert)

    w.enqueue(
        message(
            source="simulator",
            quality="suspect",
            metadata={"simulated": True, "note": "demo"},
        )
    )
    w.flush()

    row = insert.rows[0]

    assert row["source"] == "simulator"
    assert row["quality"] == "suspect"
    # The row carries an ISO-8601 string, not a datetime,
    # because PostgREST serialises the body as JSON.
    assert isinstance(row["timestamp"], str)
    assert datetime.fromisoformat(row["timestamp"]) == TICK_AT
    assert row["metadata"] == {
        "simulated": True, "note": "demo"
    }
    # Simulated data is never relabelled as sensor data.
    assert row["source"] != "sensor"


def test_row_targets_the_existing_table():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())
    w.flush()

    row = insert.rows[0]

    assert TABLE == "telemetry_readings"
    assert set(row) == {
        "metric",
        "value",
        "unit",
        "timestamp",
        "source",
        "quality",
        "metadata",
        "sensor_id",
        "campus_id",
        "building_id",
        "floor_id",
        "zone_id",
        "equipment_id",
    }
    # The database default supplies the primary key.
    assert "id" not in row


def test_energy_reading_keeps_kw_unit():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message(metric="energy", unit="kW", value=2.46))
    w.flush()

    assert insert.rows[0]["unit"] == "kW"
    assert insert.rows[0]["value"] == 2.46


# --- Failure, retry, recovery -----------------------------------


def test_transient_failure_is_retried_and_recovers():
    insert = RecordingInsert(fail_times=1)

    w = writer(insert, max_retries=2)

    w.enqueue(message())
    result = w.flush()

    assert result.inserted_rows == 1
    assert insert.calls == 2
    assert w.stats.retries == 1
    assert w.stats.inserted_rows == 1


def test_retries_are_bounded_then_it_raises():
    insert = RecordingInsert(fail_times=99)

    w = writer(insert, max_retries=2)

    w.enqueue(message())

    with pytest.raises(TelemetryWriterError):
        w.flush()

    # Initial attempt plus two retries, then it gives up.
    assert insert.calls == 3
    assert w.stats.retries == 2


def test_failed_rows_are_kept_in_the_buffer():
    insert = RecordingInsert(fail_times=99)

    w = writer(insert, max_retries=0)

    w.enqueue(message(value=31.0))

    with pytest.raises(TelemetryWriterError):
        w.flush()

    assert w.buffer_size == 1
    assert w.stats.failed_rows == 1


def test_retained_rows_survive_and_can_be_flushed_later():
    insert = RecordingInsert(fail_times=1)

    w = writer(insert, max_retries=0)

    w.enqueue(message(value=41.0))

    with pytest.raises(TelemetryWriterError):
        w.flush()

    assert w.buffer_size == 1

    # The broker came back; the rows are still there.
    result = w.flush()

    assert result.inserted_rows == 1
    assert insert.rows[0]["value"] == 41.0
    assert w.buffer_size == 0


def test_failed_chunk_is_not_partially_counted():
    insert = RecordingInsert(fail_times=99)

    w = writer(
        insert, chunk_size=2, max_buffer_rows=10,
        max_retries=0,
    )

    for index in range(4):
        w.enqueue(message(value=float(index)))

    with pytest.raises(TelemetryWriterError):
        w.flush()

    # Nothing is reported as inserted when a chunk fails.
    assert w.stats.inserted_rows == 0
    assert w.buffer_size == 4


def test_backoff_grows_and_is_capped():
    delays = []

    w = TelemetryWriter(
        insert_fn=RecordingInsert(fail_times=99),
        max_retries=4,
        backoff_seconds=0.1,
        max_backoff_seconds=0.5,
        sleep_fn=delays.append,
    )

    w.enqueue(message())

    with pytest.raises(TelemetryWriterError):
        w.flush()

    assert delays == [0.1, 0.2, 0.4, 0.5]
    assert len(delays) == 4


def test_overflow_flush_failure_propagates_from_enqueue():
    insert = RecordingInsert(fail_times=99)

    w = writer(
        insert, chunk_size=1, max_buffer_rows=1,
        max_retries=0,
    )

    with pytest.raises(TelemetryWriterError):
        w.enqueue(message())

    # Nothing was discarded silently.
    assert w.buffer_size == 1
    assert insert.rows == []


# --- Concurrency ------------------------------------------------


def test_overlapping_flushes_do_not_duplicate_rows():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=2, max_buffer_rows=500)

    for index in range(50):
        w.enqueue(message(value=float(index)))

    barrier = threading.Barrier(4)

    def flush_many():
        barrier.wait()
        w.flush()

    threads = [
        threading.Thread(target=flush_many)
        for _ in range(4)
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    values = sorted(row["value"] for row in insert.rows)

    assert len(insert.rows) == 50
    assert values == [float(index) for index in range(50)]
    assert w.buffer_size == 0


def test_concurrent_enqueue_and_flush_lose_nothing():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=5, max_buffer_rows=1000)

    def produce(start, count):
        for index in range(start, start + count):
            w.enqueue(message(value=float(index)))

    def flush_loop():
        for _ in range(20):
            w.flush()

    producers = [
        threading.Thread(target=produce, args=(0, 40)),
        threading.Thread(target=produce, args=(40, 40)),
        threading.Thread(target=flush_loop),
    ]

    for thread in producers:
        thread.start()

    for thread in producers:
        thread.join()

    w.flush()

    assert len(insert.rows) == 80
    assert w.buffer_size == 0


# --- Close ------------------------------------------------------


def test_close_drains_the_buffer():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())

    result = w.close()

    assert result.inserted_rows == 1
    assert w.is_closed
    assert len(insert.rows) == 1


def test_close_can_discard_without_draining():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())

    result = w.close(drain=False)

    assert result.inserted_rows == 0
    assert insert.calls == 0
    assert w.is_closed


def test_repeated_close_is_safe():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())

    first = w.close()
    second = w.close()
    third = w.close()

    assert first.inserted_rows == 1
    assert second.inserted_rows == 0
    assert third.inserted_rows == 0

    # The rows were written exactly once.
    assert len(insert.rows) == 1


def test_enqueue_after_close_is_rejected():
    w = writer()
    w.close()

    with pytest.raises(TelemetryWriterClosed):
        w.enqueue(message())


def test_flush_after_close_is_harmless():
    insert = RecordingInsert()

    w = writer(insert)
    w.close()

    assert w.flush().inserted_rows == 0


# --- Off-event-loop behaviour -----------------------------------


def test_sync_insert_runs_in_the_calling_thread():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=1, max_buffer_rows=10)
    w.enqueue(message())
    w.enqueue(message(value=25.0))

    w.flush()

    assert insert.thread_ids == [
        threading.get_ident(), threading.get_ident()
    ]


def test_async_flush_runs_off_the_event_loop():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=1, max_buffer_rows=10)

    for index in range(3):
        w.enqueue(message(value=float(index)))

    loop_thread = None

    async def scenario():
        nonlocal loop_thread
        loop_thread = threading.get_ident()

        return await w.flush_async()

    result = asyncio.run(scenario())

    assert result.inserted_rows == 3

    # The blocking insert never ran on the loop thread.
    assert loop_thread not in insert.thread_ids
    assert all(
        thread_id != loop_thread
        for thread_id in insert.thread_ids
    )


def test_async_enqueue_does_not_block_the_loop():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=2, max_buffer_rows=100)

    async def scenario():
        for index in range(5):
            await w.enqueue_async(
                message(value=float(index))
            )

        await w.flush_async()

    asyncio.run(scenario())

    assert len(insert.rows) == 5


def test_async_close_drains():
    insert = RecordingInsert()

    w = writer(insert)
    w.enqueue(message())

    async def scenario():
        return await w.close_async()

    result = asyncio.run(scenario())

    assert result.inserted_rows == 1
    assert w.is_closed


# --- Periodic flush ---------------------------------------------


def test_flush_interval_comes_from_settings():
    w = writer()

    assert w.flush_interval_seconds == 10.0


def test_flush_interval_can_be_overridden():
    w = writer(flush_interval_seconds=2.5)

    assert w.flush_interval_seconds == 2.5


def test_run_flusher_flushes_on_the_interval():
    insert = RecordingInsert()

    w = writer(
        insert,
        chunk_size=2,
        max_buffer_rows=100,
        flush_interval_seconds=0.01,
    )

    for index in range(4):
        w.enqueue(message(value=float(index)))

    asyncio.run(w.run_flusher(max_flushes=2))

    # The first pass wrote the 4 rows. The second found an
    # empty buffer and is a no-op, so it is not counted as a
    # real flush.
    assert len(insert.rows) == 4
    assert w.stats.flushes == 1
    assert w.buffer_size == 0


def test_run_flusher_stops_on_stop_event():
    insert = RecordingInsert()

    w = writer(
        insert,
        chunk_size=2,
        max_buffer_rows=100,
        flush_interval_seconds=0.01,
    )

    w.enqueue(message())

    async def scenario():
        stop = asyncio.Event()

        task = asyncio.create_task(
            w.run_flusher(stop=stop)
        )

        await asyncio.sleep(0.05)
        stop.set()

        await task

    asyncio.run(scenario())

    assert w.buffer_size == 0


def test_run_flusher_is_cancellable():
    insert = RecordingInsert()

    w = writer(
        insert,
        chunk_size=2,
        max_buffer_rows=100,
        flush_interval_seconds=5,
    )

    async def scenario():
        task = asyncio.create_task(w.run_flusher())

        await asyncio.sleep(0.02)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert insert.calls == 0


# --- Statistics -------------------------------------------------


def test_counters_track_the_writer():
    insert = RecordingInsert()

    w = writer(insert, chunk_size=2, max_buffer_rows=10)

    for index in range(4):
        w.enqueue(message(value=float(index)))

    w.flush()

    assert w.stats.enqueued_rows == 4
    assert w.stats.inserted_rows == 4
    assert w.stats.flushes == 1
    assert w.stats.chunks == 2
    assert w.stats.retries == 0
    assert w.stats.failed_rows == 0


def test_counters_track_retry_and_failure():
    insert = RecordingInsert(fail_times=99)

    w = writer(insert, max_retries=1)

    w.enqueue(message())

    with pytest.raises(TelemetryWriterError):
        w.flush()

    assert w.stats.retries == 1
    assert w.stats.failed_rows == 1
    assert w.stats.inserted_rows == 0