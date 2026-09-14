# Beacon API findings and export architecture

Every API call this project makes is a GET; there is no write path in the
code. Findings below are about the Beacon API itself and apply to any
account. Account-specific facts (schema shape, record volumes, editorial
findings) live in that org's own gitignored notes — see
`orgs/<slug>/FINDINGS.md` if one exists for the org you're working with.

## 1. Verified API behaviour

| Endpoint | Result |
|---|---|
| `GET /entity_types` | 200 — full schema |
| `GET /entities/{entity_type_key}` | 200 — records; `{total, results[], data_source}` |
| `GET /entities/{key}?page=N` | 200 — pagination works |
| `?limit=`, `?offset=`, `?cursor=` | ignored; page size fixed at **200** |
| `?populate=true/false` | controls the `references` array on each result |
| `?archived=true` | returns deleted records (per Beacon docs, untested) |
| `GET /users` | 200 — users (`id, role, is_deactivated, is_invited, user`) |
| `GET /entity_exports` | 200 — export job history |
| `GET /entity_export_templates` | **403** for `developer_api` |
| `GET /entity/{key}` | **403** — wrong path, use `/entities/` |
| `GET /entities?entity_type_id=…` | 504 gateway timeout — not a valid form |

Record shape: `results[] = { entity: {...}, references: [ { entity: {...} } ] }`.
The `entity` object is flat — system columns (`id, created_at, created_by_id,
created_by_type, updated_at, updated_by_id, is_archived, archived_at, is_locked,
locked_at, avatar, entity_type_id`) followed by every field keyed by field `key`.
Values are typed per field: `name` is `{full, first, middle, last, prefix}`,
`emails` is `[{email, is_primary}]`, multi-value and reference fields are arrays.

`entity_types` metadata is rich and type-specific:
- `reference` → `entity_types` (target IDs), `allow_multiple`, `fixed_entity_types`
- `select` → `options`, `fixed_options`, `allow_multiple`, `can_add_more`
- `date` → `include_time`; `currency`/`number` → `decimal_places`, `auto_increment`
- `rating` → `icon`, `color`, `maximum`; `user` → `selectable_user_ids`
- smart fields → `smart_metadata.template` (e.g. `{{{c_type}}} case note ({{{c_created_date}}})`)
- rollup fields → `rollup_metadata` with `aggregation`, `entity_type_id`,
  `reference_field_id`, `aggregate_field_id`, and full `filter_conditions`

`layout` gives grid + block field-ID ordering; `list_columns` gives default
list view columns (field IDs plus literals like `"created_at"`). The raw
schema file has a **UTF-8 BOM** — read with `encoding='utf-8-sig'`.

**Verdict:** `entity_types` is sufficient on its own to build a complete,
human-readable schema *and* relationship graph for any account. No separate
relationships endpoint is needed — every reference field names its target
entity type IDs, which join back to entity types in the same response.

Rate limits: **300 requests/min** (60/min for bulk, per Beacon's docs). 429
on breach; `beacon.py` retries with backoff.

## 2. Architecture

Scope decision: **the export describes how a CRM is configured, not what it
holds.** No records ship. That removes the entire sanitise/pseudonymise/sample
pipeline an all-records approach would need — you cannot leak a record you
never wrote.

Every script below takes `--org <slug>` and resolves its paths through
`org_context.py`; nothing here is specific to one organisation.

```
orgs/<slug>/.env.local (BEACON_API_KEY, BEACON_ACCOUNT_ID)
        │
   beacon.py --org <slug>       read-only client; method="GET" is hardcoded
        │
   build_schema.py --org <slug> ──►  orgs/<slug>/out/schema.json
        │                            orgs/<slug>/out/relationships.json
        │                            orgs/<slug>/out/attachments.json
        │
   verify_out.py --org <slug>   ──►  privacy gate; non-zero exit blocks committing
        │                            (orgs/<slug>/out/ itself is gitignored regardless —
        │                             this gate matters if you ever choose to
        │                             publish one org's export separately)
        │
   usage_report.py --org <slug> ──►  orgs/<slug>/reports/usage.json
                                     orgs/<slug>/reports/usage-summary.md
                             │
   orgs/<slug>/taxonomy.py ─────►  editorial grouping: families, money
        │                           direction, label warnings (imported by
        │                           both build_schema.py and build_report.py)
        │
   orgs/<slug>/semantics.py ────►  orgs/<slug>/out/semantics.md — what fields mean
        │
   orgs/<slug>/branding.json ───►  colours + logo, falls back to a neutral
        │                           default if absent
        │
   build_report.py --org <slug> ►  orgs/<slug>/beacon-report.html
                                    human-readable: prose, charts, interactive map
```

`usage_report.py` is deliberately separate and optional. Analytics are a
snapshot that goes stale as records are added; the architecture does not.
Mixing them would date the deliverable. `build_report.py` handles a missing
`usage.json` gracefully — an org can get a structural report before its
first usage snapshot exists.

## 3. Output files

- `orgs/<slug>/out/schema.json` — every entity type and field, with type, labels,
  help text, defaults, select options, reference targets, smart-field
  templates and resolved rollup configs. Each record type also carries an
  editorial `group`, `group_label` and `money_direction` (`in` / `out` /
  `null`), plus a `label_warning` where Beacon's label misleads; a `groups`
  block and `reading_notes` at the top explain both. These come from
  `orgs/<slug>/taxonomy.py`, the single definition shared with the report, so
  the two cannot disagree. Fields carrying special-category or free-text
  content are flagged (`special_category`, `free_text`) so a consumer knows
  the boundary without needing any values.
- `orgs/<slug>/out/relationships.json` — the reference graph, `{from, via_field,
  to, cardinality}`, derived entirely from schema metadata.
- `orgs/<slug>/out/attachments.json` — which entity types have file fields and
  which fields they are. No filenames, no counts of real attachments.
- `orgs/<slug>/out/semantics.md` — what the fields *mean*, as opposed to what they
  are: misleading labels, multi-select behaviour, which flags act as
  suppression signals, and so on. Written for reading alongside a policy
  document such as a Legitimate Interest Assessment. Editorial notes live in
  `orgs/<slug>/semantics.py`; the factual detail around them is pulled live
  from the schema, so it cannot drift.
- `orgs/<slug>/reports/usage-summary.md` — unused select options by entity type,
  and fields no record has ever filled.
- `orgs/<slug>/assets/` — that org's logo files, embedded into the report at
  build time so it stays self-contained.
- `orgs/<slug>/beacon-report.html` — the human-readable companion. Generated
  from the files above by `build_report.py`, so it cannot drift from them.
  Explains the CRM to a non-technical reader, carries an interactive
  force-directed map of every record type, and prints as an A4 digest.

## 4. Privacy model

The control is structural, not filtering: **no record value is ever written
to disk.** `usage_report.py` streams records, increments counters and
discards.

On top of that:

| Rule | Enforced by |
|---|---|
| Client cannot issue a non-GET verb | `beacon.py` self-check asserts POST/PATCH/PUT/DELETE never appear in the client source |
| Special-category fields get no value-level counts | `usage_report.py` suppresses via `is_special_category()` |
| Free-text fields get fill rate only, never a value sample | same |
| File fields never yield a filename | only the schema capability is exported |
| No field is ever dropped, only values | `verify_out.py` asserts every raw field key survives |
| `orgs/<slug>/out/` holds no email, phone or postcode | `verify_out.py` regex scan over both `.json` and `.md`, exits non-zero |

Select options are kept in full **including** on special-category fields. The
vocabulary is design; the answers are data.

## 5. Remaining unknowns

1. Whether `?archived=true` changes pagination or totals (untested).
2. Whether `populate=true` follows references more than one level deep.
3. Whether `/entity_export_templates` 403 is an application-scope limit a
   different `Beacon-Application` value would lift.
4. Field-level permission model — whether the API key sees fields a normal
   user would not.

Note items 1 and 2 no longer matter much: neither affects a schema-only export.

## 6. Running it

`python run.py` is the entry point — a wizard for a new org, straight to a
build menu for one that's already set up. See the repo README.

Each step also runs standalone, useful for scripting or debugging one stage:

```
python org_context.py                  # self-check: every orgs/<slug>/ resolves
python beacon.py --org <slug>          # self-check: read-only, schema loads
python build_schema.py --org <slug>    # no network, rebuilds orgs/<slug>/out/
python verify_out.py --org <slug>      # gate, run before ever publishing an export
python usage_report.py --org <slug>    # optional, ~60 GETs, writes orgs/<slug>/reports/
python build_report.py --org <slug>    # regenerates orgs/<slug>/beacon-report.html
```
