# Vision Persistence Activation Checklist

Canonical operator runbook for applying
`backend/migrations/003_vision_observations.sql` and performing
the first controlled, real-database vision persistence test.

**Status: NOT EXECUTED.** No database has ever been contacted
by the development of this feature. Everything below is a plan
for a human operator to review and, separately, approve.

Every SQL statement in this document is a **future operator
action**. None of it was executed while writing this file. The
development environment has no database connection.

---

## Intended test parameters

| Parameter | Value |
| --- | --- |
| Zone | `LH01` (University Lecture Hall, capacity 60, seeded by `002`) |
| Model | `yolo11n.pt` |
| Confidence threshold | `0.45` |
| IoU threshold | `0.50` |
| Person class | COCO `0` |
| Test image | Public-domain Wikimedia image only. No real personal imagery |
| Reference result | 2 people, aggregate confidence ≈ `0.82384` |

> The reference result is a **reference, not a contract**.
> It was measured on one machine with one copy of the weights.
> A different environment may legitimately produce a different
> confidence. Record the actual value; do **not** fail the test
> on a mismatch, and do **not** change thresholds to force a
> match.

---

## A. Scope, environment and operator approval

- [ ] **A1.** Identify the intended **non-production** Supabase
      project. Record its dashboard **reference name** only.
      Never paste the project URL into a terminal, ticket or
      chat.
- [ ] **A2.** Confirm this is the correct project for a test.
      If there is any doubt about whether it is production,
      stop.
- [ ] **A3.** Confirm `VISION_ENABLED=true`. When it is false,
      `include_vision_router()` in `app/main.py` never imports
      the vision router, so `/api/v1/vision/analyze`,
      `/api/v1/vision/status` and
      `/api/v1/vision/zone/{zone_code}/latest` are **not
      registered** and will answer `404`. A `404` from those
      routes means the feature is switched off, not that it is
      broken.
- [ ] **A4.** Confirm `MQTT_ENABLED=false`. See **R7** below —
      this setting alone does not prove no other process can
      write.
- [ ] **A5.** Confirm the backend is started **from the
      `backend/` directory**. `app/core/config.py` sets
      `env_file=".env"`, a working-directory-relative path. Run
      from elsewhere and the config will not be found.
- [ ] **A6.** Confirm `backend/vision/weights/yolo11n.pt`
      exists. It is gitignored (`.gitignore` rule for
      `backend/vision/weights/`), so a fresh clone will not have
      it and the detector will report unavailable.
- [ ] **A7.** Confirm no other backend or test process is bound
      to the port. See section **R7**.
- [ ] **A8.** **Explicit, recorded operator approval to apply
      migration 003.** Stop here until this exists.

---

## B. Credential verification without exposing secrets

The application reads its credential from the settings named
`supabase_url` and `supabase_service_role_key`
(`app/core/config.py`), and passes it to `create_client()` in
`app/db/supabase.py`. **Only the setting names are relevant to
this checklist. No value belongs in this document, in a
terminal transcript, or in any ticket.**

- [ ] **B1.** In the Supabase dashboard, open the confirmed
      project's **API Keys** page and read the **role name**
      shown next to the configured key. Confirm it is
      **service_role**, not `anon` / publishable. Record the role
      name, not the key.
- [ ] **B2.** If the configured value is a JWT, inspect its
      **`role` claim** in the dashboard viewer. Do not decode or
      echo it in a shell.
- [ ] **B3.** Never run `echo $SUPABASE_SERVICE_ROLE_KEY`,
      `cat backend/.env`, or paste the value into a terminal,
      ticket, commit or chat message.
- [ ] **B4.** Confirm the key is **not** exposed to the
      frontend. The frontend declares exactly one environment
      variable, `NEXT_PUBLIC_API_URL`, and the only
      `NEXT_PUBLIC_` reference in frontend source is the API
      base URL in `frontend/lib/api.ts`. Any `SUPABASE_*` or
      `SERVICE_ROLE` value in frontend code or in a
      `NEXT_PUBLIC_*` variable is a stop condition.
- [ ] **B5.** Understand that **a successful backend start
      proves nothing about the credential.**
      `app/db/supabase.py` builds a client at import time, so
      startup validates only that the URL is well-formed. The
      `supabase` library does not connect on construction, so a
      wrong or under-privileged key still starts cleanly and
      fails later, at the first query.

> **Do not switch credentials to make an authorization failure
> pass.** If an insert is denied, that is the credential check
> working as designed. Stop and escalate.

---

## C. Read-only pre-migration checks

Run in the Supabase SQL editor. **All queries below are
operator actions and have not been executed.**

### C1 — the `zones` table exists (proves `001` applied)

```sql
-- OPERATOR ACTION — NOT EXECUTED
select to_regclass('public.zones') as zones_table;
```

- **Expected:** one row, `zones_table = zones`.
- **If NULL:** migration `001` has not been applied. `003`
  depends on `zones`. **Stop** and apply `001` first, under its
  own approval.

### C2 — the `pgcrypto` extension exists (proves `001` applied)

```sql
-- OPERATOR ACTION — NOT EXECUTED
select extname from pg_extension where extname = 'pgcrypto';
```

- **Expected:** exactly one row.
- **If empty:** `003` calls `gen_random_uuid()`, which needs
  this extension. **Stop.** Re-apply `001` (it is written with
  `create extension if not exists`).

### C3 — the seeded `LH01` zone exists (proves `002` applied)

```sql
-- OPERATOR ACTION — NOT EXECUTED
select code, name, zone_type, capacity
from public.zones
where code = 'LH01';
```

- **Expected:** exactly one row —
  `LH01 | University Lecture Hall | lecture_hall | 60`.
- **If empty:** migration `002` has not been applied, or the
  seed failed. The test targets this zone specifically.
  **Stop** and apply `002` first.

### C4 — `vision_observations` does not yet exist

```sql
-- OPERATOR ACTION — NOT EXECUTED
select to_regclass('public.vision_observations') as vision_table;
```

- **Expected:** one row, `vision_table` is **NULL**. Migration
  003 has not been applied.
- **If it returns a table name:** `003` has already been
  applied. Do **not** re-apply and do **not** assume the
  definition is correct — `create table if not exists` skips
  silently and will not repair drift. **Stop** and inspect the
  existing table against section F before doing anything.

---

## D. Migration 003 review and explicit approval gate

- [ ] **D1.** Read `backend/migrations/003_vision_observations.sql`
      in full (108 lines).
- [ ] **D2.** Confirm it performs exactly four operations:
      1. `create table if not exists vision_observations`
      2. `create index if not exists idx_vision_zone_observed`
      3. `create index if not exists idx_vision_camera_observed`
      4. `alter table vision_observations enable row level security`
- [ ] **D3.** Confirm it touches no other table, creates no
      policy, and issues no `GRANT`.
- [ ] **D4.** Confirm `confidence` is `numeric(6,5)` with a
      `between 0 and 1` check.
- [ ] **D5.** Confirm the dependency order: `003` needs `001`
      (for `pgcrypto` and `zones`) and `002` (for the `LH01`
      seed). It is **not** standalone-safe.
- [ ] **D6.** **Approval gate.** Record explicit approval to
      apply. **Stop here until it exists.**

---

## E. Manual migration application

- [ ] **E1.** Open the Supabase SQL editor for the project
      confirmed in A1.
- [ ] **E2.** Paste the full contents of
      `backend/migrations/003_vision_observations.sql`
      verbatim.
- [ ] **E3.** Execute **once**. Record the timestamp and any
      notices.
- [ ] **E4.** Do **not** re-run to "correct" anything. Every
      statement is guarded by `IF NOT EXISTS` or is idempotent,
      so a second run reports success while changing nothing.
      If the definition is wrong, it needs an explicit
      `alter table` or a drop-and-recreate — see section J.

---

## F. Read-only post-migration verification

**Operator actions. Not executed.**

### F1 — the table now exists

```sql
-- OPERATOR ACTION — NOT EXECUTED
select to_regclass('public.vision_observations') as vision_table;
```

- **Expected:** one row, `vision_table =
  vision_observations`.
- **If NULL:** the migration did not apply. Stop and read the
  editor's error output.

### F2 — column types

```sql
-- OPERATOR ACTION — NOT EXECUTED
select column_name, data_type, numeric_precision, numeric_scale,
       is_nullable, column_default
from information_schema.columns
where table_schema = 'public'
  and table_name = 'vision_observations'
order by ordinal_position;
```

- **Expected:** ten columns —
  `id` (uuid), `camera_id` (text), `zone_code` (text),
  `observation_type` (text), `value` (integer), `unit` (text),
  `confidence` (numeric, precision **6**, scale **5**),
  `observed_at` (timestamp with time zone), `evidence` (jsonb),
  `created_at` (timestamp with time zone).
- **If `confidence` shows precision 4 / scale 4:** the table
  predates the precision fix. **Stop** — the stored value will
  disagree visibly with the API response.

### F3 — indexes

```sql
-- OPERATOR ACTION — NOT EXECUTED
select indexname, indexdef
from pg_indexes
where schemaname = 'public'
  and tablename = 'vision_observations'
order by indexname;
```

- **Expected:** `idx_vision_zone_observed` on
  `(zone_code, observed_at DESC)` and
  `idx_vision_camera_observed` on
  `(camera_id, observed_at DESC)`, plus the primary-key index.
- **If a query index is missing:** re-running `003` will create
  it safely. That is the one repair a re-run genuinely fixes.

### F4 — row level security

```sql
-- OPERATOR ACTION — NOT EXECUTED
select relrowsecurity, relforcerowsecurity
from pg_class
where oid = 'public.vision_observations'::regclass;
```

- **Expected:** `relrowsecurity = true`.

```sql
-- OPERATOR ACTION — NOT EXECUTED
select count(*) as policy_count
from pg_policies
where schemaname = 'public'
  and tablename = 'vision_observations';
```

- **Expected:** `policy_count = 0`.

> **Zero policies is intentional.** The backend reads and writes
> with a **service_role** key, which carries `BYPASSRLS`, so it
> is unaffected by RLS. Meanwhile `anon` and `authenticated`
> are denied everything, which keeps observation data — imagery
> derived information about people in a space — off the public
> PostgREST surface. Adding a policy, or a `GRANT`, would change
> that posture and is out of scope for this test.

### F5 — the zone foreign key

```sql
-- OPERATOR ACTION — NOT EXECUTED
select
    con.conname,
    pg_get_constraintdef(con.oid) as definition
from pg_constraint con
join pg_class rel on rel.oid = con.conrelid
join pg_namespace nsp on nsp.oid = rel.relnamespace
where nsp.nspname = 'public'
  and rel.relname = 'vision_observations'
  and con.contype = 'f';
```

- **Expected:** exactly one row, a foreign key whose
  definition references `zones(code)` with
  `ON DELETE CASCADE`.
- **If no foreign key exists, or it points somewhere else:** the
  zone reference is not enforced, so an observation could name a
  zone that does not exist. **Stop and investigate before any
  activation.**

### F6 — privileges

```sql
-- OPERATOR ACTION — NOT EXECUTED
select grantee, privilege_type
from information_schema.role_table_grants
where table_schema = 'public'
  and table_name = 'vision_observations'
  and grantee in ('anon', 'authenticated')
order by grantee, privilege_type;
```

- **Expected:** **zero rows.** No privileges for `anon` or
  `authenticated`.
- **If any row appears:** the table is reachable by a public
  role. **Stop** and investigate.

---

## G. One controlled image-to-database round-trip

### G0 — Readiness (no database access)

- [ ] **G1.** Start the backend bound to **localhost only**.
      Do not expose the port beyond the local machine.
- [ ] **G2.** `GET /health`. Expected `vision` block when
      enabled:

      ```json
      {
        "enabled": true,
        "routes_registered": true,
        "detector_available": true,
        "model_name": "yolo11n.pt"
      }
      ```

      When the feature is switched off:

      ```json
      {
        "enabled": false,
        "routes_registered": false,
        "detector_available": false,
        "detail": "Vision is disabled by VISION_ENABLED=false. ..."
      }
      ```

      `/health` never contains the database URL, host or any
      credential. It is safe to paste into a report.

- [ ] **G3.** `GET /api/v1/vision/status`. Expect
      `confidence_threshold = 0.45`, `iou_threshold = 0.50`,
      `model_name = yolo11n.pt`, `observation_type =
      people_count`.
      A `404` here means `VISION_ENABLED=false` (A3), not a
      fault.

### G1 — Record the starting state

```sql
-- OPERATOR ACTION — NOT EXECUTED
select count(*) as observations_before
from public.vision_observations;
```

- **Expected:** `0` on a clean project. Record the actual value
  either way; it is your baseline.

### G2 — Exactly one POST

> **One POST only. See R4 below — repeating the request is not
> idempotent and will create additional rows.**

- [ ] **G4.** `POST /api/v1/vision/analyze` **once**, with the
      public-domain test image, `zone_code=LH01`, and a
      `camera_id` you will recognise as a test value.
- [ ] **G5.** Expect **HTTP 200** and `people_count = 2`.
      Aggregate confidence should be near `0.82384`; record the
      actual value. It may differ.
- [ ] **G6.** `GET /api/v1/vision/zone/LH01/latest`. Expect
      `value = 2`, `zone_code = LH01`, non-empty `evidence`,
      and `observed_at` close to now in UTC.

### G3 — Confirm it is genuinely in the database

```sql
-- OPERATOR ACTION — NOT EXECUTED
select id, camera_id, zone_code, observation_type, value, unit,
       confidence, observed_at, jsonb_array_length(evidence) as evidence_items
from public.vision_observations
order by created_at desc
limit 5;
```

- **Expected:** exactly one row matching the API response.
  `value = 2`, the `zone_code` you sent, and `observed_at`
  within a minute or two of now.
- **If nothing appears:** the insert did not persist. Do not
  retry blindly — capture the HTTP status and body first, and go
  to section H.
- **If more than one row appeared:** more than one POST was
  sent. See R4.

- [ ] **G7.** Confirm the count increased by exactly one:

```sql
-- OPERATOR ACTION — NOT EXECUTED
select count(*) as observations_after
from public.vision_observations;
```

- **Expected:** `observations_before + 1`.

### G4 — Timestamp and zone correctness

- [ ] **G8.** `observed_at` is stored in `timestamptz`. Confirm
      it is recent and unambiguous in UTC. The API returns an
      ISO-8601 timestamp with a `+00:00` offset; a naive
      timestamp is normalised to UTC before it is written.
- [ ] **G9.** `zone_code` is the exact code you submitted.
      Because the column is constrained to `zones(code)`, an
      unknown zone would have been rejected at insert time
      rather than stored.

---

## H. Validation failures and safe error reporting

- [ ] **H1.** Unknown zone → expect **404**. The body names the
      zone and nothing else.
- [ ] **H2.** Unsupported upload type → expect **415**.
- [ ] **H3.** Oversized upload → expect **413**.
- [ ] **H4.** Model weights absent → expect **503**. This is a
      configuration problem, not a transient fault; retrying
      will not help.
- [ ] **H5.** Persistence or unexpected fault → expect **500**
      with the fixed body:

      ```
      Vision processing failed. Nothing was recorded.
      ```

- [ ] **H6.** Inspect every response body you captured. It must
      contain **no** database hostname, port, connection string,
      SQL fragment or key fragment. Server-side detail is logged
      for the operator and is deliberately not returned to
      clients.
- [ ] **H7.** **A denied insert is a valid, informative
      outcome.** It means the credential is not sufficiently
      privileged under the zero-policy RLS posture. Record it as
      a **blocked activation** and stop. Do **not** work around
      it by switching keys, adding a policy, or granting
      privileges.

---

## I. Test-row identification and optional cleanup

Cleanup is **optional** and requires its own approval. Nothing
below has been executed.

- [ ] **I1.** Record the `id` of the row created by this test,
      taken from the G3 query.
- [ ] **I2.** Re-read that row by `id` and confirm every field
      matches what was submitted: `camera_id`, `zone_code`,
      `value`, `confidence`, `observed_at`.

```sql
-- OPERATOR ACTION — NOT EXECUTED
select * from public.vision_observations where id = '<recorded-id>';
```

- **If the row cannot be identified confidently: STOP AND
  ESCALATE. Do not attempt cleanup.**

- [ ] **I3.** If cleanup is approved, delete **only** that one
  recorded id:

```sql
-- OPERATOR ACTION — NOT EXECUTED — REQUIRES SEPARATE APPROVAL
delete from public.vision_observations where id = '<recorded-id>';
```

  **Never** use a blanket `delete from vision_observations`,
  and never use a predicate that could match more than the one
  recorded row.

- [ ] **I4.** Never delete or modify `zones`, `sensors`,
      `telemetry_readings`, `incidents`, or any observation not
      created by this test.
- [ ] **I5.** Remember the cascade: `vision_observations.zone_code`
      has `ON DELETE CASCADE` from `zones(code)`. Deleting zone
      `LH01` destroys every observation recorded for it.
- [ ] **I6.** If the row is kept deliberately, record that
      decision — `vision_observations` currently has **no
      retention policy** and no TTL.

---

## J. Stop conditions, evidence recording, and go/no-go

### J1 — Stop conditions. Do not proceed if any of these hold.

- The target project cannot be confirmed as non-production.
- Any check in sections C, D or F fails.
- The credential cannot be confirmed as `service_role` by
  inspection.
- `confidence` is `numeric(5,4)`, or the foreign key is absent.
- Any privilege exists for `anon` or `authenticated`.
- A service-role key or project URL appears in frontend code or
  in any `NEXT_PUBLIC_*` variable.
- An insert is denied by authorization.
- More than one row is created by a single POST.

### J2 — Evidence to record

- Project reference name (not URL) and timestamp.
- Results of every query in sections C, F, G3 and G4.
- HTTP status and body for each request in sections G and H,
  with any credential-like text redacted before it is shared.
- The `id` of the created row, and the cleanup decision.
- Actual `people_count` and `confidence` observed, recorded as
  observed — not as the reference value.

### J3 — Go/no-go decision

Record one of:

- **GO** — table applied and verified, one observation persisted
  and read back consistently.
- **BLOCKED** — a stop condition was hit. Record which one. The
  schema may be applied or unapplied; state which.
- **NO-GO** — do not activate.

### J4 — Production deployment remains blocked

Passing this checklist proves the pipeline can persist one row.
It does **not** make the feature production-ready. The following
remain unresolved and must be addressed before any public
exposure:

1. **Authentication.** `POST /api/v1/vision/analyze` has no
   authentication, and there is none anywhere in the backend.
   Anyone who can reach the port can write observation rows.
2. **Retention.** No TTL or purge policy. Bounding boxes derived
   from imagery of identifiable people persist indefinitely.
3. **Rate limiting.** None. An exposed endpoint can be written to
   without bound.
4. **`camera_id` is free text**, not a registered entity. Any
   caller may claim any camera label; there is no ownership or
   authorization boundary.
5. **Cascade data loss.** Deleting a zone destroys its
   observations.
6. **Error disclosure elsewhere.** The same raw-exception
   pattern that was fixed in the Phase 7 vision module remains in
   `app/api/campus.py` and `app/api/incidents.py`.

---

## R1 — Verify migrations 001 and 002 explicitly

Covered by **C1** (zones table), **C2** (`pgcrypto` extension),
**C3** (seeded `LH01` with its code, name, type and capacity)
and **C4** (absence of `vision_observations`). Each query states
its expected result and the required response on failure.

## R2 — Account for the vision feature toggle

Covered by **A3**, **G2** and **G3**. When `VISION_ENABLED=false`
the vision router is never imported, so all three vision routes
return `404`. A `404` must be read as "feature off", not
"feature broken". The authoritative signal is the
`vision.enabled` field on `/health`.

## R3 — Correct health response expectations

Covered by **G2**, using the Phase 7G contract:
`vision.enabled`, `vision.routes_registered`,
`vision.detector_available`, plus `model_name` when enabled and
a `detail` string when disabled. `/health` contains no database
URL, host or credential, and must never be edited to add one.

## R4 — The deduplication limitation

Phase 7H added an idempotent write that reuses an existing row
with the same `(camera_id, zone_code, observed_at)`. It
activates **only when the caller supplies `observed_at`
internally**. The current HTTP endpoint does not accept or send
that value, so **every POST creates a new row**.

Therefore: send **exactly one** POST (G4). Do not retry. Do not
assume HTTP retries are idempotent. If a retry is unavoidable,
count the extra rows in section G3 and account for them in
cleanup.

## R5 — Precise cleanup

Covered by section **I**: record the id, verify the exact row and
project, delete only that id under separate approval, never a
blanket delete, never touching zones, sensors, telemetry
readings, incidents or unrelated observations, and escalate if
the row cannot be identified confidently.

## R6 — Verify the foreign key

Covered by **F5**: a read-only `pg_constraint` query expecting
exactly one foreign key to `zones(code)` with `ON DELETE
CASCADE`. A missing or different constraint blocks activation
pending investigation.

## R7 — Check for concurrent database writers

- **A7** requires confirming no other backend or test process is
  bound to the port.
- **A4** requires `MQTT_ENABLED=false`, and **G1** requires
  localhost-only binding.

**Important:** disabling MQTT in one process does **not** prove
that nothing else can write to the database. Another backend
instance, a scheduled job, another developer's script, or a
direct SQL session in the editor can all write concurrently.
Before the test, confirm that no other writer is active — in
particular that no telemetry worker is running, since it writes
to `telemetry_readings` every flush cycle. After the test,
re-run the counts in G1 and G3 to confirm exactly one row was
added by exactly one POST.
