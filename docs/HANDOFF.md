# Handoff — Beacon CRM architecture export

Read this first if you are a fresh Claude Code session picking up this repo.

## Goal

Produce a reliable, repeatable export of a Beacon CRM account's
configuration into structured JSON files that can be handed to an AI
coding/reasoning agent, so the agent can understand the real Beacon
architecture (entity types, fields, field types and options, relationships,
smart fields, rollups) — **without receiving personal or confidential data,
and without any organisation's identity or credentials living in this repo.**

Hard requirement: **the export must never remove fields.** If a Beacon
account has a Person entity with a `name` field, the export keeps that field
with its type, label and settings, and carries no value for it. The AI must
know the field exists, its type, and its purpose.

Scope: **no record values ship at all.** The deliverable describes how a CRM
is customised, not what it contains — so there is nothing to sanitise,
because nothing is written. Record analytics are a separate, optional,
per-org, gitignored report (`orgs/<slug>/reports/`).

The output must be materially more useful to an AI than a folder of cleaned
CSVs.

## Multi-org design

This tool is meant to work against any Beacon account, and to eventually be
public. That means nothing about a specific organisation — its name, colours,
logo, account ID, credentials, or editorial knowledge of its own schema —
lives in a tracked file. All of it lives under `orgs/<slug>/`, which is
entirely gitignored except `orgs/README.md` (the documented shape). Generated
output (`orgs/<slug>/`) is gitignored too.

See `orgs/README.md` for the folder shape and how to add an organisation, and
`ARCHITECTURE.md` for the pipeline diagram.

## Decisions already made

- **Zapier is out.** The Zapier Beacon integration acts on workflow-exposed
  events; it is not a general-purpose extraction path. We go direct to the
  REST API.
- Schema and record data are treated as two separate concerns with separate
  pipelines and separate output files.
- **No records ship at all.** The deliverable describes how a CRM is
  customised, not what it contains. This removed the planned
  sanitisation/sampling pipeline entirely.
- **Strictly read-only. No exceptions, ever.** No POST, PATCH, PUT or DELETE
  against Beacon under any circumstances. `beacon.py` hardcodes GET and its
  self-check fails if any other verb appears in the client source.
- **Nothing org-specific is ever committed.** Credentials, raw schema,
  branding, taxonomy, semantics content and every generated output all live
  under `orgs/<slug>/` (all gitignored, except `orgs/README.md`).
  `verify_out.py`'s privacy gate still matters if you ever choose to publish
  one org's export separately from this repo.
- `orgs/<slug>/beacon-report.html` is the human-readable companion, generated
  by `build_report.py`. Regenerate it whenever that org's `out/` or
  `reports/` (both under `orgs/<slug>/`) change.
- Record-type grouping (families, money direction, label warnings) lives in
  `orgs/<slug>/taxonomy.py` and is imported by both `build_schema.py` and
  `build_report.py`. Change it there, never in either builder, then rerun
  both so `orgs/<slug>/out/schema.json` and the report stay in step.
- To refresh an org's schema from Beacon (read-only), delete
  `orgs/<slug>/beacon-schema-raw.json` and run `run.py --org <slug>` again —
  it re-fetches the schema automatically when that file is missing, then
  offers to rebuild. Doing it by hand: re-fetch `entity_types` via
  `beacon.get("entity_types")` (after `beacon.set_org(slug)`), write it to
  `orgs/<slug>/beacon-schema-raw.json`, then run `build_schema.py`,
  `verify_out.py` and `build_report.py` in that order, all with `--org
  <slug>`. Forgetting `build_schema.py` leaves `orgs/<slug>/out/` stale.

## What has been verified against the live API

See `ARCHITECTURE.md` for the full detail (endpoint behaviour, pagination,
rate limits) — none of it is account-specific.

## What the deliverable is for

The target use is: hand an AI assistant (1) the contents of `orgs/<slug>/out/`,
(2) a link to Beacon's API documentation, and (3) a policy document such as a
Legitimate Interest Assessment — and have it design a Beacon filter selecting
the records that satisfy that policy, or report where the policy assumes a
distinction Beacon does not record.

Two things that scenario needs, which the schema alone cannot supply:

- **Filter syntax and operators** — not in `orgs/<slug>/out/`; they come from
  Beacon's documentation at https://beacon-crm-api.notion.site/api-filtering
- **What fields mean in practice** — `orgs/<slug>/out/semantics.md`, generated
  from `orgs/<slug>/semantics.py`. Extend the notes there when a field's
  meaning turns out to be non-obvious.

Beacon records no lawful basis. Any lawful-basis judgement comes from reading
these fields against the policy document, never from a field in the CRM.
Where policy and configuration disagree, that mismatch is itself a finding.

Filters should cover every declared select option relevant to the question,
not only options that currently have records behind them — an unused option
may be applied at any time. `orgs/<slug>/reports/` shows current usage and informs
tidying decisions; it should not narrow a filter.

## Reference

- API overview and rate limits: https://guide.beaconcrm.org/en/articles/5720215-beacon-s-api
- Exporting via the API (CSV export templates): https://guide.beaconcrm.org/en/articles/12539278-exporting-via-the-api
- Filtering: https://beacon-crm-api.notion.site/api-filtering
- Field type validation: https://beacon-crm-api.notion.site/field-type-validation
- Per-account generated docs (login required): https://developers.beaconcrm.org/
