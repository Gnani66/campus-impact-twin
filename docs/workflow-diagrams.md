# Campus Impact Twin — Technical Workflow Diagrams

## 1. System Architecture Overview

```mermaid
graph TB
    subgraph External["External Systems"]
        MQTT[("Mosquitto<br/>MQTT Broker")]
        CAM[Camera Feeds]
    end

    subgraph Frontend["Frontend — Next.js / React / React Three Fiber"]
        LAND[Landing Page<br/>/]
        DASH[Dashboard<br/>/dashboard]
        TWIN[Digital Twin<br/>/digital-twin]
        INC[Incidents<br/>/incidents]
        COP[AI Copilot<br/>/copilot]
        APPR[Approvals<br/>/approvals]
    end

    subgraph Backend["Backend — FastAPI / Python"]
        API[API Layer<br/>app/api/]
        SVC[Service Layer<br/>app/services/]
        CORE[Core Rules<br/>app/core/]
        TELE[Telemetry Engine<br/>app/telemetry/]
        AI[AI Copilot<br/>app/ai/]
        VISION[Vision Engine<br/>vision/]
    end

    subgraph Data["Data Layer"]
        SUPA[(Supabase<br/>PostgreSQL)]
        OLLAMA[("Ollama<br/>Local LLM")]
    end

    CAM -->|POST /vision/analyze| API
    MQTT -->|Subscribe| TELE
    TELE -->|Write readings| SUPA
    API --> SVC
    SVC --> CORE
    SVC --> SUPA
    AI --> OLLAMA
    COP -->|POST /copilot/ask| API
    DASH -->|Poll 5s| API
    TWIN -->|Poll 5s| API
    INC -->|GET /incidents| API
    APPR -->|POST /approvals/*| API
```

---

## 2. Telemetry Ingestion Pipeline

```mermaid
flowchart LR
    subgraph Sim["Simulator"]
        PHYS[Zone Physics<br/>Deterministic Model]
        TICK[Build Tick<br/>5 sensors]
        PUB[Publish to MQTT]
        PHYS --> TICK --> PUB
    end

    subgraph Broker["MQTT Broker"]
        TOPIC[Topic: smart-campus/campus/{code}<br/>/building/{code}/floor/{code}<br/>/zone/{code}/sensor/{uuid}]
    end

    subgraph Worker["MQTT Worker"]
        VAL[Validate Message<br/>7-step validation]
        ENQ[Enqueue to Writer]
        VAL --> ENQ
    end

    subgraph Writer["TelemetryWriter"]
        BUF[Bounded Buffer<br/>max 500 rows]
        FLUSH[Periodic Flush<br/>every 10s]
        CHUNK[Chunk Insert<br/>200 rows/chunk]
        RETRY[Retry with<br/>Exponential Backoff]
        BUF --> FLUSH --> CHUNK --> RETRY
    end

    subgraph Intelligence["Intelligence Engine"]
        EVAL[Evaluate Rules<br/>5 deterministic rules]
        DEDUP[Deduplicate<br/>zone+category+rule]
        PERSIST[Persist Incident]
        EVAL --> DEDUP --> PERSIST
    end

    subgraph DB[(Supabase)]
        TELEMETRY[(telemetry_readings)]
        INCIDENTS[(incidents)]
    end

    PUB --> TOPIC --> VAL
    ENQ --> BUF
    CHUNK -->|Insert rows| TELEMETRY
    TELEMETRY -->|on_persisted callback| EVAL
    PERSIST --> INCIDENTS
```

---

## 3. Intelligence Engine — Rule Evaluation

```mermaid
flowchart TD
    START[Telemetry Batch Persisted] --> CTX[Resolve Zone Context<br/>zone → floor → building → campus]
    CTX --> OCC[Read Occupancy<br/>as of reading timestamp]
    OCC --> BASE[Read Energy Baseline<br/>20th percentile of recent readings]
    BASE --> EVAL{Metric?}

    EVAL -->|temperature| TEMP[Temperature Rule<br/>≥28°C warning, ≥32°C critical<br/>Requires occupancy > 0]
    EVAL -->|humidity| HUM[Humidity Rule<br/>30-70% band<br/>Outside band fires]
    EVAL -->|co2| CO2[CO2 Rule<br/>≥1200ppm warning, ≥1800ppm critical]
    EVAL -->|energy| ENG[Energy Rule<br/>≥1.7x baseline warning, ≥2.3x critical<br/>Min excess 0.5kW]
    EVAL -->|occupancy| OCC2[Occupancy Rule<br/>Over capacity fires]

    TEMP --> RESULT[RuleResult<br/>category, severity, impact_score,<br/>confidence_score, evidence]
    HUM --> RESULT
    CO2 --> RESULT
    ENG --> RESULT
    OCC2 --> RESULT

    RESULT --> DEDUP{Existing open incident<br/>same zone+category+rule?}
    DEDUP -->|Yes, within 5min| REFRESH[Refresh Incident<br/>Update evidence, keep worst impact<br/>Bound history to 50 observations]
    DEDUP -->|No| CREATE[Create New Incident<br/>status=open, detection_method=deterministic_rule]
```

---

## 4. Correlation Engine — Evidence Gate

```mermaid
flowchart TD
    REQ[POST /correlation/analyze<br/>zone_code, schedule_active] --> VISION[Read Latest Vision Observation<br/>occupancy, confidence, observed_at]
    VISION --> ENERGY[Read Latest Energy Telemetry<br/>energy_kw, timestamp]
    ENERGY --> BASE[Read Energy Baseline<br/>median of recent readings]
    BASE --> CAP[Read Zone Capacity]

    VISION --> C1{Vision Evidence<br/>confidence ≥ 0.55?}
    ENERGY --> C2{Energy Evidence<br/>fresh < 60s?}
    BASE --> C3{Energy Anomaly<br/>ratio ≥ 1.5?}
    CAP --> C4{Occupancy Low<br/>ratio < 0.3?}
    REQ --> C5{Schedule Active?}
    VISION --> C6{Observation Fresh<br/>age < 120s?}

    C1 --> SCORE[Calculate Evidence Score<br/>0-100]
    C2 --> SCORE
    C3 --> SCORE
    C4 --> SCORE
    C5 --> SCORE
    C6 --> SCORE

    SCORE --> VERDICT{All checks pass?}
    VERDICT -->|Yes| CONFIRMED[confirmed_candidate<br/>root_cause: energy waste / over-capacity]
    VERDICT -->|No, condition absent| NORMAL[normal<br/>No finding]
    VERDICT -->|No, evidence incomplete| REVIEW[needs_review<br/>Ask a human]

    CONFIRMED --> PERSIST[(correlation_runs)]
    NORMAL --> PERSIST
    REVIEW --> PERSIST
```

---

## 5. Simulation & Impact Pipeline

```mermaid
flowchart TD
    REQ[POST /simulation/run<br/>zone_code, scenario, interventions, constraints] --> CORR[Load Latest Correlation Run]
    CORR --> CHECK{confirmed_candidate?}
    CHECK -->|No| BLOCKED[status: blocked<br/>No evidenced condition]
    CHECK -->|Yes| CTX[Load Correlation Context<br/>energy, observation, findings]

    CTX --> LIB[Load Intervention Library<br/>Filter by codes/names]
    LIB --> EVAL[For Each Intervention]

    EVAL --> EVID{Evidence Quality<br/>Sufficient?}
    EVID -->|No| INFEASIBLE[Mark Infeasible<br/>evidence too weak]
    EVID -->|Yes| FEAS{Feasibility Check}

    FEAS -->|Budget exceeded| INFEASIBLE
    FEAS -->|Disruption too high| INFEASIBLE
    FEAS -->|Duration too long| INFEASIBLE
    FEAS -->|OK| PROJ[Project Impact]

    PROJ --> IMPACT[Impact Score<br/>energy 35%, water 20%, waste 15%,<br/>co2 15%, business priority 15%]
    IMPACT --> CONF[Confidence Score<br/>vision 25%, telemetry 25%,<br/>baseline 25%, intervention 25%]
    CONF --> COST[Cost Efficiency Score<br/>impact × (1 - normalized_cost)]
    COST --> OVERALL[Overall Score<br/>impact 35%, confidence 25%, feasibility 20%,<br/>cost 10%, disruption 10%]

    OVERALL --> RANK[Rank Options<br/>Infeasible always last<br/>Tie-break: confidence → cost →<br/>disruption → impact → code]
    RANK --> REC[Build Recommendation<br/>Best feasible option<br/>State the trade-off]
    REC --> ARCHIVE[(simulation_runs<br/>simulation_options)]
```

---

## 6. Approval State Machine

```mermaid
stateDiagram-v2
    [*] --> pending: System creates request<br/>from simulation option

    pending --> approved: Reviewer approves<br/>with reason
    pending --> rejected: Reviewer rejects<br/>with reason (required)
    pending --> expired: Lapses
    pending --> cancelled: Withdrawn

    approved --> ready_to_execute: Prepare for execution<br/>(separate signed step)
    approved --> cancelled: Withdrawn

    ready_to_execute: Cleared to run
    ready_to_execute --> executed: Simulated execution<br/>No physical system touched
    ready_to_execute --> cancelled: Withdrawn

    rejected --> [*]
    expired --> [*]
    cancelled --> [*]
    executed --> [*]

    note right of pending
        Reviewer name required
        Reason required to reject
    end note

    note right of approved
        Approval ≠ Execution
        Separate prepare step
    end note

    note right of executed
        SIMULATED ONLY
        No campus system modified
        Result recorded with mode=simulation
    end note
```

---

## 7. Digital Twin Snapshot Assembly

```mermaid
flowchart TD
    REQ[GET /digital-twin/snapshot] --> ZONES[Load All Zones<br/>with twin_model_object, metadata]
    ZONES --> TELE[Load Latest Telemetry<br/>per zone per metric]
    TELE --> INC[Load Open Incidents<br/>status: open/acknowledged/investigating]
    INC --> CORR[Load Latest Correlation Run<br/>result_status, root_cause]
    CORR --> APPR[Load Pending Approval Count<br/>via simulation_runs join]

    TELE --> METRICS[Map Metrics<br/>temperature, humidity, co2,<br/>occupancy, energy, capacity]
    METRICS --> RATIO[Calculate Occupancy Ratio<br/>occupancy / capacity]
    RATIO --> FRESH{Fresh?<br/>age < threshold}
    FRESH -->|No| OFFLINE[status: offline]
    FRESH -->|Yes| STATUS[Determine Status<br/>from thresholds]

    INC --> RECONCILE[Reconcile with Incidents<br/>incident severity can upgrade status]
    STATUS --> REASONS[Build Status Reasons<br/>human-readable explanations]
    RECONCILE --> REASONS

    REASUES --> ISSUES[Collect Active Issues<br/>incident titles + root_cause]
    REASONS --> ENTITY[TwinEntity<br/>id, code, name, status, metrics,<br/>reasons, issues, position, scale]
    ISSUES --> ENTITY

    ENTITY --> SNAPSHOT[TwinSnapshot<br/>entities[], counts{normal, warning,<br/>critical, offline}]
```

---

## 8. AI Copilot Flow

```mermaid
flowchart TD
    REQ[POST /copilot/ask<br/>message, entity_id?] --> SNAP[Load Twin Snapshot]
    SNAP --> ENTITY{entity_id provided?}
    ENTITY -->|Yes| RESOLVE[Resolve Entity<br/>via twin service]
    ENTITY -->|No| TOP[Use Top Priority Entity<br/>from snapshot ranking]

    RESOLVE --> INTENT[Classify Intent<br/>keyword matching, ordered cascade]
    TOP --> INTENT

    INTENT -->|OVERVIEW| OVIEW[Build Overview Context<br/>counts, ranked entities, top priority]
    INTENT -->|EXPLANATION| OEXP[Build Entity Context<br/>metrics, reasons, issues, root_cause]
    INTENT -->|RECOMMENDATION| OREC[Build Entity Context<br/>+ recommendation rules]
    INTENT -->|WHAT_IF| OWHAT[Defer to Simulation Engine]
    INTENT -->|ENTITY_ANALYSIS| OENT[Build Entity Context]
    INTENT -->|UNKNOWN| OUNK[Unknown intent response]

    OVIEW --> PROMPT[Assemble Prompt<br/>system + context + question]
    OEXP --> PROMPT
    OREC --> PROMPT
    OENT --> PROMPT

    PROMPT --> LLM[Call Local LLM<br/>Ollama qwen2.5:3b<br/>temp=0.2, max_tokens=600]
    LLM -->|Success| CHECK{Contradicts<br/>verified status?}
    LLM -->|Unavailable| DET[Deterministic Answer<br/>composed from stored facts]

    CHECK -->|Yes| DET
    CHECK -->|No| FOOTER[Append Verified Footer<br/>backend status + reasons]

    FOOTER --> EVIDENCE[Build Evidence Array<br/>from stored readings]
    DET --> EVIDENCE

    EVIDENCE --> RECS[Build Recommendations<br/>each requires_approval=true]
    RECS --> RESP[CopilotResponse<br/>answer, evidence, recommendations,<br/>source: llm/deterministic, caveats]
```

---

## 9. Vision Analysis Pipeline

```mermaid
flowchart TD
    REQ[POST /vision/analyze<br/>image, camera_id, zone_code, observed_at?] --> ZONE{Zone exists?}
    ZONE -->|No| 404[404 Not Found]
    ZONE -->|Yes| VALIDATE{Validate Image}

    VALIDATE -->|Too large >10MB| 413[413 Content Too Large]
    VALIDATE -->|Unsupported format| 415[415 Unsupported Media Type]
    VALIDATE -->|Corrupt/truncated| 400[400 Bad Request]
    VALIDATE -->|Valid JPEG/PNG| DETECT[Run YOLO11n Inference<br/>conf ≥ 0.45, IoU ≥ 0.50, class=person]

    DETECT -->|Model missing| 503[503 Service Unavailable]
    DETECT -->|Inference error| 500[500 Server Error]
    DETECT -->|Success| COUNT[DetectionResult<br/>people_count, confidence, detections[]]

    COUNT --> DEDUP{observed_at provided?}
    DEDUP -->|Yes, existing row| REUSE[Reuse Stored Row<br/>idempotent]
    DEDUP -->|No| INSERT[(vision_observations)]

    REUSE --> MIRROR[(observations)]
    INSERT --> MIRROR

    MIRROR --> RESP[VisionAnalysisResponse<br/>people_count, confidence, detections]
```

---

## 10. Frontend User Journeys

### 10.1 Dashboard Overview Journey

```mermaid
flowchart LR
    A[Landing Page] -->|Open dashboard| B[Dashboard]
    B --> C[Campus Metrics<br/>buildings, zones, sensors,<br/>open alerts, critical]
    B --> D[3D Twin Panel<br/>React Three Fiber<br/>status markers]
    B --> E[Attention Panel<br/>incidents ranked by impact]

    D -->|Click marker| F[Entity Detail Sheet<br/>metrics, reasons, issues]
    F -->|Ask copilot| G[AI Copilot<br/>scoped to entity]
    F -->|View incidents| H[Incidents Page<br/>filtered by zone]
```

### 10.2 Incident Resolution Journey

```mermaid
flowchart LR
    A[Incidents Page] --> B[Filter by status/severity/zone]
    B --> C[View Incident Card<br/>title, description, evidence count]
    C --> D[Expand Evidence<br/>observation table]
    D --> E[Ask Copilot<br/>why this status?]
    E --> F[Copilot Response<br/>evidence + recommendations]
```

### 10.3 Approval Workflow Journey

```mermaid
flowchart LR
    A[Approvals Page] --> B[Enter Reviewer Name]
    B --> C[View Pending Queue]
    C --> D{Decision}
    D -->|Approve| E[status: approved]
    D -->|Reject| F[status: rejected<br/>reason required]
    E --> G[Prepare for Execution]
    G --> H[Run Simulated Execution]
    H --> I[status: executed<br/>No physical change]
```

### 10.4 Digital Twin Exploration

```mermaid
flowchart LR
    A[Digital Twin Page] --> B[3D Scene<br/>lecture-hall.glb]
    B --> C[Entity List<br/>all zones with status]
    B --> D[Status Legend<br/>normal/warning/critical/offline]
    C -->|Select entity| E[Entity Panel<br/>metrics, reasons, issues]
    E -->|Ask copilot| F[AI Copilot scoped]
    E -->|View incidents| G[Incidents filtered by zone]
```

---

## 11. Data Model Relationships

```mermaid
erDiagram
    CAMPUS ||--o{ BUILDING : has
    BUILDING ||--o{ FLOOR : has
    FLOOR ||--o{ ZONE : has
    ZONE ||--o{ SENSOR : has
    ZONE ||--o{ EQUIPMENT : has
    SENSOR ||--o{ TELEMETRY_READING : produces
    ZONE ||--o{ INCIDENT : attributed_to
    SENSOR ||--o{ INCIDENT : detected_by
    ZONE ||--o{ VISION_OBSERVATION : observed_in
    ZONE ||--o{ CORRELATION_RUN : analyzed_as
    CORRELATION_RUN ||--o{ SIMULATION_RUN : justifies
    SIMULATION_RUN ||--o{ SIMULATION_OPTION : contains
    SIMULATION_OPTION ||--o{ INTERVENTION : references
    SIMULATION_RUN ||--o{ APPROVAL_REQUEST : raises
    APPROVAL_REQUEST ||--o{ APPROVAL_EVENT : records

    CAMPUS {
        uuid id PK
        string code UK
        string name
        string timezone
    }
    BUILDING {
        uuid id PK
        uuid campus_id FK
        string code
        string name
    }
    FLOOR {
        uuid id PK
        uuid building_id FK
        string code
        int floor_number
    }
    ZONE {
        uuid id PK
        uuid floor_id FK
        string code
        string name
        string zone_type
        int capacity
        float area_sq_meters
        int schedule_start_hour
        int schedule_end_hour
    }
    SENSOR {
        uuid id PK
        uuid zone_id FK
        uuid equipment_id FK
        string code
        string sensor_type
        string unit
        string status
    }
    TELEMETRY_READING {
        uuid id PK
        uuid sensor_id FK
        uuid zone_id FK
        string metric
        float value
        string unit
        timestamptz timestamp
        string source
        string quality
    }
    INCIDENT {
        uuid id PK
        uuid campus_id FK
        uuid zone_id FK
        uuid sensor_id FK
        string category
        string severity
        string status
        string title
        float impact_score
        jsonb evidence
    }
    VISION_OBSERVATION {
        uuid id PK
        string camera_id
        string zone_code FK
        string observation_type
        int value
        float confidence
        timestamptz observed_at
        jsonb evidence
    }
    CORRELATION_RUN {
        uuid id PK
        string zone_code
        string result_status
        string root_cause
        float evidence_score
        float confidence_score
        jsonb findings
    }
    SIMULATION_RUN {
        uuid id PK
        string zone_code
        uuid correlation_run_id FK
        string status
        jsonb baseline
        jsonb constraints
    }
    SIMULATION_OPTION {
        uuid id PK
        uuid simulation_run_id FK
        uuid intervention_id FK
        bool feasible
        float overall_score
    }
    INTERVENTION {
        uuid id PK
        string name UK
        string domain
        float cost
        string status
    }
    APPROVAL_REQUEST {
        uuid id PK
        uuid simulation_id FK
        string request_code
        string status
        string requested_by
        string reviewed_by
    }
    APPROVAL_EVENT {
        uuid id PK
        uuid approval_request_id FK
        string previous_status
        string new_status
        string actor
        string reason
    }
```

---

## 12. API Endpoint Map

```mermaid
mindmap
  root((API))
    Campus
      GET /campus/{code}/twin
      GET /campus/{code}/telemetry/latest
    Incidents
      GET /incidents
      GET /incidents/summary
    Correlation
      POST /correlation/analyze
      GET /correlation/zone/{code}
    Vision
      POST /vision/analyze
      GET /vision/zone/{code}/latest
      GET /vision/status
    Interventions
      GET /interventions
      GET /interventions/{code}
    Impact
      POST /impact/analyze
    Simulation
      POST /simulation/run
      GET /simulation/{run_id}
      GET /simulation/{run_id}/comparison
    Digital Twin
      GET /digital-twin/snapshot
      GET /digital-twin/entities/{id}
    Approvals
      POST /approvals
      GET /approvals
      GET /approvals/pending
      GET /approvals/{id}
      GET /approvals/{id}/events
      POST /approvals/{id}/review
      POST /approvals/{id}/prepare
      POST /approvals/{id}/execute
    Copilot
      POST /copilot/ask
      GET /copilot/health
    System
      GET /
      GET /health
```

---

## 13. Feature Flags & Degradation

```mermaid
flowchart TD
    subgraph Flags["Feature Flags"]
        MQTT[MQTT_ENABLED<br/>default: false]
        INTEL[INTELLIGENCE_ENABLED<br/>default: true]
        VISION[VISION_ENABLED<br/>default: false]
    end

    subgraph Degradation["Graceful Degradation"]
        MQTT_OFF[MQTT disabled<br/>No telemetry ingestion<br/>API serves last stored data]
        INTEL_OFF[Intelligence disabled<br/>No new incidents created<br/>Existing incidents still served]
        VISION_OFF[Vision disabled<br/>No vision routes registered<br/>Correlation uses sensor data only]
        LLM_OFF[LLM unavailable<br/>Copilot uses deterministic answers<br/>Evidence still computed in Python]
        TELEMETRY_DOWN[Telemetry pipeline down<br/>API still serves<br/>Stale data shown honestly]
    end

    MQTT -->|false| MQTT_OFF
    INTEL -->|false| INTEL_OFF
    VISION -->|false| VISION_OFF
    LLM_OFF -.->|always works| TELEMETRY_DOWN
```

---

## 14. Trust Boundaries

```mermaid
flowchart LR
    subgraph ReadOnly["Read-Only Surfaces"]
        TWIN_API[Digital Twin API<br/>Read-only snapshot]
        INC_API[Incidents API<br/>Read-only listing]
        COP_API[Copilot API<br/>Read-only answers<br/>No write surface]
        SIM_API[Simulation API<br/>Simulated figures only<br/>No actuation]
        INT_API[Interventions API<br/>Read-only library]
        IMP_API[Impact API<br/>Modeled projections]
    end

    subgraph Control["Control Boundary"]
        APPR_API[Approvals API<br/>Only place status changes<br/>Human decision required<br/>Execution is SIMULATED]
    end

    subgraph Ingestion["Ingestion Surfaces"]
        TELE_IN[Telemetry Ingestion<br/>MQTT → Writer → Supabase]
        VISION_IN[Vision Ingestion<br/>Image → Detector → Supabase]
    end

    subgraph External["External Trust"]
        MQTT_BROKER[MQTT Broker<br/>Untrusted messages<br/>7-step validation]
        CAMERA[Camera Image<br/>Untrusted upload<br/>Format + size validation]
        LLM[Llm<br/>Untrusted prose<br/>Contradiction check<br/>Evidence computed in Python]
    end

    External -->|Validated| Ingestion
    Ingestion -->|Stored data| ReadOnly
    ReadOnly -->|Recommendations| Control
    Control -->|Simulated only| Result[No physical<br/>system modified]
```
