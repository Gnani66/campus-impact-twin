Campus Impact Twin

PROJECT STATUS

This folder contains a partial upload of the Campus Impact Twin codebase. Only a portion of the full project has been uploaded to this drive due to time constraints. The complete source code is available on GitHub.

WHAT IS CAMPUS IMPACT TWIN?

A smart campus operations platform that connects a 3D digital twin, real-time sensor telemetry, deterministic intelligence rules, computer vision, and intervention simulation — so campus teams can understand emerging issues and evaluate decisions before acting.

KEY FEATURES

  • 3D Digital Twin — Live campus model with status markers per zone
  • Telemetry Pipeline — MQTT-based sensor ingestion with batched writes
  • Intelligence Engine — Deterministic rules for temperature, humidity, CO2, energy, and occupancy
  • Correlation Engine — Multi-source evidence gate (vision + telemetry + schedule)
  • AI Copilot — Natural language answers with verified evidence
  • Simulation — What-if analysis comparing interventions
  • Human Approval — Every action requires a named reviewer; execution is always simulated

TECH STACK

  Frontend    Next.js, React, TypeScript, Tailwind CSS, React Three Fiber
  Backend     FastAPI, Python
  Database    Supabase (PostgreSQL)
  AI          Ollama (local LLM) with deterministic fallback
  Vision      YOLO11n person detection

FULL SOURCE CODE

The complete and up-to-date codebase is available at:

  https://github.com/Gnani66/campus-impact-twin

Please refer to the GitHub repository for the full project, including all source files, tests, migrations, and documentation.

ARCHITECTURE AT A GLANCE

  Sensors → Data → Rules → Incidents → Copilot → You decide → Simulated result

Nothing acts without a human. Execution is always simulated.

CONTACT

For questions or access to the full codebase, refer to the GitHub repository linked above.
