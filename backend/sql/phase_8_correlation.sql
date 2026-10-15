-- ============================================================
-- PHASE 8
-- MULTI-SOURCE CORRELATION
-- ============================================================
--
-- Applied by the operator in the Supabase SQL editor. Recorded
-- here so the schema the code expects is version controlled and
-- a fresh environment can be built from the repository alone.
--
-- Requires pgcrypto for gen_random_uuid().
-- ============================================================


create extension if not exists pgcrypto;


-- ============================================================
-- OBSERVATIONS
-- ============================================================
--
-- The Phase 8 observation model, which supersedes
-- `vision_observations` as the source the correlation engine
-- reads. The legacy table is retained for backward
-- compatibility with existing dashboards only.
-- ============================================================


create table if not exists observations (
    id uuid primary key default gen_random_uuid(),

    zone_id uuid,

    zone_code text not null,

    source_type text not null
        check (
            source_type in (
                'camera',
                'uploaded_image',
                'uploaded_video',
                'simulation'
            )
        ),

    observation_type text not null
        check (
            observation_type in (
                'occupancy',
                'people_count'
            )
        ),

    value numeric not null
        check (value >= 0),

    unit text not null
        default 'people',

    confidence numeric
        check (
            confidence >= 0
            and confidence <= 1
        ),

    -- How much this observation can be trusted. Carried on the
    -- row rather than derived at read time so the judgement
    -- that was actually made is recoverable later.
    evidence_status text not null
        default 'usable'
        check (
            evidence_status in (
                'usable',
                'uncertain',
                'stale',
                'insufficient'
            )
        ),

    evidence jsonb not null
        default '{}'::jsonb,

    observed_at timestamptz not null,

    created_at timestamptz not null
        default now()
);


-- ============================================================
-- INDEXES
-- ============================================================


create index if not exists
idx_observations_zone_time
on observations (
    zone_code,
    observed_at desc
);


create index if not exists
idx_observations_status
on observations (
    evidence_status
);


-- ============================================================
-- CORRELATION RUNS
-- ============================================================
--
-- Every analysis leaves a trace. A run is written for each
-- outcome including `normal`: the analyses that concluded
-- nothing are the ones a reviewer asks about later.
-- ============================================================


create table if not exists correlation_runs (
    id uuid primary key default gen_random_uuid(),

    zone_code text not null,

    observation_id uuid,

    telemetry_window_start timestamptz,

    telemetry_window_end timestamptz,

    result_status text not null
        check (
            result_status in (
                'confirmed_candidate',
                'needs_review',
                'insufficient_evidence',
                'normal'
            )
        ),

    root_cause text,

    evidence_score numeric
        check (
            evidence_score >= 0
            and evidence_score <= 100
        ),

    confidence_score numeric
        check (
            confidence_score >= 0
            and confidence_score <= 100
        ),

    findings jsonb not null
        default '[]'::jsonb,

    created_at timestamptz not null
        default now()
);


create index if not exists
idx_correlation_zone_time
on correlation_runs (
    zone_code,
    created_at desc
);