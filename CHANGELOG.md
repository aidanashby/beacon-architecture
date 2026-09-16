# Changelog

All notable changes to this project are documented here.

## Unreleased

### Fixed
- Branding wizard (`run.py`) now adds a leading `#` to a hex colour typed
  without one, so `primary`/`secondary` always land in `branding.json` as
  valid CSS colours instead of silently falling back to the default.

## 2026-09-14 — Initial public release

Multi-org Beacon CRM architecture exporter. Exports a Beacon account's
*configuration* — entity types, fields, relationships, smart fields, rollups
— into structured JSON an AI agent can read safely, plus a standalone HTML
report. No record values ever ship. Strictly read-only against the Beacon
API. Nothing organisation-specific is tracked in the repo; per-org
credentials, branding and editorial knowledge live in a gitignored
`orgs/<slug>/` created by an interactive setup wizard (`run.py`).
