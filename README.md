# Smart Campus Digital Twin

A 3D digital twin of the campus, backed by real building,
floor, zone, equipment and sensor data.

```
Campus
  │
  └── Building
        │
        └── Floor
              │
              └── Zone / Room
                    │
          ┌─────────┼─────────┐
          │         │         │
       Sensors   Equipment  Assets
          │         │
          └────┬────┘
               │
               ▼
          Telemetry
               │
               ▼
           Analytics
               │
               ▼
           Incidents
               │
               ▼
        Recommendations
```

## Architecture

- `frontend/` — Next.js, React, TypeScript, Tailwind CSS, React Three Fiber.
- `backend/` — FastAPI, Python, Supabase.

The frontend never talks to the database directly. It calls
the FastAPI backend, which reads Supabase with the service
role key.

## Database

Migrations live in `backend/migrations/` and run in order in
the Supabase SQL editor.

| File | Purpose |
| --- | --- |
| `001_smart_campus.sql` | Creates the schema, drops the superseded schema |
| `002_seed_smart_campus.sql` | Seeds CIT-MAIN and the LH01 entity graph |
| `LEGACY_snapshot_do_not_run.sql` | Reference only. Pre-migration data snapshot |

Tables: `campuses`, `buildings`, `floors`, `zones`,
`equipment`, `sensors`, `telemetry_readings`, `incidents`.

Seeded hierarchy:

```
CIT-MAIN   Cambridge Institute of Technology
└── ACADEMIC-BLK-A   Academic Block A
    └── A-F1   Ground Floor
        └── LH01   University Lecture Hall
            ├── HVAC-LH01
            ├── OCC-LH01
            ├── TEMP-LH01
            ├── HUM-LH01
            ├── CO2-LH01
            └── ENERGY-LH01
```

## Local development

### Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY

uvicorn app.main:app --reload --port 8000
```

> **Python 3.11 or newer is required.** The Phase 5 telemetry
> engine and its test suite use `datetime.fromisoformat()` with
> the `Z` suffix (3.11+) and rely on implicit event-loop
> creation in `asyncio.Event()`. On Python 3.9 those fail at
> runtime. The schemas still use `typing.Optional` /
> `typing.List` rather than `X | None` for wider
> compatibility, but 3.9 is no longer a supported target.

Endpoints:

| Method | Path |
| --- | --- |
| GET | `/` |
| GET | `/health` |
| GET | `/api/v1/campus/{campus_code}/twin` |
| GET | `/docs` |

```bash
curl http://localhost:8000/
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/campus/CIT-MAIN/twin
```

### Frontend

```bash
cd frontend

npm install

cp .env.example .env.local
# NEXT_PUBLIC_API_URL=http://localhost:8000

npm run dev
```

- http://localhost:3000 — overview
- http://localhost:3000/twin — 3D digital twin with live markers
- http://localhost:3000/dashboard — campus command centre

## The twin identity

`lecture-hall.glb` resolves to a real zone through the
database, not through hardcoded coordinates:

```
lecture-hall.glb
      │
      ▼
LH01  University Lecture Hall   (zone_type: lecture_hall, capacity 60)
      │
      ├── HVAC-LH01            (equipment, 12.5 kW rated)
      ├── OCC-LH01             (occupancy, every 5s)
      ├── TEMP-LH01            (temperature, every 5s)
      ├── HUM-LH01             (humidity, every 5s)
      ├── CO2-LH01             (co2, every 5s)
      └── ENERGY-LH01          (energy, every 5s)
```

Marker positions are derived from the model's real bounding
box at runtime, so they stay correct if the asset changes.

## Notes

`public/models/lecture-hall.glb` is a 260 MB asset and takes
roughly 10-20 seconds to load on first paint. A loading
overlay shows progress while the Suspense boundary resolves.
Compressing or decimating the asset is the highest-impact
performance improvement available.

## Telemetry

The telemetry pipeline is storage-first. Readings are written
to `telemetry_readings` and read back through the API; nothing
streams to the browser.

```
simulator ──▶ Mosquitto (docker compose up -d)
               └──▶ FastAPI worker ──▶ TelemetryWriter ──▶ telemetry_readings
                                                              │
                              GET /api/v1/campus/{code}/telemetry/latest
                                                              │
                                                   Next.js polls every 20s
```

| Step | Status |
| --- | --- |
| Simulator with coupled physics | Done. Produces demo values, not measurements |
| MQTT broker, worker, batched writer | Done. All gated behind `MQTT_ENABLED`, default `false` |
| Read-only latest endpoint | Done. One latest reading per sensor |
| Dashboard and 3D twin display | Done. Polls every 20 seconds |

Read carefully:

* **Stored, not live.** The endpoint returns the newest
  *stored* reading. With MQTT disabled the newest reading is
  only as fresh as the last write, which the UI shows as an
  age next to the reading timestamp. Polling every 20 seconds
  proves the API is reachable, not that anything is ingesting.
* **Simulated by default.** Every reading produced so far came
  from the simulator and is labelled `source="simulator"` in
  the UI. No physical sensor instrumentation is connected.
* **No streaming.** WebSocket delivery was deferred; the
  frontend polls instead.

To produce new readings, enable MQTT for one process:

```bash
cd backend
MQTT_ENABLED=true .venv/bin/python ../scripts/phase5c_e2e_verify.py
```

### Generating history

`scripts/phase5c_e2e_verify.py` publishes exactly one tick and
exits. To build a history worth analysing, run the simulator
standalone:

```bash
docker compose up -d                 # broker

# Terminal 1 — ingest
cd backend
MQTT_ENABLED=true .venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2 — publish
cd backend
.venv/bin/python simulator.py
```

| Flag | Effect |
| --- | --- |
| `--ticks N` | Stop after N ticks. Default: run until Ctrl+C. |
| `--interval S` | Seconds between ticks. Default: `TELEMETRY_TICK_SECONDS`. |
| `--occupancy N` | Force a headcount instead of following the zone schedule. |
| `--every N` | Print every Nth tick. |
| `--verbose` | One line per sensor per tick. |
| `--fault MODE` | `hvac-stuck-on`, `no-ventilation`, `overcool`, `door-left-open`. |
| `--fault-after-ticks N` | Tick at which the fault starts. Default 24. |
| `--fault-ticks N` | How long the fault lasts. Default 60. |

**Use `--occupancy` when generating history outside opening
hours.** The seeded LH01 schedule is 08:00-18:00 local, so
after 18:00 every tick is unoccupied and every signal flattens
to base load. That dataset has no variance and nothing for
Phase 6 to detect.

```bash
.venv/bin/python simulator.py --occupancy 48
```

### Fault injection

Faults are applied to the *controls* fed into the physics, not
to the produced readings, so each fault propagates through the
same equations as normal operation. An anomaly detector cannot
tell a fault from reality by checking physical plausibility.

| Mode | Signature | Detectable in |
| --- | --- | --- |
| `hvac-stuck-on` | Energy steps ~0.35 → ~1.7 kW at zero occupancy while temperature falls | One tick |
| `no-ventilation` | CO2 diverges upward from the healthy trajectory (~+100 ppm at 20 min, ~+300 ppm at 40 min) | Tens of minutes |
| `overcool` | Energy at maximum draw, temperature falling regardless of ambient | Minutes |
| `door-left-open` | Temperature drifts toward outdoor at high occupancy, energy at base load | Minutes |

`no-ventilation` is a drift rather than a step, because CO2
removal is a slow process. It needs trend detection, not a
threshold.

```bash
.venv/bin/python simulator.py --occupancy 55 \
    --fault hvac-stuck-on --fault-after-ticks 24 --fault-ticks 60
```

Give the fault window enough ticks to be visible in the data.
Thirty seconds of throttled ventilation is not an anomaly; it
is noise.

## Intelligence

Telemetry becomes incidents. Rules are **deterministic**: pure
functions, no model, no API key, no network. The same inputs
always produce the same verdict, which is what makes an incident
defensible — a reviewer can recompute the decision by hand from
the evidence.

```
telemetry_readings
        │
        ▼
  context resolution      zone → floor → building → campus
        │                 plus latest occupancy, plus the
        │                 zone's normal energy draw
        ▼
  rule evaluation         temperature · humidity · co2
        │                 energy · occupancy
        ▼
  impact + confidence     scored from how far past threshold
        ▼
  deduplication           one incident per zone+rule, refreshed
        ▼
  incidents
```

| Layer | Module |
| --- | --- |
| Rules | `app/core/intelligence_rules.py` |
| Schemas | `app/schemas/intelligence.py` |
| Service | `app/services/intelligence_service.py` |
| API | `app/api/incidents.py` |

Endpoints (read-only; incidents are never written through the API):

| Method | Path |
| --- | --- |
| GET | `/api/v1/incidents` |
| GET | `/api/v1/incidents/summary` |

`GET /api/v1/incidents` accepts `campus_code`, `status`,
`severity`, `category` and `limit`.

### Why deduplication matters

Telemetry arrives every few seconds. A condition that persists for
an hour would otherwise produce hundreds of identical incidents.
An incident is created once and then refreshed, keeping the worst
impact score seen and a bounded history of observations. In a
demonstration run, 20 rule firings produced 4 incidents.

### Two design decisions worth knowing

**The energy baseline is a low percentile, not the mean.** Using
the mean would let a sustained fault drag its own baseline upward
until the rule silently stopped firing — the fault would erase
the evidence of itself.

**Zone context has no `campus_id`.** The hierarchy is
`zones → floors → buildings → campuses`, so an incident is only
attributed once all three hops resolve.

### Demonstrating a detection

```bash
cd backend
MQTT_ENABLED=true .venv/bin/python simulator.py --scenario demo
```

`--scenario demo` runs 20 ticks of healthy data, then a scripted
window of 58 people / 30.5 °C / 72% / 1850 ppm / 8.5 kW for 15
ticks, then returns to normal. The values are applied to the
readings after the physics runs, not to the model inputs, so they
are a **scripted demonstration** rather than simulated reality.
It is opt-in and never the default. Every affected reading is
tagged `metadata.demo_scenario = true` so scripted and simulated
data are never confused later.

Normal operation produces **zero incidents**, and that is the
correct behaviour. An intelligence engine that reports `CRITICAL`
every five seconds is not useful.

## Phase 6 status

Phase 6 is complete. The intelligence engine is implemented and
wired into the telemetry flush cycle:

| Rule | Signal |
| --- | --- |
| `temperature` | comfort band breach |
| `humidity` | low / high bounds |
| `co2` | ventilation adequacy |
| `energy` | load multiplier against baseline |
| `occupancy` | headcount over zone capacity |

Endpoints: `GET /api/v1/incidents`, `GET /api/v1/incidents/summary`.
Toggle with `INTELLIGENCE_ENABLED` (default on) and target a campus
with `DEFAULT_CAMPUS_CODE`.

Not yet built, and deliberately so: forecasting and
recommendations. Those need a real history of sensor data
accumulated over time rather than a scripted run.

## Next phase

Phase 7 — forecasting and recommendations on top of the stored
incident and telemetry history. It depends on the pipeline having
produced a meaningful history of real sensor data, so it cannot be
validated against a short scripted run.
