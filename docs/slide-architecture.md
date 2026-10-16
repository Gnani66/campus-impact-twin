# Campus Impact Twin — Simple Architecture

```mermaid
flowchart LR
    subgraph SENSORS[" "]
        SIM[Simulator]
        CAM[Camera]
    end

    subgraph INGEST[" "]
        MQTT[MQTT Broker]
        VISION[Vision API]
    end

    subgraph STORE[" "]
        DB[(Supabase)]
    end

    subgraph BRAIN[" "]
        RULES[Rules Engine]
        CORR[Correlation]
        SIM[Simulation]
    end

    subgraph ACTION[" "]
        APPROVAL[Human Approval]
        TWIN[Digital Twin]
    end

    subgraph USER[" "]
        DASH[Dashboard]
        COP[AI Copilot]
    end

    SIM --> MQTT --> DB
    CAM --> VISION --> DB
    DB --> RULES --> DB
    DB --> CORR --> DB
    DB --> SIM --> APPROVAL
    DB --> TWIN --> DASH
    DASH --> COP
    COP --> DASH
    APPROVAL -->|Simulated only| DB

    style SENSORS fill:#4A90D9,stroke:#2C5F8A,color:#fff
    style INGEST fill:#27AE60,stroke:#1A7A42,color:#fff
    style STORE fill:#F39C12,stroke:#B9770E,color:#fff
    style BRAIN fill:#E67E22,stroke:#BA6418,color:#fff
    style ACTION fill:#E74C3C,stroke:#B03A2E,color:#fff
    style USER fill:#8E44AD,stroke:#6C3483,color:#fff

    style SIM fill:#5DADE2,stroke:#2E86C1,color:#fff
    style CAM fill:#5DADE2,stroke:#2E86C1,color:#fff
    style MQTT fill:#52BE80,stroke:#1E8449,color:#fff
    style VISION fill:#52BE80,stroke:#1E8449,color:#fff
    style DB fill:#F5B041,stroke:#B9770E,color:#fff
    style RULES fill:#EB984E,stroke:#BA6418,color:#fff
    style CORR fill:#EB984E,stroke:#BA6418,color:#fff
    style SIM fill:#EB984E,stroke:#BA6418,color:#fff
    style APPROVAL fill:#EC7063,stroke:#B03A2E,color:#fff
    style TWIN fill:#EC7063,stroke:#B03A2E,color:#fff
    style DASH fill:#AF7AC5,stroke:#6C3483,color:#fff
    style COP fill:#AF7AC5,stroke:#6C3483,color:#fff
```

---

## User Flow

```mermaid
flowchart LR
    A[Dashboard] -->|Live status| B[3D Twin]
    B -->|Click zone| C[Incidents]
    C -->|Ask why| D[Copilot]
    D -->|Suggests action| E[Approvals]
    E -->|You decide| F[Simulated Result]
    F -->|Nothing physical changes| G[Back to Dashboard]

    style A fill:#AF7AC5,stroke:#6C3483,color:#fff
    style B fill:#EC7063,stroke:#B03A2E,color:#fff
    style C fill:#E67E22,stroke:#BA6418,color:#fff
    style D fill:#AF7AC5,stroke:#6C3483,color:#fff
    style E fill:#E74C3C,stroke:#B03A2E,color:#fff
    style F fill:#F39C12,stroke:#B9770E,color:#fff
    style G fill:#27AE60,stroke:#1A7A42,color:#fff
```

---

## One-Liner

> **Sensors → Data → Rules → Incidents → Copilot → You decide → Simulated result**
>
> Nothing acts without a human. Execution is always simulated.
