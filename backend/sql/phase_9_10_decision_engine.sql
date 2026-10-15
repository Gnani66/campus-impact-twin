-- ============================================================
-- PHASE 9 + 10
-- IMPACT, INTERVENTIONS AND WHAT-IF SIMULATION
-- ============================================================
--
-- Applied by the operator in the Supabase SQL editor. Recorded
-- here so the schema the code expects is version controlled and
-- a fresh environment can be built from the repository alone.
--
-- The four concepts, in dependency order:
--
--   interventions      what we COULD do about a condition
--   intervention_impacts what each one is modelled to achieve
--   simulation_runs    one what-if comparison
--   simulation_options one candidate option within that run
--
-- Nothing here actuates equipment. The engine models; a human
-- approves; a later phase may execute.
-- ============================================================


create extension if not exists pgcrypto;


-- ============================================================
-- INTERVENTIONS
-- ============================================================
--
-- An intervention is not an incident. An incident says something
-- needs attention; an intervention says here is something we
-- could do about it.
--
-- `assumptions` and `constraints` are JSON so the library can
-- grow without the engine being rewritten. An intervention
-- carries its own reasoning:
--
--   assumptions: {"baseline_reduction_percent": 30,
--                 "max_reduction_percent": 50}
--   constraints: ["must_be_within_operating_window",
--                 "requires_hvac_control"]
-- ============================================================


create table if not exists interventions (
    id uuid primary key default gen_random_uuid(),

    code text not null unique,

    name text not null,

    description text,

    category text not null
        check (
            category in (
                'energy',
                'water',
                'waste',
                'occupancy',
                'hvac',
                'lighting',
                'maintenance',
                'operations'
            )
        ),

    -- The metric this intervention acts on. Interventions are
    -- matched to a condition by this, not by category alone.
    target_metric text not null,

    estimated_cost numeric not null default 0
        check (estimated_cost >= 0),

    estimated_duration_minutes integer
        check (
            estimated_duration_minutes is null
            or estimated_duration_minutes >= 0
        ),

    disruption_level text not null default 'low'
        check (
            disruption_level in (
                'low',
                'medium',
                'high'
            )
        ),

    -- The evidence bar this intervention demands. An analysis
    -- below it is refused rather than downgraded: this is the
    -- mechanism that lets the engine say NO SAFE RECOMMENDATION.
    minimum_evidence_score numeric
        not null default 70
        check (
            minimum_evidence_score >= 0
            and minimum_evidence_score <= 100
        ),

    enabled boolean not null default true,

    assumptions jsonb not null default '{}'::jsonb,

    constraints jsonb not null default '[]'::jsonb,

    created_at timestamptz not null default now(),

    updated_at timestamptz not null default now()
);


create index if not exists
idx_interventions_category
on interventions (
    category
);


-- ============================================================
-- INTERVENTION IMPACT MODELS
-- ============================================================
--
-- "Energy saving = 30%" is not a number. 30% of what, from which
-- baseline, on what evidence, and with how much uncertainty?
--
-- `evidence_source` and `assumptions` carry that reasoning, and
-- `minimum_value`/`maximum_value` bound the claim so it can be
-- stress tested rather than presented as a single figure.
-- ============================================================


create table if not exists intervention_impacts (
    id uuid primary key default gen_random_uuid(),

    intervention_id uuid not null
        references interventions(id)
        on delete cascade,

    metric text not null,

    unit text not null,

    impact_type text not null
        check (
            impact_type in (
                'absolute',
                'percentage',
                'range'
            )
        ),

    expected_value numeric,

    minimum_value numeric,

    maximum_value numeric,

    confidence numeric
        check (
            confidence >= 0
            and confidence <= 1
        ),

    evidence_source text not null,

    assumptions jsonb not null default '{}'::jsonb,

    created_at timestamptz not null
        default now()
);


create index if not exists
idx_intervention_impacts_intervention
on intervention_impacts (
    intervention_id
);


-- ============================================================
-- SIMULATION RUNS
-- ============================================================
--
-- One what-if comparison for a zone. Written even when the run
-- was blocked: a refused decision is still a decision worth
-- auditing.
-- ============================================================


create table if not exists simulation_runs (
    id uuid primary key default gen_random_uuid(),

    zone_code text not null,

    -- The correlation run this simulation reasoned from. The
    -- engine never re-runs the gate, so a decision is always
    -- traceable to recorded evidence rather than to a fresh
    -- judgement that might differ.
    correlation_run_id uuid,

    scenario_name text not null,

    baseline jsonb not null default '{}'::jsonb,

    constraints jsonb not null default '[]'::jsonb,

    status text not null default 'completed'
        check (
            status in (
                'draft',
                'running',
                'completed',
                'failed'
            )
        ),

    created_at timestamptz not null
        default now()
);


create index if not exists
idx_simulation_zone_time
on simulation_runs (
    zone_code,
    created_at desc
);


-- ============================================================
-- SIMULATION OPTIONS
-- ============================================================
--
-- One candidate within a run. Infeasible options are stored,
-- not dropped: a reviewer must be able to see that an option
-- was considered and why it was refused.
-- ============================================================


create table if not exists simulation_options (
    id uuid primary key default gen_random_uuid(),

    simulation_run_id uuid not null
        references simulation_runs(id)
        on delete cascade,

    intervention_id uuid not null
        references interventions(id),

    feasible boolean not null,

    feasibility_reasons jsonb not null default '[]'::jsonb,

    estimated_cost numeric not null default 0,

    projected_energy_reduction numeric,

    projected_water_reduction numeric,

    projected_waste_reduction numeric,

    projected_co2_reduction numeric,

    disruption_score numeric,

    impact_score numeric,

    confidence_score numeric,

    overall_score numeric,

    assumptions jsonb not null default '{}'::jsonb,

    created_at timestamptz not null
        default now()
);


create index if not exists
idx_simulation_options_run
on simulation_options (
    simulation_run_id
);