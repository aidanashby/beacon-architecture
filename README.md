# beacon-architecture

Exports a Beacon CRM account's *configuration* — not its records — into
structured JSON that an AI coding/reasoning agent can consume safely, plus a
human-readable HTML report with an interactive map of every record type.

Works against any [Beacon CRM](https://beaconcrm.org/) account. Nothing
organisation-specific lives in this repo: credentials, branding, editorial
groupings and every generated output all live under `orgs/<slug>/`, which is
entirely gitignored — clone this and it's blank until you run the wizard.

**Requirements:** Python 3.9+. No dependencies — everything here is the
standard library.

## Running it

On Windows, double-click `run.cmd`. Otherwise:

```
python run.py
```

That's the only command you need. It's a wizard: for a new organisation it
asks for a display name and branding (colours, logo URLs — skip anything and
it falls back to a neutral default), creates `orgs/<slug>/.env.local` with
empty placeholders, and tells you where to add the real API key. Run it
again once the key's in and it fetches the schema and offers to build the
export and report. For an organisation that's already set up, it skips
straight to that — rebuild the schema, regenerate the report, or both.

See [`orgs/README.md`](orgs/README.md) if you want to understand or hand-edit
what the wizard creates.

The export describes how the CRM is configured, not what it holds: entity
types, fields, select vocabularies, the reference graph, smart-field
formulas, rollup configs, and which types accept file attachments. No record
values, ever.

- [`CHANGELOG.md`](CHANGELOG.md) — notable changes to this tool
- [`docs/HANDOFF.md`](docs/HANDOFF.md) — everything a fresh Claude Code session needs to pick this up
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — verified API behaviour, the pipeline as built, and the privacy model
- [`docs/process.html`](docs/process.html) — the pipeline as a diagram: actions, outputs, the privacy gate
- [`orgs/README.md`](orgs/README.md) — the shape of an `orgs/<slug>/` folder and what each generated file is
- `orgs/<slug>/beacon-report.html` — **the human-readable report** for one org. How its CRM
  is put together, with an interactive map of every record type. Prints to A4. Standalone —
  safe to send to someone with no access to this repo.
- `orgs/<slug>/out/` — **the machine-readable deliverable** for one org. `schema.json`,
  `relationships.json`, `attachments.json`, and `semantics.md` (what the fields mean in practice)
- `orgs/<slug>/reports/` — record counts and option usage for one org. A snapshot; regenerate when it matters.

`run.py` calls the individual scripts below in order; each also runs
standalone with `--org <slug>` (or prompts if you omit it) if you want one
step in isolation:

```
python build_schema.py --org <slug>    # no network; rebuilds orgs/<slug>/out/ from the raw schema
python verify_out.py --org <slug>      # privacy gate; non-zero exit means do not commit
python usage_report.py --org <slug>    # optional; ~60 GETs, writes orgs/<slug>/reports/
python build_report.py --org <slug>    # regenerates orgs/<slug>/beacon-report.html
```

## Security

**This project is strictly read-only against Beacon.** `beacon.py` hardcodes
`method="GET"` and its self-check fails if the strings POST, PATCH, PUT or
DELETE appear in the client source. There is no write path. Do not add one.

No API key is stored in this repo. Each org's key lives in
`orgs/<slug>/.env.local` (gitignored). Never commit keys, never write them
into generated JSON, never print them in logs. No record value is ever
written to disk by any script here.

## License

[MIT](LICENSE)
