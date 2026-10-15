-- ============================================================
-- CAMPUS IMPACT TWIN
-- PHASE 2 — INITIAL DATABASE SCHEMA
-- ============================================================

create extension if not exists "pgcrypto";

-- ============================================================
-- ENUM TYPES
-- ============================================================

create type resource_domain as enum (
    'energy',
    'water',
    'waste'
);

create type zone_type as enum (
    'lecture_hall',
    'classroom',
    'lab',
    'office',
    'common'
);

create type telemetry_provenance as enum (
    'observed',
    'simulated',
    'imported'
);

create type evidence_source as enum (
    'camera',
    'telemetry',
    'schedule',
    'simulation',
    'import'
);

create type evidence_quality as enum (
    'insufficient',
    'weak',
    'moderate',
    'strong'
);

create type occupancy_state as enum (
    'occupied',
    'uncertain',
    'potentially_unoccupied'
);

create type incident_severity as enum (
    'low',
    'medium',
    'high',
    'critical'
);

create type incident_status as enum (
    'open',
    'under_review',
    'resolved',
    'dismissed'
);

create type intervention_status as enum (
    'eligible',
    'requires_review',
    'ineligible'
);

create type decision_status as enum (
    'draft',
    'recommended',
    'approved',
    'rejected'
);

create type priority_profile as enum (
    'environment_first',
    'budget_efficient',
    'risk_aware'
);

create type audit_event_type as enum (
    'observation',
    'incident_created',
    'optimization',
    'stress_test',
    'explanation',
    'approval',
    'rejection',
    'scenario_reset'
);

-- ============================================================
-- BUILDINGS
-- ============================================================

create table buildings (
    id uuid primary key default gen_random_uuid(),

    name text not null,
    code text not null unique,
    description text,

    latitude double precision,
    longitude double precision,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ============================================================
-- ZONES
-- ============================================================

create table zones (
    id uuid primary key default gen_random_uuid(),

    building_id uuid not null
        references buildings(id)
        on delete cascade,

    name text not null,
    code text not null unique,

    type zone_type not null,
    floor integer not null default 0,

    schedule_start_hour integer not null default 8
        check (schedule_start_hour between 0 and 23),

    schedule_end_hour integer not null default 18
        check (schedule_end_hour between 0 and 23),

    active_days integer[] not null default
        '{1,2,3,4,5}',

    timezone text not null default 'Asia/Kolkata',

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_zones_building_id
    on zones(building_id);

-- ============================================================
-- TELEMETRY READINGS
-- ============================================================

create table telemetry_readings (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid not null
        references zones(id)
        on delete cascade,

    resource resource_domain not null,

    metric text not null,
    unit text not null,

    value double precision not null,

    timestamp timestamptz not null,

    provenance telemetry_provenance not null default 'simulated',

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now()
);

create index idx_telemetry_zone_timestamp
    on telemetry_readings(zone_id, timestamp desc);

create index idx_telemetry_resource
    on telemetry_readings(resource);

-- ============================================================
-- OCCUPANCY OBSERVATIONS
-- ============================================================

create table occupancy_observations (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid not null
        references zones(id)
        on delete cascade,

    timestamp timestamptz not null,

    detected_people integer not null
        check (detected_people >= 0),

    confidence double precision not null
        check (confidence between 0 and 1),

    source evidence_source not null,

    quality evidence_quality not null,

    occupancy_state occupancy_state not null,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now()
);

create index idx_occupancy_zone_timestamp
    on occupancy_observations(zone_id, timestamp desc);

-- ============================================================
-- EVIDENCE
-- ============================================================

create table evidence (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid not null
        references zones(id)
        on delete cascade,

    source evidence_source not null,

    description text not null,

    timestamp timestamptz,

    confidence double precision
        check (
            confidence is null
            or confidence between 0 and 1
        ),

    quality evidence_quality not null,

    reference_id text,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now()
);

create index idx_evidence_zone_timestamp
    on evidence(zone_id, timestamp desc);

-- ============================================================
-- INCIDENTS
-- ============================================================

create table incidents (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid not null
        references zones(id)
        on delete cascade,

    domain resource_domain not null,

    title text not null,
    description text not null,

    severity incident_severity not null default 'medium',

    status incident_status not null default 'open',

    impact_score double precision not null
        check (impact_score between 0 and 100),

    trigger_rule text not null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_incidents_zone
    on incidents(zone_id);

create index idx_incidents_status
    on incidents(status);

create index idx_incidents_impact
    on incidents(impact_score desc);

-- ============================================================
-- INCIDENT EVIDENCE
-- ============================================================

create table incident_evidence (
    incident_id uuid not null
        references incidents(id)
        on delete cascade,

    evidence_id uuid not null
        references evidence(id)
        on delete cascade,

    primary key (
        incident_id,
        evidence_id
    )
);

-- ============================================================
-- INTERVENTIONS
-- ============================================================

create table interventions (
    id uuid primary key default gen_random_uuid(),

    name text not null,
    domain resource_domain not null,

    description text not null,

    cost double precision not null
        check (cost >= 0),

    maintenance_hours double precision not null
        check (maintenance_hours >= 0),

    expected_energy_kwh double precision not null default 0
        check (expected_energy_kwh >= 0),

    expected_water_litres double precision not null default 0
        check (expected_water_litres >= 0),

    expected_waste_kg double precision not null default 0
        check (expected_waste_kg >= 0),

    expected_emissions_kg_co2e double precision not null default 0
        check (expected_emissions_kg_co2e >= 0),

    confidence double precision not null
        check (confidence between 0 and 1),

    minimum_evidence_quality evidence_quality not null
        default 'moderate',

    prerequisites text[] not null default '{}',
    incompatible_with text[] not null default '{}',

    status intervention_status not null default 'eligible',

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ============================================================
-- INCIDENT INTERVENTIONS
-- ============================================================

create table incident_interventions (
    incident_id uuid not null
        references incidents(id)
        on delete cascade,

    intervention_id uuid not null
        references interventions(id)
        on delete cascade,

    primary key (
        incident_id,
        intervention_id
    )
);

-- ============================================================
-- SCENARIOS
-- ============================================================

create table scenarios (
    id uuid primary key default gen_random_uuid(),

    name text not null,

    zone_id uuid not null
        references zones(id)
        on delete cascade,

    budget double precision not null
        check (budget >= 0),

    maintenance_hours double precision not null
        check (maintenance_hours >= 0),

    profile priority_profile not null,

    occupancy_confidence double precision not null
        check (occupancy_confidence between 0 and 1),

    telemetry_freshness_minutes double precision not null
        check (telemetry_freshness_minutes >= 0),

    created_at timestamptz not null default now()
);

create index idx_scenarios_zone
    on scenarios(zone_id);

-- ============================================================
-- DECISION RUNS
-- ============================================================

create table decision_runs (
    id uuid primary key default gen_random_uuid(),

    scenario_id uuid not null
        references scenarios(id)
        on delete cascade,

    status decision_status not null default 'draft',

    selected_portfolio jsonb not null default '{}'::jsonb,

    alternatives jsonb not null default '[]'::jsonb,

    stress_tests jsonb not null default '[]'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_decision_runs_scenario
    on decision_runs(scenario_id);

-- ============================================================
-- IMPACT PASSPORTS
-- ============================================================

create table impact_passports (
    id uuid primary key default gen_random_uuid(),

    decision_id uuid not null
        references decision_runs(id)
        on delete cascade,

    passport_number text not null unique,

    evidence_snapshot jsonb not null default '[]'::jsonb,

    calculation_snapshot jsonb not null default '{}'::jsonb,

    decision_snapshot jsonb not null default '{}'::jsonb,

    stability_snapshot jsonb not null default '[]'::jsonb,

    explanation text,

    approved_by text,

    approved_at timestamptz,

    created_at timestamptz not null default now()
);

create index idx_passports_decision
    on impact_passports(decision_id);

-- ============================================================
-- AUDIT EVENTS
-- ============================================================

create table audit_events (
    id uuid primary key default gen_random_uuid(),

    decision_id uuid
        references decision_runs(id)
        on delete set null,

    type audit_event_type not null,

    message text not null,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now()
);

create index idx_audit_decision
    on audit_events(decision_id);

create index idx_audit_created
    on audit_events(created_at desc);

-- ============================================================
-- UPDATED_AT FUNCTION
-- ============================================================

create or replace function update_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

-- ============================================================
-- UPDATED_AT TRIGGERS
-- ============================================================

create trigger buildings_updated_at
before update on buildings
for each row
execute function update_updated_at();

create trigger zones_updated_at
before update on zones
for each row
execute function update_updated_at();

create trigger incidents_updated_at
before update on incidents
for each row
execute function update_updated_at();

create trigger interventions_updated_at
before update on interventions
for each row
execute function update_updated_at();

create trigger decision_runs_updated_at
before update on decision_runs
for each row
execute function update_updated_at();

-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

alter table buildings enable row level security;
alter table zones enable row level security;
alter table telemetry_readings enable row level security;
alter table occupancy_observations enable row level security;
alter table evidence enable row level security;
alter table incidents enable row level security;
alter table incident_evidence enable row level security;
alter table interventions enable row level security;
alter table incident_interventions enable row level security;
alter table scenarios enable row level security;
alter table decision_runs enable row level security;
alter table impact_passports enable row level security;
alter table audit_events enable row level security;

-- ============================================================
-- DEMO READ POLICIES
--
-- For the hackathon MVP we allow anonymous reads of
-- non-sensitive demo data.
--
-- Mutations will be performed by the FastAPI backend
-- using the service role.
-- ============================================================

create policy "public read buildings"
on buildings
for select
to anon, authenticated
using (true);

create policy "public read zones"
on zones
for select
to anon, authenticated
using (true);

create policy "public read telemetry"
on telemetry_readings
for select
to anon, authenticated
using (true);

create policy "public read occupancy"
on occupancy_observations
for select
to anon, authenticated
using (true);

create policy "public read evidence"
on evidence
for select
to anon, authenticated
using (true);

create policy "public read incidents"
on incidents
for select
to anon, authenticated
using (true);

create policy "public read incident evidence"
on incident_evidence
for select
to anon, authenticated
using (true);

create policy "public read interventions"
on interventions
for select
to anon, authenticated
using (true);

create policy "public read incident interventions"
on incident_interventions
for select
to anon, authenticated
using (true);

create policy "public read scenarios"
on scenarios
for select
to anon, authenticated
using (true);

create policy "public read decision runs"
on decision_runs
for select
to anon, authenticated
using (true);

create policy "public read impact passports"
on impact_passports
for select
to anon, authenticated
using (true);

create policy "public read audit events"
on audit_events
for select
to anon, authenticated
using (true);