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

> The virtualenv here is Python 3.9, so the schemas use
> `typing.Optional` / `typing.List` rather than `X | None`.

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

## Next phase

Phase 6 — intelligence on top of stored telemetry: anomaly
detection, forecasting and recommendations. None of it exists
yet, and none of it can be validated until the pipeline
produces a meaningful history of real sensor data.
