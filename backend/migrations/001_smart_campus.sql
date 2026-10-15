-- ============================================================
-- SMART CAMPUS DIGITAL TWIN
-- PHASE 4 DATABASE FOUNDATION
--
-- Run order:
--   001_smart_campus.sql
--   002_seed_smart_campus.sql
--
-- This migration is idempotent and safe to re-run.
--
-- NOTE: Step 0 removes the previous "Campus Impact Twin"
-- schema, which was built around a different data model.
-- A full data snapshot of those tables was taken beforehand
-- in backend/migrations/LEGACY_snapshot_do_not_run.sql
-- (reference only - do not execute it)
-- ============================================================


-- ============================================================
-- STEP 0 — LEGACY SCHEMA CLEANUP
--
-- The old schema described a flat zone/incident model.
-- Phase 4 replaces it with the physical hierarchy:
--
--   Campus → Building → Floor → Zone
--                              ├── Equipment
--                              └── Sensors
--                                     │
--                                     ▼
--                                Telemetry
--                                     │
--                                     ▼
--                                  Analytics
--                                     │
--                                     ▼
--                                  Incidents
--                                     │
--                                     ▼
--                              Recommendations
-- ============================================================

-- Child tables first. CASCADE removes the dependent
-- foreign keys, RLS policies and triggers as well.
drop table if exists public.audit_events cascade;
drop table if exists public.impact_passports cascade;
drop table if exists public.decision_runs cascade;
drop table if exists public.scenarios cascade;
drop table if exists public.incident_interventions cascade;
drop table if exists public.incident_evidence cascade;
drop table if exists public.interventions cascade;
drop table if exists public.evidence cascade;
drop table if exists public.occupancy_observations cascade;
drop table if exists public.telemetry_readings cascade;
drop table if exists public.incidents cascade;
drop table if exists public.sensors cascade;
drop table if exists public.equipment cascade;
drop table if exists public.zones cascade;
drop table if exists public.buildings cascade;

-- Legacy enum types are no longer referenced.
drop type if exists public.audit_event_type cascade;
drop type if exists public.decision_status cascade;
drop type if exists public.evidence_quality cascade;
drop type if exists public.evidence_source cascade;
drop type if exists public.incident_severity cascade;
drop type if exists public.incident_status cascade;
drop type if exists public.intervention_status cascade;
drop type if exists public.occupancy_state cascade;
drop type if exists public.priority_profile cascade;
drop type if exists public.telemetry_provenance cascade;
drop type if exists public.resource_domain cascade;
drop type if exists public.zone_type cascade;
drop type if exists public.equipment_type cascade;
drop type if exists public.equipment_status cascade;
drop type if exists public.sensor_type cascade;
drop type if exists public.sensor_status cascade;


create extension if not exists pgcrypto;


-- ============================================================
-- CAMPUSES
-- ============================================================

create table if not exists campuses (
    id uuid primary key default gen_random_uuid(),

    code text not null unique,
    name text not null,
    description text,

    timezone text not null default 'Asia/Kolkata',

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- BUILDINGS
-- ============================================================

create table if not exists buildings (
    id uuid primary key default gen_random_uuid(),

    campus_id uuid not null
        references campuses(id)
        on delete cascade,

    code text not null unique,
    name text not null,
    description text,

    latitude double precision,
    longitude double precision,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- FLOORS
-- ============================================================

create table if not exists floors (
    id uuid primary key default gen_random_uuid(),

    building_id uuid not null
        references buildings(id)
        on delete cascade,

    code text not null unique,
    name text not null,

    floor_number integer not null,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- ZONES / ROOMS
-- ============================================================

create table if not exists zones (
    id uuid primary key default gen_random_uuid(),

    floor_id uuid not null
        references floors(id)
        on delete cascade,

    code text not null unique,
    name text not null,

    zone_type text not null
        check (
            zone_type in (
                'lecture_hall',
                'classroom',
                'laboratory',
                'office',
                'library',
                'corridor',
                'auditorium',
                'cafeteria',
                'washroom',
                'outdoor',
                'other'
            )
        ),

    capacity integer
        check (capacity is null or capacity >= 0),

    area_sq_meters numeric(10,2)
        check (
            area_sq_meters is null
            or area_sq_meters >= 0
        ),

    schedule_start_hour integer
        check (
            schedule_start_hour is null
            or schedule_start_hour between 0 and 23
        ),

    schedule_end_hour integer
        check (
            schedule_end_hour is null
            or schedule_end_hour between 0 and 23
        ),

    active_days integer[]
        default '{1,2,3,4,5}',

    twin_model_object text,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- EQUIPMENT
-- ============================================================

create table if not exists equipment (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid
        references zones(id)
        on delete set null,

    code text not null unique,
    name text not null,

    equipment_type text not null
        check (
            equipment_type in (
                'hvac',
                'lighting',
                'fan',
                'pump',
                'elevator',
                'generator',
                'solar',
                'display',
                'other'
            )
        ),

    status text not null default 'active'
        check (
            status in (
                'active',
                'inactive',
                'maintenance',
                'fault'
            )
        ),

    manufacturer text,
    model_number text,
    installation_date date,

    rated_power_kw numeric(10,3),

    twin_model_object text,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- SENSORS
-- ============================================================

create table if not exists sensors (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid
        references zones(id)
        on delete set null,

    equipment_id uuid
        references equipment(id)
        on delete set null,

    code text not null unique,
    name text not null,

    sensor_type text not null
        check (
            sensor_type in (
                'temperature',
                'humidity',
                'pressure',
                'occupancy',
                'energy',
                'air_quality',
                'co2',
                'light',
                'noise',
                'water',
                'rain',
                'uv',
                'motion',
                'other'
            )
        ),

    unit text,

    status text not null default 'active'
        check (
            status in (
                'active',
                'inactive',
                'fault'
            )
        ),

    sampling_interval_seconds integer
        check (
            sampling_interval_seconds is null
            or sampling_interval_seconds > 0
        ),

    twin_model_object text,

    metadata jsonb not null default '{}'::jsonb,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- TELEMETRY READINGS
-- ============================================================

create table if not exists telemetry_readings (
    id uuid primary key default gen_random_uuid(),

    campus_id uuid not null
        references campuses(id)
        on delete cascade,

    building_id uuid
        references buildings(id)
        on delete cascade,

    floor_id uuid
        references floors(id)
        on delete cascade,

    zone_id uuid
        references zones(id)
        on delete cascade,

    sensor_id uuid
        references sensors(id)
        on delete set null,

    equipment_id uuid
        references equipment(id)
        on delete set null,

    metric text not null,

    value double precision not null,

    unit text not null,

    timestamp timestamptz not null default now(),

    source text not null default 'simulator'
        check (
            source in (
                'sensor',
                'simulator',
                'import',
                'manual'
            )
        ),

    quality text not null default 'good'
        check (
            quality in (
                'good',
                'suspect',
                'bad'
            )
        ),

    metadata jsonb not null default '{}'::jsonb
);


-- ============================================================
-- INCIDENTS
-- ============================================================

create table if not exists incidents (
    id uuid primary key default gen_random_uuid(),

    campus_id uuid not null
        references campuses(id)
        on delete cascade,

    building_id uuid
        references buildings(id)
        on delete set null,

    zone_id uuid
        references zones(id)
        on delete set null,

    sensor_id uuid
        references sensors(id)
        on delete set null,

    equipment_id uuid
        references equipment(id)
        on delete set null,

    category text not null
        check (
            category in (
                'energy',
                'environment',
                'occupancy',
                'water',
                'equipment',
                'safety',
                'maintenance',
                'other'
            )
        ),

    severity text not null
        check (
            severity in (
                'low',
                'medium',
                'high',
                'critical'
            )
        ),

    status text not null default 'open'
        check (
            status in (
                'open',
                'acknowledged',
                'investigating',
                'resolved',
                'dismissed'
            )
        ),

    title text not null,

    description text not null,

    impact_score numeric(5,2) not null default 0
        check (
            impact_score between 0 and 100
        ),

    confidence_score numeric(5,2)
        check (
            confidence_score is null
            or confidence_score between 0 and 100
        ),

    detection_method text not null default 'rule',

    evidence jsonb not null default '[]'::jsonb,

    detected_at timestamptz not null default now(),

    acknowledged_at timestamptz,

    resolved_at timestamptz,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);


-- ============================================================
-- INDEXES
-- ============================================================

create index if not exists idx_buildings_campus
    on buildings(campus_id);

create index if not exists idx_floors_building
    on floors(building_id);

create index if not exists idx_zones_floor
    on zones(floor_id);

create index if not exists idx_equipment_zone
    on equipment(zone_id);

create index if not exists idx_sensors_zone
    on sensors(zone_id);

create index if not exists idx_sensors_equipment
    on sensors(equipment_id);

create index if not exists idx_telemetry_timestamp
    on telemetry_readings(timestamp desc);

create index if not exists idx_telemetry_zone_timestamp
    on telemetry_readings(
        zone_id,
        timestamp desc
    );

create index if not exists idx_telemetry_sensor_timestamp
    on telemetry_readings(
        sensor_id,
        timestamp desc
    );

create index if not exists idx_incidents_status
    on incidents(status);

create index if not exists idx_incidents_severity
    on incidents(severity);

create index if not exists idx_incidents_impact
    on incidents(impact_score desc);

create index if not exists idx_incidents_zone
    on incidents(zone_id);


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

drop trigger if exists campuses_updated_at
on campuses;

create trigger campuses_updated_at
before update on campuses
for each row
execute function update_updated_at();


drop trigger if exists buildings_updated_at
on buildings;

create trigger buildings_updated_at
before update on buildings
for each row
execute function update_updated_at();


drop trigger if exists floors_updated_at
on floors;

create trigger floors_updated_at
before update on floors
for each row
execute function update_updated_at();


drop trigger if exists zones_updated_at
on zones;

create trigger zones_updated_at
before update on zones
for each row
execute function update_updated_at();


drop trigger if exists equipment_updated_at
on equipment;

create trigger equipment_updated_at
before update on equipment
for each row
execute function update_updated_at();


drop trigger if exists sensors_updated_at
on sensors;

create trigger sensors_updated_at
before update on sensors
for each row
execute function update_updated_at();


drop trigger if exists incidents_updated_at
on incidents;

create trigger incidents_updated_at
before update on incidents
for each row
execute function update_updated_at();


-- ============================================================
-- ROW LEVEL SECURITY
--
-- All reads go through the FastAPI backend, which uses the
-- service role key and bypasses RLS. Enabling RLS without
-- policies keeps the anon/authenticated roles locked out of
-- the raw tables.
-- ============================================================

alter table campuses enable row level security;
alter table buildings enable row level security;
alter table floors enable row level security;
alter table zones enable row level security;
alter table equipment enable row level security;
alter table sensors enable row level security;
alter table telemetry_readings enable row level security;
alter table incidents enable row level security;
