-- ============================================================
-- SMART CAMPUS DEMO DATA
--
-- Run after 001_smart_campus.sql.
--
-- Produces the hierarchy:
--
--   CIT-MAIN  Cambridge Institute of Technology
--   └── ACADEMIC-BLK-A  Academic Block A
--       └── A-F1  Ground Floor
--           └── LH01  University Lecture Hall
--               ├── HVAC-LH01
--               ├── OCC-LH01
--               ├── TEMP-LH01
--               ├── HUM-LH01
--               ├── CO2-LH01
--               └── ENERGY-LH01
--
-- Every statement is idempotent.
-- ============================================================


insert into campuses (
    code,
    name,
    description,
    timezone
)
values (
    'CIT-MAIN',
    'Cambridge Institute of Technology',
    'Smart Campus Digital Twin demonstration environment.',
    'Asia/Kolkata'
)
on conflict (code) do nothing;


-- ============================================================
-- BUILDING
-- ============================================================

insert into buildings (
    campus_id,
    code,
    name,
    description,
    metadata
)
select
    id,
    'ACADEMIC-BLK-A',
    'Academic Block A',
    'Primary academic building for the digital twin demonstration.',
    jsonb_build_object(
        'twin_enabled', true,
        'model', 'lecture-hall.glb'
    )
from campuses
where code = 'CIT-MAIN'
on conflict (code) do nothing;


-- ============================================================
-- FLOOR
-- ============================================================

insert into floors (
    building_id,
    code,
    name,
    floor_number
)
select
    id,
    'A-F1',
    'Ground Floor',
    0
from buildings
where code = 'ACADEMIC-BLK-A'
on conflict (code) do nothing;


-- ============================================================
-- LECTURE HALL
-- ============================================================

insert into zones (
    floor_id,
    code,
    name,
    zone_type,
    capacity,
    area_sq_meters,
    schedule_start_hour,
    schedule_end_hour,
    active_days,
    twin_model_object,
    metadata
)
select
    id,
    'LH01',
    'University Lecture Hall',
    'lecture_hall',
    60,
    120.00,
    8,
    18,
    '{1,2,3,4,5,6}',
    'lecture_hall',
    jsonb_build_object(
        'model_path',
        '/models/lecture-hall.glb',
        'digital_twin',
        true
    )
from floors
where code = 'A-F1'
on conflict (code) do nothing;


-- ============================================================
-- HVAC
-- ============================================================

insert into equipment (
    zone_id,
    code,
    name,
    equipment_type,
    status,
    rated_power_kw,
    twin_model_object,
    metadata
)
select
    id,
    'HVAC-LH01',
    'Lecture Hall HVAC',
    'hvac',
    'active',
    12.5,
    'HVAC',
    jsonb_build_object(
        'twin_object_id', 'HVAC-LH01'
    )
from zones
where code = 'LH01'
on conflict (code) do nothing;


-- ============================================================
-- OCCUPANCY SENSOR
-- ============================================================

insert into sensors (
    zone_id,
    code,
    name,
    sensor_type,
    unit,
    status,
    sampling_interval_seconds,
    twin_model_object
)
select
    id,
    'OCC-LH01',
    'Lecture Hall Occupancy Sensor',
    'occupancy',
    'people',
    'active',
    5,
    'OCCUPANCY_SENSOR'
from zones
where code = 'LH01'
on conflict (code) do nothing;


-- ============================================================
-- TEMPERATURE SENSOR
-- ============================================================

insert into sensors (
    zone_id,
    code,
    name,
    sensor_type,
    unit,
    status,
    sampling_interval_seconds,
    twin_model_object
)
select
    id,
    'TEMP-LH01',
    'Lecture Hall Temperature Sensor',
    'temperature',
    '°C',
    'active',
    5,
    'TEMPERATURE_SENSOR'
from zones
where code = 'LH01'
on conflict (code) do nothing;


-- ============================================================
-- HUMIDITY SENSOR
-- ============================================================

insert into sensors (
    zone_id,
    code,
    name,
    sensor_type,
    unit,
    status,
    sampling_interval_seconds,
    twin_model_object
)
select
    id,
    'HUM-LH01',
    'Lecture Hall Humidity Sensor',
    'humidity',
    '%',
    'active',
    5,
    'HUMIDITY_SENSOR'
from zones
where code = 'LH01'
on conflict (code) do nothing;


-- ============================================================
-- CO2 SENSOR
-- ============================================================

insert into sensors (
    zone_id,
    code,
    name,
    sensor_type,
    unit,
    status,
    sampling_interval_seconds,
    twin_model_object
)
select
    id,
    'CO2-LH01',
    'Lecture Hall CO2 Sensor',
    'co2',
    'ppm',
    'active',
    5,
    'CO2_SENSOR'
from zones
where code = 'LH01'
on conflict (code) do nothing;


-- ============================================================
-- ENERGY METER
-- ============================================================

insert into sensors (
    zone_id,
    equipment_id,
    code,
    name,
    sensor_type,
    unit,
    status,
    sampling_interval_seconds,
    twin_model_object
)
select
    z.id,
    e.id,
    'ENERGY-LH01',
    'Lecture Hall Energy Meter',
    'energy',
    'kW',
    'active',
    5,
    'ENERGY_METER'
from zones z
join equipment e
    on e.code = 'HVAC-LH01'
where z.code = 'LH01'
on conflict (code) do nothing;
