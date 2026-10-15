-- ============================================================
-- LEGACY DATA SNAPSHOT
-- Campus Impact Twin schema (superseded by Phase 4)
-- Reference only. DO NOT RUN.
-- Captured before backend/migrations/001_smart_campus.sql dropped these tables.

-- Restore order (FK dependencies):
--   buildings -> zones -> equipment -> sensors -> telemetry_readings
--   -> incidents -> occupancy_observations -> evidence
--   -> incident_evidence -> interventions -> incident_interventions
--   -> scenarios -> decision_runs -> impact_passports -> audit_events
-- ============================================================

-- ---------- buildings: 1 row(s)

insert into public.buildings (id, code, name, description, latitude, longitude, created_at, updated_at) values
    ('1211b940-7d36-45a1-906a-65f2c0f7cca7', 'CIT-MAIN', 'Cambridge Institute of Technology', 'Primary campus used for the Smart Campus Digital Twin simulation.', null, null, '2026-10-15T06:32:16.426331+00:00', '2026-10-15T07:14:15.114473+00:00');

-- ---------- zones: 1 row(s)

insert into public.zones (id, building_id, code, name, type, floor, schedule_start_hour, schedule_end_hour, active_days, timezone, metadata, created_at, updated_at) values
    ('7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', '1211b940-7d36-45a1-906a-65f2c0f7cca7', 'LH01', 'University Lecture Hall', 'lecture_hall', 0, 8, 18, '{1,2,3,4,5}', 'Asia/Kolkata', '{}'::jsonb, '2026-10-15T06:32:16.426331+00:00', '2026-10-15T06:32:16.426331+00:00');

-- ---------- equipment: 1 row(s)

insert into public.equipment (id, zone_id, code, name, type, status, metadata, created_at, updated_at) values
    ('f8462e98-928b-4019-8c17-c57378cb83ec', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'HVAC-LH01', 'Lecture Hall HVAC', 'hvac', 'active', '{"position": [0, 3.4, 2], "model_object": "HVAC", "twin_object_id": "HVAC-LH01"}'::jsonb, '2026-10-15T06:32:29.524639+00:00', '2026-10-15T06:32:29.524639+00:00');

-- ---------- sensors: 2 row(s)

insert into public.sensors (id, zone_id, code, name, type, unit, status, metadata, created_at, updated_at) values
    ('dd32db6e-ac1a-48cc-bf7d-34c0d45f1a4e', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'OCC-LH01', 'Lecture Hall Occupancy Sensor', 'occupancy', 'people', 'active', '{"position": [-2.5, 2.8, -1.5], "model_object": "Sensor_Occupancy", "twin_object_id": "OCC-LH01"}'::jsonb, '2026-10-15T06:32:29.524639+00:00', '2026-10-15T06:32:29.524639+00:00'),
    ('a5c0b675-ef79-4d70-a166-4ba4173daa8c', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'ENERGY-LH01', 'Lecture Hall Energy Meter', 'energy', 'kW', 'active', '{"position": [2.4, 3, -1.2], "model_object": "Energy_Meter", "twin_object_id": "ENERGY-LH01"}'::jsonb, '2026-10-15T06:32:29.524639+00:00', '2026-10-15T06:32:29.524639+00:00');

-- ---------- telemetry_readings: 0 row(s)

-- ---------- incidents: 1 row(s)

insert into public.incidents (id, zone_id, equipment_id, sensor_id, domain, title, description, severity, status, impact_score, trigger_rule, evidence, created_at, updated_at, resolved_at) values
    ('00000000-0000-0000-0000-000000002001', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', null, null, 'energy', 'Potential energy waste in University Lecture Hall', 'Sustained zero-person observations coincide with energy consumption significantly above the configured baseline.', 'high', 'open', 87.0, 'ZERO_OCCUPANCY_AND_HIGH_ENERGY', '{{'source': 'camera', 'confidence': 0.91, 'description': 'Camera detected zero people across sustained observations.', 'reference_id': 'OBS-LH01-CAMERA'},{'source': 'telemetry', 'confidence': 0.98, 'description': 'University Lecture Hall continues consuming 4.8 kW.', 'reference_id': 'TEL-LH01-ENERGY'},{'source': 'schedule', 'confidence': 1.0, 'description': 'University Lecture Hall is inside its configured operating schedule.', 'reference_id': 'SCH-LH01'}}', '2026-10-15T07:14:24.087509+00:00', '2026-10-15T07:14:24.087509+00:00', null);

-- ---------- occupancy_observations: 3 row(s)

insert into public.occupancy_observations (id, zone_id, timestamp, detected_people, confidence, source, quality, occupancy_state, metadata, created_at) values
    ('d3978854-3fb4-4ea7-9d91-a601ae8db092', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', '2026-10-14T16:07:02.017616+00:00', 0, 0.91, 'camera', 'strong', 'potentially_unoccupied', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00'),
    ('2de89ed8-a12e-476c-baa6-1b57155701b1', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', '2026-10-14T16:15:02.017616+00:00', 0, 0.92, 'camera', 'strong', 'potentially_unoccupied', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00'),
    ('e3d9297d-1821-4b80-8e1e-7eb967245aaa', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', '2026-10-14T16:23:02.017616+00:00', 0, 0.91, 'camera', 'strong', 'potentially_unoccupied', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00');

-- ---------- evidence: 3 row(s)

insert into public.evidence (id, zone_id, source, description, timestamp, confidence, quality, reference_id, metadata, created_at) values
    ('00000000-0000-0000-0000-000000001001', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'camera', 'Camera detected zero people across sustained observations.', '2026-10-14T16:23:02.017616+00:00', 0.91, 'strong', 'OBS-LH01-CAMERA', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000001002', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'telemetry', 'Lecture Hall 1 continues consuming 4.8 kW.', '2026-10-14T16:23:02.017616+00:00', 0.98, 'strong', 'TEL-LH01-ENERGY', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000001003', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 'schedule', 'Lecture Hall 1 is inside its configured operating schedule.', '2026-10-14T16:25:02.017616+00:00', 1, 'strong', 'SCH-LH01', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00');

-- ---------- incident_evidence: 3 row(s)

insert into public.incident_evidence (incident_id, evidence_id) values
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000001001'),
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000001002'),
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000001003');

-- ---------- interventions: 6 row(s)

insert into public.interventions (id, name, domain, description, cost, maintenance_hours, expected_energy_kwh, expected_water_litres, expected_waste_kg, expected_emissions_kg_co2e, confidence, minimum_evidence_quality, prerequisites, incompatible_with, status, metadata, created_at, updated_at) values
    ('00000000-0000-0000-0000-000000003001', 'HVAC schedule adjustment', 'energy', 'Adjust HVAC operation to align with verified occupancy and room schedule.', 2500, 1.5, 18, 0, 0, 7.2, 0.88, 'strong', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000003002', 'Lighting schedule adjustment', 'energy', 'Reduce unnecessary lighting runtime during verified low-occupancy periods.', 1200, 1, 8.5, 0, 0, 3.4, 0.94, 'moderate', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000003003', 'Equipment shutdown protocol', 'energy', 'Introduce a verified shutdown procedure for non-essential room equipment.', 800, 0.5, 5.2, 0, 0, 2.1, 0.81, 'moderate', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000003004', 'Energy audit inspection', 'energy', 'Perform an operational inspection before changing equipment schedules.', 500, 2, 2, 0, 0, 0.8, 0.97, 'weak', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000003005', 'Leak inspection', 'water', 'Inspect water fixtures and nearby plumbing for abnormal consumption.', 900, 2.5, 0, 1200, 0, 0, 0.86, 'moderate', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00'),
    ('00000000-0000-0000-0000-000000003006', 'Waste collection optimization', 'waste', 'Adjust collection timing based on estimated waste generation.', 700, 1, 0, 0, 9, 1.8, 0.9, 'moderate', '{}', '{}', 'eligible', '{}'::jsonb, '2026-10-14T16:25:02.017616+00:00', '2026-10-14T16:25:02.017616+00:00');

-- ---------- incident_interventions: 4 row(s)

insert into public.incident_interventions (incident_id, intervention_id) values
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000003001'),
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000003002'),
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000003003'),
    ('00000000-0000-0000-0000-000000002001', '00000000-0000-0000-0000-000000003004');

-- ---------- scenarios: 1 row(s)

insert into public.scenarios (id, name, zone_id, budget, maintenance_hours, profile, occupancy_confidence, telemetry_freshness_minutes, created_at) values
    ('00000000-0000-0000-0000-000000004001', 'Lecture Hall 1 — Morning Review', '7ae93b4e-36ec-4e7b-87d2-f6a9099a3a37', 10000, 8, 'environment_first', 0.91, 2, '2026-10-14T16:25:02.017616+00:00');

-- ---------- decision_runs: 0 row(s)

-- ---------- impact_passports: 0 row(s)

-- ---------- audit_events: 0 row(s)

