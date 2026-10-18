# Campus Impact Twin

A campus operations platform that puts a 3D digital twin in front of
real sensor telemetry, turns that telemetry into incidents through
deterministic rules, and routes every proposed action through a
named human before it is recorded.

The premise: a campus already has buildings, rooms, sensors and
alerts. What it usually lacks is a way to answer *"what is actually
happening in that room, and what would we do about it?"* without a
spreadsheet and a walk around the building.

| | |
| --- | --- |
| **Live frontend** | https://campus-impact-twin.vercel.app |
| **Live API** | https://campus-impact-twin-api.onrender.com |
| **API reference** | https://campus-impact-twin-api.onrender.com/docs |
| **Stack** | Next.js 16 · React 19 · TypeScript · Tailwind 4 · React Three Fiber · FastAPI · Supabase (Postgres) · Ollama · YOLO11n · Mosquitto MQTT |

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Design decisions worth reading](#design-decisions-worth-reading)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Testing](#testing)
- [Deployment](#deployment)
- [What is real and what is simulated](#what-is-real-and-what-is-simulated)
- [Repository layout](#repository-layout)

---

## What it does

### 1. Digital twin

A 3D scene of the campus with a live marker for every sensor and
piece of equipment. Marker positions are derived from the model's
real bounding box at runtime, so they stay correct if the asset
changes rather than being hardcoded coordinates.

Two views, both polling the same backend snapshot:

- `/digital-twin` — embedded in the operations workspace, marker
  click selects an entity
- `/twin` — full-screen scene with the telemetry overlay

### 2. Telemetry pipeline

Storage-first ingestion. A simulator publishes MQTT messages, a
FastAPI worker consumes them, and readings are batch-written to
`telemetry_readings`. The frontend polls; nothing streams.

```
simulator ──▶ Mosquitto ──▶ FastAPI worker ──▶ TelemetryWriter ──▶ telemetry_readings
                                                                        │
                                            GET /api/v1/campus/{code}/telemetry/latest
                                                                        │
                                                          Next.js polls every 20s
```

The digital twin snapshot polls every 5s.

### 3. Intelligence engine

Telemetry becomes incidents through **deterministic rules** — pure
functions, no model, no API key, no network. The same inputs always
produce the same verdict, which is what makes an incident defensible:
a reviewer can recompute the decision by hand from the evidence.

Five rules: `temperature`, `humidity`, `co2`, `energy`, `occupancy`.

### 4. Correlation engine

Multi-source evidence gate. Vision observation, telemetry and the
zone schedule must *agree* before something is reported — a single
source claiming a full lecture hall at 03:00 is not enough.

### 5. AI copilot

Ask a question in plain language about the campus state. The copilot
computes the answer from the same deterministic analysis the rest of
the platform uses, then lets a local model (Ollama, `qwen2.5:3b`) write
the prose. When the model is unreachable, the copilot still answers,
composed from the same facts, and says so.

### 6. Intervention simulation

What-if analysis that compares candidate interventions against the
current state and reports the modelled outcome. Simulation only — see
[what is real](#what-is-real-and-what-is-simulated).

### 7. Human approval

Nothing is recorded as acted-on without a named reviewer. A request
moves through `approve → prepare → execute`, each step a separate
auditable event recording who did it and why. Execution is always
simulated: this project cannot reach a physical campus system.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Next.js 16  ·  React 19  ·  React Three Fiber               │
│                                                              │
│  /  /dashboard  /digital-twin  /twin  /incidents             │
│  /approvals  /copilot                                         │
└───────────────────────────┬──────────────────────────────────┘
                            │  NEXT_PUBLIC_API_URL
                            │  (client → FastAPI only,
                            │   never straight to the database)
┌───────────────────────────▼──────────────────────────────────┐
│  FastAPI                                                       │
│                                                              │
│  campus · telemetry · intelligence · correlation · impact    │
│  interventions · simulation · approvals · digital twin       │
│  copilot · vision                                             │
└───────────────────────────┬──────────────────────────────────┘
                            │  service role key
┌───────────────────────────▼──────────────────────────────────┐
│  Supabase (Postgres)                                          │
│  campuses · buildings · floors · zones · equipment           │
│  sensors · telemetry_readings · incidents · approvals · …    │
└──────────────────────────────────────────────────────────────┘

Side channels:  Mosquitto (MQTT ingest) · Ollama (local LLM) · YOLO11n (vision)
```

**The frontend never talks to the database.** It calls the API, which
reads Supabase with the service role key. Status is a value the
backend decided — which is what stops the view and the operational
record from disagreeing, and what lets the status rules be tested as
pure functions instead of by clicking a building.

### Seeded entity graph

The demo dataset is one real hierarchy, not scattered fixtures:

```
CIT-MAIN              Cambridge Institute of Technology
└── ACADEMIC-BLK-A    Academic Block A
    └── A-F1          Ground Floor
        └── LH01      University Lecture Hall   (capacity 60)
            ├── HVAC-LH01     equipment · hvac
            ├── OCC-LH01      occupancy   · people
            ├── TEMP-LH01     temperature · °C
            ├── HUM-LH01      humidity    · %
            ├── CO2-LH01      co2         · ppm
            └── ENERGY-LH01   energy      · kW
```

---

## Design decisions worth reading

These are the choices that shaped the codebase. Each one exists to
solve a specific failure mode, not as a matter of taste.

**Intelligence is deterministic, not generative.** An incident can be
recomputed by hand from the evidence shown beside it. A language model
deciding whether a room is too hot would be unfalsifiable, and the
whole point of an operations tool is that you can check its work.

**The language model writes prose only.** It never decides a severity
or states a number the backend did not compute. Its claims are printed
underneath the model's answer, so a hallucinated temperature is visible
as a hallucinated temperature rather than silently believed. When the
model is unavailable the copilot says so rather than appearing to have
worked.

**The energy baseline is a low percentile, not the mean.** Using the
mean would let a sustained fault drag its own baseline upward until
the rule silently stopped firing — the fault would erase the evidence
of itself.

**Incidents are deduplicated, not appended.** Telemetry arrives every
few seconds; a condition persisting an hour would otherwise produce
hundreds of identical incidents. One incident per zone+rule, refreshed,
keeping the worst impact score and a bounded observation history. In a
demonstration run, 20 rule firings produced 4 incidents.

**A blank environment variable is treated as unset.** The API address
and the model path both fall back on an empty string rather than
accepting it. This is not theoretical: `NEXT_PUBLIC_API_URL` was
declared on Vercel with no value, `??` accepted `""` as a valid
address, and every request went out as a relative path — so the
browser reported a 404 *from the frontend* for endpoints that exist on
the backend. A wrong host, silently. Both resolvers now take the raw
value as an argument and treat empty and whitespace as missing, with
tests for each case.

**The twin degrades instead of dying.** `useGLTF` throws when a model
cannot be fetched, and in React that is an error rather than a loading
state — it escapes Suspense and takes the Canvas with it, leaving a
black rectangle for what is an asset rather than the thing being
demonstrated. An error boundary catches the failure and renders a
wireframe footprint at the extent the marker layout already falls back
to, so the operational picture survives a missing model.

**Prefer a build that works to a build that refuses.** An earlier
version of the API address threw during a production build when the
variable was unset. It was solving a real problem, but the *default*
was the actual fix, and the throw only turned a missing value into a
red deploy.

---

## Quick start

### Prerequisites

- **Python 3.11+** — the telemetry engine uses
  `datetime.fromisoformat()` with the `Z` suffix (3.11+) and relies on
  implicit event-loop creation in `asyncio.Event()`
- **Node.js 20.9+** — required by Next.js 16
- A Supabase project

### 1. Database

Migrations live in `backend/migrations/` and **must be applied in
order** — each depends on the ones before it. They are run by hand in
the Supabase SQL editor; this repository has no migration runner.

| File | Purpose |
| --- | --- |
| `001_smart_campus.sql` | Creates the schema |
| `002_seed_smart_campus.sql` | Seeds CIT-MAIN and the LH01 entity graph |
| `003_vision_observations.sql` | Creates `vision_observations` with its indexes, enables RLS |

### 2. Backend

```bash
cd backend

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY

uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend

npm install

cp .env.example .env.local
# NEXT_PUBLIC_API_URL=http://127.0.0.1:8000

npm run dev
```

http://localhost:3000

> Use `127.0.0.1` rather than `localhost`: uvicorn binds `127.0.0.1`
> by default, and where `localhost` resolves to `::1` first, a healthy
> backend gets refused.

### 4. Optional — generate telemetry

Nothing is ingesting until MQTT is enabled, so the dashboard will be
empty on a fresh database.

```bash
# Terminal 1 — broker
docker compose up -d

# Terminal 2 — ingest
cd backend
MQTT_ENABLED=true .venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 3 — publish
cd backend
.venv/bin/python simulator.py --occupancy 48
```

`--occupancy` forces a headcount instead of following the zone
schedule. The seeded LH01 schedule is 08:00–18:00 local, so outside
those hours every tick is unoccupied and every signal flattens to base
load — a dataset with no variance and nothing to detect.

Useful simulator flags:

| Flag | Effect |
| --- | --- |
| `--ticks N` | Stop after N ticks. Default: run until Ctrl+C. |
| `--interval S` | Seconds between ticks |
| `--occupancy N` | Force a headcount |
| `--fault MODE` | `hvac-stuck-on`, `no-ventilation`, `overcool`, `door-left-open` |
| `--fault-after-ticks N` | When the fault starts. Default 24. |
| `--fault-ticks N` | How long it lasts. Default 60. |
| `--scenario demo` | Scripted demonstration window |

Faults are applied to the *controls* fed into the physics, not to the
produced readings, so each fault propagates through the same equations
as normal operation. An anomaly detector cannot tell a fault from
reality by checking physical plausibility — that is the point.

| Mode | Signature | Detectable in |
| --- | --- | --- |
| `hvac-stuck-on` | Energy steps ~0.35 → ~1.7 kW at zero occupancy while temperature falls | One tick |
| `no-ventilation` | CO2 diverges upward from the healthy trajectory (+100 ppm at 20 min, +300 ppm at 40 min) | Tens of minutes |
| `overcool` | Energy at maximum draw, temperature falling regardless of ambient | Minutes |
| `door-left-open` | Temperature drifts toward outdoor at high occupancy, energy at base load | Minutes |

`no-ventilation` is a drift rather than a step, because CO2 removal is
slow. It needs trend detection, not a threshold.

### Seeing a detection

```bash
cd backend
MQTT_ENABLED=true .venv/bin/python simulator.py --scenario demo
```

`--scenario demo` runs 20 ticks of healthy data, then a scripted
window of 58 people / 30.5 °C / 72% / 1850 ppm / 8.5 kW for 15 ticks,
then returns to normal. The values are applied to the readings *after*
the physics runs, not to the model inputs — so it is a scripted
demonstration, not simulated reality. It is opt-in and never the
default, and every affected reading is tagged
`metadata.demo_scenario = true` so scripted and simulated data are
never confused later.

Normal operation produces **zero incidents**, and that is the correct
behaviour. An intelligence engine that reports `CRITICAL` every five
seconds is not useful.

---

## Configuration

### Backend (`backend/.env`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `SUPABASE_URL` | — | **Required** |
| `SUPABASE_SERVICE_ROLE_KEY` | — | **Required** |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated browser origins |
| `MQTT_ENABLED` | `false` | Enables the telemetry ingest worker |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | Broker address |
| `MQTT_TOPIC_PREFIX` | `smart-campus` | Topic prefix |
| `TELEMETRY_TICK_SECONDS` | `5` | Simulator cadence |
| `TELEMETRY_FLUSH_SECONDS` | `10` | Batched write interval |
| `INTELLIGENCE_ENABLED` | `true` | Runs the rules after each flush |
| `DEFAULT_CAMPUS_CODE` | `CIT-MAIN` | Campus used when none is named |
| `VISION_ENABLED` | `true` | Loads the YOLO detector |
| `VISION_CONFIDENCE_THRESHOLD` | `0.45` | Detection floor |
| `VISION_IOU_THRESHOLD` | `0.50` | Non-max suppression |
| `VISION_MAX_UPLOAD_BYTES` | `10485760` | Uploads rejected above this |
| `VISION_MODEL_PATH` | *(empty)* | Weights path; refuses to download when empty |

Optional, for the copilot: `OLLAMA_URL` (default
`http://127.0.0.1:11434`) and `OLLAMA_MODEL` (default `qwen2.5:3b`).

> `CORS_ALLOWED_ORIGINS` is the one setting that silently breaks a
> deployment. An origin that is not listed produces a response with no
> `Access-Control-Allow-Origin` header, which the browser reports as a
> CORS failure — that reads as "the API is down" when the API answered
> `200`.

### Frontend (`frontend/.env.local`)

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | deployed API URL | Backend base address |
| `NEXT_PUBLIC_MODEL_URL` | `/models/lecture-hall.glb` | Where the GLB is loaded from |

`NEXT_PUBLIC_*` values are inlined at build time, so restart
`npm run dev` after changing them.

---

## API reference

Interactive docs at `/docs`. 32 endpoints:

| Method | Path | |
| --- | --- | --- |
| GET | `/` | Service metadata |
| GET | `/health` | Liveness |
| GET | `/api/v1/campus/{campus_code}/twin` | Full entity graph |
| GET | `/api/v1/campus/{campus_code}/telemetry/latest` | Latest stored readings |
| GET | `/api/v1/digital-twin/snapshot` | Scene snapshot |
| GET | `/api/v1/digital-twin/entities/{entity_id}` | One entity |
| GET | `/api/v1/incidents` | Filterable list |
| GET | `/api/v1/incidents/summary` | Counts and severity mix |
| GET | `/api/v1/approvals` | All requests |
| GET | `/api/v1/approvals/pending` | Awaiting a decision |
| GET | `/api/v1/approvals/{id}` | One request |
| GET | `/api/v1/approvals/{id}/events` | Audit trail |
| POST | `/api/v1/approvals/{id}/review` | Approve or reject |
| POST | `/api/v1/approvals/{id}/prepare` | Move to ready |
| POST | `/api/v1/approvals/{id}/execute` | Record simulated execution |
| POST | `/api/v1/copilot/ask` | Ask a question |
| GET | `/api/v1/copilot/health` | Whether the local model is reachable |
| GET | `/api/v1/correlation/zone/{zone_code}` | Evidence gate for a zone |
| POST | `/api/v1/correlation/analyze` | Evidence gate, run |
| GET | `/api/v1/interventions` | Available interventions |
| GET | `/api/v1/interventions/{code}` | One intervention |
| POST | `/api/v1/impact/analyze` | Impact assessment |
| POST | `/api/v1/simulation/run` | Start a what-if run |
| GET | `/api/v1/simulation/{run_id}` | Run status |
| GET | `/api/v1/simulation/{run_id}/comparison` | Candidate comparison |
| POST | `/api/v1/vision/analyze` | Analyse an uploaded still |
| GET | `/api/v1/vision/status` | Detector state |
| GET | `/api/v1/vision/zone/{zone_code}/latest` | Latest observation |

`GET /api/v1/incidents` accepts `campus_code`, `status`, `severity`,
`category`, `zone` and `limit`. Filtering is applied by the backend,
not in the browser — fetching a page and narrowing it client-side
would silently under-report once the result reached the limit.

---

## Testing

```bash
cd backend  && .venv/bin/python -m pytest tests -q    # 923 passed
cd frontend && npm test                                # 65 passed
```

**988 tests, all passing.** The suite leans on pure functions: rule
evaluation, baseline selection, marker layout and address resolution
are all testable without a database or a browser.

---

## Deployment

| | |
| --- | --- |
| Backend | Render — `render.yaml`, Docker |
| Frontend | Vercel — `frontend/vercel.json` |

The backend is a Docker service defined in `render.yaml`; secrets are
supplied at deploy time. `VISION_ENABLED=false` there, so the
deployment serves the rest of the API without loading a detector.

> `CORS_ALLOWED_ORIGINS` in `render.yaml` only takes effect on a
> **Blueprint redeploy** — setting it in the file does not change a
> running service.

---

## What is real and what is simulated

Worth stating plainly, because a demo that blurs this is worth less
than one that doesn't.

| | |
| --- | --- |
| **Telemetry** | Simulated. Every reading comes from `simulator.py` and is labelled `source="simulator"` in the UI. No physical sensor is instrumented. |
| **Stored, not live** | The endpoint returns the newest *stored* reading. Polling every 20s proves the API is reachable, not that anything is ingesting. |
| **Streaming** | None. WebSocket delivery was deferred; the frontend polls. |
| **Execution** | Always simulated. Nothing here can reach a physical campus system. Approvals write a record of what *would* have happened. |
| **Vision** | Uploaded still images, not a live camera feed. |
| **The LLM** | Local, and optional. With Ollama stopped the copilot still answers, composed from the same facts, and reports that the model was unavailable. |
| **The 3D model** | A 260 MB GLB, gitignored and hosted externally — see [the GLB](#the-3d-model) below. |
| **Incidents** | Real rule output. The rules are deterministic and would detect the injected faults; what is simulated is the *input*, not the detection. |

### The 3D model

`lecture-hall.glb` is a 260 MB asset. It is gitignored — it exceeds
what a repository should carry — so a build from source has no model
and the twin renders a wireframe placeholder.

Serve it from object storage and point `NEXT_PUBLIC_MODEL_URL` at it.
The bucket must be public (signed URLs expire, which breaks a cached
asset) and must serve CORS headers.

Note that Supabase Storage caps files at **50 MB on the Free plan** —
a hard limit that cannot be raised in settings — so a 260 MB file needs
Pro or above. Even then, 260 MB before first paint is a poor first
impression; decimation is the highest-impact performance improvement
available to this project.

---

## Repository layout

```
backend/
  app/
    api/          Routers: campus, incidents, correlation, impact,
                  interventions, simulation, approvals, digital twin,
                  copilot, vision
    ai/           Local model seam, prompts, copilot schemas
    core/         Config and the rule sets
    services/     Business logic per capability
    telemetry/    MQTT ingest and batched writer
    repositories/ Data access
  migrations/     Ordered SQL, applied by hand
  tests/          923 tests
  simulator.py    Fault-injecting telemetry generator

frontend/
  app/            App Router pages
  components/
    digital-twin/ Embedded twin scene
    twin/         Shared twin components (error boundary, placeholder)
  lib/
    api.ts        Single typed API boundary
    twin/         Twin configuration and marker layout
  tests/          65 tests

docs/             Architecture notes and diagrams
scripts/          End-to-end verification
```

`frontend/lib/api.ts` is the only place the frontend builds a backend
URL. Eleven call sites, one error-handling policy: a network failure
names the configured address, an abort is passed through untouched, and
a response the backend refused names the status.
