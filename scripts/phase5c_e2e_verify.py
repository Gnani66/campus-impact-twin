#!/usr/bin/env python3
"""
Controlled end-to-end verification of the telemetry pipeline.

One tick only: simulator -> Mosquitto -> worker -> writer ->
Supabase telemetry_readings. Maximum five inserted rows.

Every reading carries `metadata.test_run_id`, so the rows can
be found exactly afterwards and left in place.

Safety:

* nothing is published until the worker reports it is
  subscribed;
* the run id is checked for zero existing rows before any
  message is sent;
* at most one simulator tick (five messages) is published;
* the periodic flusher is never started, so the single drain
  happens in `worker.stop(drain_writer=True)`;
* no secret is printed;
* this script is never imported by `app.main`.

Run from the `backend` directory with MQTT enabled for this
process only:

    MQTT_ENABLED=true .venv/bin/python ../scripts/phase5c_e2e_verify.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.chdir(BACKEND_DIR)  # settings reads .env relative to here

from app.core.config import settings  # noqa: E402
from app.db.supabase import get_supabase  # noqa: E402
from app.telemetry.models import TelemetryMessage  # noqa: E402
from app.telemetry.mqtt_worker import (  # noqa: E402
    MqttTelemetryWorker,
)
from app.telemetry.registry import get_registry  # noqa: E402
from app.telemetry.simulator import (  # noqa: E402
    TelemetrySimulator,
)
from app.telemetry.writer import TelemetryWriter  # noqa: E402


EXPECTED_MESSAGES = 5
EXPECTED_METRICS = {
    "co2",
    "energy",
    "humidity",
    "occupancy",
    "temperature",
}

CONNECT_TIMEOUT = 15.0
CONSUME_TIMEOUT = 20.0
SHUTDOWN_TIMEOUT = 20.0


def log(message: str) -> None:
    print(message, flush=True)


def rows_for_run(supabase, run_id: str):
    """Read-only lookup by the exact run id."""

    return (
        supabase.table("telemetry_readings")
        .select(
            "id, sensor_id, metric, value, unit, timestamp, "
            "source, quality, campus_id, building_id, "
            "floor_id, zone_id, metadata"
        )
        .contains("metadata", {"test_run_id": run_id})
        .order("timestamp")
        .execute()
        .data
        or []
    )


async def wait_for_subscription(
    worker: MqttTelemetryWorker, timeout: float
) -> bool:
    """Polls until the worker reports an established connection."""

    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        if worker.stats.connections_established >= 1:
            return True

        await asyncio.sleep(0.1)

    return False


async def main() -> int:
    run_id = (
        "phase5c-e2e-"
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    )

    log("=" * 62)
    log("Phase 5C Part 2 - controlled end-to-end verification")
    log("=" * 62)
    log(f"  test_run_id       : {run_id}")
    log(f"  mqtt_enabled      : {settings.mqtt_enabled}")
    log(f"  broker            : {settings.mqtt_host}:{settings.mqtt_port}")
    log(f"  topic prefix      : {settings.mqtt_topic_prefix}")

    if not settings.mqtt_enabled:
        log("  ABORT: MQTT_ENABLED is false. Rerun with")
        log("         MQTT_ENABLED=true for this process only.")
        return 2

    supabase = get_supabase()

    # --- pre-write guard ---------------------------------------
    existing = rows_for_run(supabase, run_id)
    log(f"  pre-check rows for this run id : {len(existing)}")

    if existing:
        log("  ABORT: this run id already has rows.")
        return 2

    before = (
        supabase.table("telemetry_readings")
        .select("id", count="exact")
        .limit(1)
        .execute()
    ).count
    log(f"  telemetry_readings before      : {before}")
    log("-" * 62)

    # --- components --------------------------------------------
    registry = await asyncio.to_thread(get_registry)
    log(f"  registry sensors               : {len(registry)}")

    if len(registry) != EXPECTED_MESSAGES:
        log(f"  ABORT: expected {EXPECTED_MESSAGES} sensors.")
        return 2

    # No insert_fn: the real Supabase insert path is used.
    writer = TelemetryWriter(app_settings=settings)

    worker = MqttTelemetryWorker(
        writer=writer,
        registry=registry,
        app_settings=settings,
    )

    simulator = TelemetrySimulator(
        registry=registry,
        app_settings=settings,
    )

    # One real simulator tick, tagged with the run id.
    tick = simulator.build_tick()

    if len(tick) != EXPECTED_MESSAGES:
        log(f"  ABORT: tick produced {len(tick)} readings.")
        return 2

    payloads = []

    for reading in tick:
        body = json.loads(reading.payload)
        body["metadata"] = {
            **body.get("metadata", {}),
            "test_run_id": run_id,
        }
        # Re-validate through the real model before publishing.
        TelemetryMessage.model_validate(body)
        payloads.append(
            (reading.topic, json.dumps(body, separators=(",", ":")))
        )

    log(f"  prepared messages              : {len(payloads)}")
    log("-" * 62)

    # --- run ----------------------------------------------------
    task = asyncio.create_task(
        worker.run(max_messages=EXPECTED_MESSAGES)
    )

    published = 0
    outcome = "unknown"

    try:
        if not await wait_for_subscription(worker, CONNECT_TIMEOUT):
            log("  TIMEOUT: worker never subscribed.")
            outcome = "timeout"
        else:
            log("  worker connected and subscribed")
            log(f"  topic filter: {await worker.build_topic_filter()}")

            # Publish exactly one tick, five messages.
            client = simulator._build_client()

            async with client:
                for topic, payload in payloads:
                    await client.publish(
                        topic, payload.encode("utf-8"), qos=0
                    )
                    published += 1

                    log(f"    published {published}/{len(payloads)}")

            log(f"  messages published             : {published}")

            await asyncio.wait_for(task, timeout=CONSUME_TIMEOUT)

            log(
                "  worker stats: "
                f"received={worker.stats.messages_received} "
                f"accepted={worker.stats.messages_accepted} "
                f"rejected={worker.stats.messages_rejected} "
                f"writer_errors={worker.stats.writer_errors}"
            )

            outcome = "consumed"

    except asyncio.TimeoutError:
        log("  TIMEOUT while consuming messages.")
        outcome = "timeout"
    except Exception as exc:
        log(f"  ERROR: {type(exc).__name__}: {exc}")
        outcome = "error"
    finally:
        # Safe shutdown: cancels the worker task and performs
        # the single writer drain.
        try:
            await asyncio.wait_for(
                worker.stop(drain_writer=True),
                timeout=SHUTDOWN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log("  TIMEOUT during shutdown drain.")

    log(f"  writer stats: enqueued={writer.stats.enqueued_rows} "
        f"inserted={writer.stats.inserted_rows} "
        f"failed={writer.stats.failed_rows} "
        f"retries={writer.stats.retries}")
    log(f"  writer buffer remaining       : {writer.buffer_size}")
    log(f"  phase outcome                 : {outcome}")
    log("-" * 62)

    # --- verification (read-only) -------------------------------
    rows = rows_for_run(supabase, run_id)

    after = (
        supabase.table("telemetry_readings")
        .select("id", count="exact")
        .limit(1)
        .execute()
    ).count

    log(f"  rows for this run id          : {len(rows)}")
    log(f"  telemetry_readings total      : {before} -> {after}")

    checks = []

    checks.append(("exactly five rows", len(rows) == EXPECTED_MESSAGES))
    checks.append(("no extra rows", after - before == EXPECTED_MESSAGES))

    metrics = {row["metric"] for row in rows}
    checks.append(("all five metrics", metrics == EXPECTED_METRICS))

    for row in sorted(rows, key=lambda item: item["metric"]):
        stamp = row["timestamp"]
        aware = stamp.endswith("+00:00") or stamp.endswith("Z")

        checks.append(
            (
                f"{row['metric']}: sensor/zone/campus ids present",
                bool(row["sensor_id"])
                and bool(row["zone_id"])
                and bool(row["campus_id"])
                and bool(row["building_id"])
                and bool(row["floor_id"]),
            )
        )
        checks.append(
            (
                f"{row['metric']}: unit '{row['unit']}' valid",
                bool(row["unit"]),
            )
        )
        checks.append(
            (f"{row['metric']}: tz-aware timestamp", aware)
        )
        checks.append(
            (
                f"{row['metric']}: source/quality",
                row["source"] == "simulator"
                and row["quality"] == "good",
            )
        )
        checks.append(
            (
                f"{row['metric']}: run id in metadata",
                (row.get("metadata") or {}).get("test_run_id")
                == run_id,
            )
        )

        log(
            f"    {row['metric']:<11} {row['value']:>10.4f} "
            f"{row['unit']:<7} {stamp} "
            f"sensor={str(row['sensor_id'])[:8]}... "
            f"zone={str(row['zone_id'])[:8]}..."
        )

    log("-" * 62)

    for name, passed in checks:
        log(f"  [{'PASS' if passed else 'FAIL'}] {name}")

    passed_all = all(result for _, result in checks)

    log("=" * 62)
    log(f"  published={published} "
        f"accepted={worker.stats.messages_accepted} "
        f"inserted={writer.stats.inserted_rows} "
        f"verified={len(rows)}")
    log(f"  RESULT: {'PASS' if passed_all else 'FAIL'}")
    log("=" * 62)

    return 0 if passed_all else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))