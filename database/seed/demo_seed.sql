-- ============================================================
-- CAMPUS IMPACT TWIN
-- DEMO DATA
-- ============================================================

-- ============================================================
-- BUILDING
-- ============================================================

insert into buildings (
    id,
    name,
    code,
    description,
    latitude,
    longitude
)
values (
    '00000000-0000-0000-0000-000000000001',
    'Academic Block',
    'AB01',
    'Primary academic building used for the Campus Impact Twin demo.',
    13.0326,
    77.7147
)
on conflict (id) do nothing;

-- ============================================================
-- LECTURE HALL
-- ============================================================

insert into zones (
    id,
    building_id,
    name,
    code,
    type,
    floor,
    schedule_start_hour,
    schedule_end_hour,
    active_days,
    timezone
)
values (
    '00000000-0000-0000-0000-000000000101',
    '00000000-0000-0000-0000-000000000001',
    'Lecture Hall 1',
    'LH01',
    'lecture_hall',
    1,
    8,
    18,
    '{1,2,3,4,5}',
    'Asia/Kolkata'
)
on conflict (id) do nothing;

-- ============================================================
-- SECOND ZONE
-- ============================================================

insert into zones (
    id,
    building_id,
    name,
    code,
    type,
    floor,
    schedule_start_hour,
    schedule_end_hour,
    active_days,
    timezone
)
values (
    '00000000-0000-0000-0000-000000000102',
    '00000000-0000-0000-0000-000000000001',
    'Computer Laboratory 1',
    'CL01',
    'lab',
    1,
    8,
    20,
    '{1,2,3,4,5,6}',
    'Asia/Kolkata'
)
on conflict (id) do nothing;

-- ============================================================
-- ENERGY TELEMETRY
-- ============================================================

insert into telemetry_readings (
    zone_id,
    resource,
    metric,
    unit,
    value,
    timestamp,
    provenance
)
values
(
    '00000000-0000-0000-0000-000000000101',
    'energy',
    'power',
    'kW',
    4.8,
    now() - interval '2 minutes',
    'simulated'
),
(
    '00000000-0000-0000-0000-000000000101',
    'energy',
    'baseline_power',
    'kW',
    1.2,
    now() - interval '2 minutes',
    'simulated'
),
(
    '00000000-0000-0000-0000-000000000102',
    'energy',
    'power',
    'kW',
    7.4,
    now() - interval '1 minute',
    'simulated'
);

-- ============================================================
-- WATER TELEMETRY
-- ============================================================

insert into telemetry_readings (
    zone_id,
    resource,
    metric,
    unit,
    value,
    timestamp,
    provenance
)
values
(
    '00000000-0000-0000-0000-000000000101',
    'water',
    'flow_rate',
    'L/min',
    2.1,
    now() - interval '3 minutes',
    'simulated'
),
(
    '00000000-0000-0000-0000-000000000102',
    'water',
    'flow_rate',
    'L/min',
    3.7,
    now() - interval '4 minutes',
    'simulated'
);

-- ============================================================
-- WASTE TELEMETRY
-- ============================================================

insert into telemetry_readings (
    zone_id,
    resource,
    metric,
    unit,
    value,
    timestamp,
    provenance
)
values
(
    '00000000-0000-0000-0000-000000000101',
    'waste',
    'estimated_kg_per_day',
    'kg/day',
    5.8,
    now() - interval '10 minutes',
    'simulated'
),
(
    '00000000-0000-0000-0000-000000000102',
    'waste',
    'estimated_kg_per_day',
    'kg/day',
    11.4,
    now() - interval '12 minutes',
    'simulated'
);

-- ============================================================
-- OCCUPANCY OBSERVATION
-- ============================================================

insert into occupancy_observations (
    zone_id,
    timestamp,
    detected_people,
    confidence,
    source,
    quality,
    occupancy_state
)
values
(
    '00000000-0000-0000-0000-000000000101',
    now() - interval '18 minutes',
    0,
    0.91,
    'camera',
    'strong',
    'potentially_unoccupied'
),
(
    '00000000-0000-0000-0000-000000000101',
    now() - interval '10 minutes',
    0,
    0.92,
    'camera',
    'strong',
    'potentially_unoccupied'
),
(
    '00000000-0000-0000-0000-000000000101',
    now() - interval '2 minutes',
    0,
    0.91,
    'camera',
    'strong',
    'potentially_unoccupied'
);

-- ============================================================
-- EVIDENCE
-- ============================================================

insert into evidence (
    id,
    zone_id,
    source,
    description,
    timestamp,
    confidence,
    quality,
    reference_id
)
values
(
    '00000000-0000-0000-0000-000000001001',
    '00000000-0000-0000-0000-000000000101',
    'camera',
    'Camera detected zero people across sustained observations.',
    now() - interval '2 minutes',
    0.91,
    'strong',
    'OBS-LH01-CAMERA'
),
(
    '00000000-0000-0000-0000-000000001002',
    '00000000-0000-0000-0000-000000000101',
    'telemetry',
    'Lecture Hall 1 continues consuming 4.8 kW.',
    now() - interval '2 minutes',
    0.98,
    'strong',
    'TEL-LH01-ENERGY'
),
(
    '00000000-0000-0000-0000-000000001003',
    '00000000-0000-0000-0000-000000000101',
    'schedule',
    'Lecture Hall 1 is inside its configured operating schedule.',
    now(),
    1.0,
    'strong',
    'SCH-LH01'
);

-- ============================================================
-- INCIDENT
-- ============================================================

insert into incidents (
    id,
    zone_id,
    domain,
    title,
    description,
    severity,
    status,
    impact_score,
    trigger_rule
)
values (
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000000101',
    'energy',
    'Potential energy waste in Lecture Hall 1',
    'Sustained zero-person observations coincide with energy consumption significantly above the configured baseline.',
    'high',
    'open',
    87,
    'ZERO_OCCUPANCY_AND_HIGH_ENERGY'
)
on conflict (id) do nothing;

-- ============================================================
-- INCIDENT ↔ EVIDENCE
-- ============================================================

insert into incident_evidence (
    incident_id,
    evidence_id
)
values
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000001001'
),
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000001002'
),
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000001003'
)
on conflict do nothing;

-- ============================================================
-- INTERVENTIONS
-- ============================================================

insert into interventions (
    id,
    name,
    domain,
    description,
    cost,
    maintenance_hours,
    expected_energy_kwh,
    expected_water_litres,
    expected_waste_kg,
    expected_emissions_kg_co2e,
    confidence,
    minimum_evidence_quality,
    status
)
values
(
    '00000000-0000-0000-0000-000000003001',
    'HVAC schedule adjustment',
    'energy',
    'Adjust HVAC operation to align with verified occupancy and room schedule.',
    2500,
    1.5,
    18.0,
    0,
    0,
    7.2,
    0.88,
    'strong',
    'eligible'
),
(
    '00000000-0000-0000-0000-000000003002',
    'Lighting schedule adjustment',
    'energy',
    'Reduce unnecessary lighting runtime during verified low-occupancy periods.',
    1200,
    1.0,
    8.5,
    0,
    0,
    3.4,
    0.94,
    'moderate',
    'eligible'
),
(
    '00000000-0000-0000-0000-000000003003',
    'Equipment shutdown protocol',
    'energy',
    'Introduce a verified shutdown procedure for non-essential room equipment.',
    800,
    0.5,
    5.2,
    0,
    0,
    2.1,
    0.81,
    'moderate',
    'eligible'
),
(
    '00000000-0000-0000-0000-000000003004',
    'Energy audit inspection',
    'energy',
    'Perform an operational inspection before changing equipment schedules.',
    500,
    2.0,
    2.0,
    0,
    0,
    0.8,
    0.97,
    'weak',
    'eligible'
),
(
    '00000000-0000-0000-0000-000000003005',
    'Leak inspection',
    'water',
    'Inspect water fixtures and nearby plumbing for abnormal consumption.',
    900,
    2.5,
    0,
    1200,
    0,
    0,
    0.86,
    'moderate',
    'eligible'
),
(
    '00000000-0000-0000-0000-000000003006',
    'Waste collection optimization',
    'waste',
    'Adjust collection timing based on estimated waste generation.',
    700,
    1.0,
    0,
    0,
    9.0,
    1.8,
    0.90,
    'moderate',
    'eligible'
)
on conflict (id) do nothing;

-- ============================================================
-- INCIDENT ↔ INTERVENTIONS
-- ============================================================

insert into incident_interventions (
    incident_id,
    intervention_id
)
values
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000003001'
),
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000003002'
),
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000003003'
),
(
    '00000000-0000-0000-0000-000000002001',
    '00000000-0000-0000-0000-000000003004'
)
on conflict do nothing;

-- ============================================================
-- DEFAULT SCENARIO
-- ============================================================

insert into scenarios (
    id,
    name,
    zone_id,
    budget,
    maintenance_hours,
    profile,
    occupancy_confidence,
    telemetry_freshness_minutes
)
values (
    '00000000-0000-0000-0000-000000004001',
    'Lecture Hall 1 — Morning Review',
    '00000000-0000-0000-0000-000000000101',
    10000,
    8,
    'environment_first',
    0.91,
    2
)
on conflict (id) do nothing;