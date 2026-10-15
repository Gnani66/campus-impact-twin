-- ============================================================
-- SMART CAMPUS DIGITAL TWIN
-- PHASE 7 — VISION OBSERVATIONS
--
-- Run order:
--   001_smart_campus.sql
--   002_seed_smart_campus.sql
--   003_vision_observations.sql
--
-- This migration is idempotent and safe to re-run.
--
-- NOT EXECUTED DURING IMPLEMENTATION. The Phase 7 backend was
-- built and verified without a database write. Apply this file
-- in the Supabase SQL editor as a separate, deliberate step.
-- ============================================================


-- ============================================================
-- VISION_OBSERVATIONS
--
-- One row per analysed image.
--
-- This records a measurement, not a decision. A row here
-- never means an incident was raised, an IoT sensor was
-- declared faulty or any equipment was actuated. Comparing a
-- camera count against IoT occupancy is a separate, explicitly
-- designed step that does not exist yet.
--
-- There is deliberately no foreign key to a camera table: the
-- schema has none, and `camera_id` is a caller-supplied label
-- rather than a registered entity. Inventing a `cameras`
-- table here would fabricate a relationship the rest of the
-- project does not have.
--
-- `zone_code` is a real foreign-key candidate because
-- `zones.code` is already unique (001_smart_campus.sql), so
-- it is constrained. That makes a stored observation always
-- refer to a zone that existed.
-- ============================================================

create table if not exists vision_observations (
    id uuid primary key default gen_random_uuid(),

    camera_id text not null,

    zone_code text not null
        references zones(code)
        on delete cascade,

    observation_type text not null default 'people_count'
        check (
            observation_type in ('people_count')
        ),

    value integer not null
        check (value >= 0),

    unit text not null default 'people',

    -- Five decimal places. A detector confidence is a float
-- averaged over detections, so the third significant figure
-- onwards is not meaningful, but four places (numeric(5,4))
-- visibly disagreed with the value the API had just returned:
-- 0.8498355746 was stored as 0.8498. Five places keeps the
-- stored value within half an ulp of what the detector
-- produced, which is as close as a decimal column can get.
-- The range 0..1 fits comfortably inside numeric(6,5).
confidence numeric(6,5) not null default 0
        check (
            confidence between 0 and 1
        ),

    observed_at timestamptz not null default now(),

    evidence jsonb not null default '[]'::jsonb,

    created_at timestamptz not null default now()
);


-- ============================================================
-- INDEXES
--
-- The read path is always "newest observation for a zone",
-- which the (zone_code, observed_at desc) index serves
-- directly. The camera index supports per-camera history.
-- Both are created in the descending order the queries use so
-- no extra sort is needed.
-- ============================================================

create index if not exists idx_vision_zone_observed
    on vision_observations(zone_code, observed_at desc);

create index if not exists idx_vision_camera_observed
    on vision_observations(camera_id, observed_at desc);


-- ============================================================
-- ROW LEVEL SECURITY
--
-- Matches the established model: RLS is enabled and no policy
-- is granted, because the backend reads and writes with the
-- service role key, which bypasses RLS. That keeps anon and
-- authenticated roles locked out of observation data, which
-- includes imagery-derived information about occupants.
-- ============================================================

alter table vision_observations enable row level security;