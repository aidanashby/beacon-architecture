"""Which organisation a build script runs for, and where its files live.

Everything for one org — credentials, raw schema, taxonomy, semantics,
branding, logos, and every generated output — lives under orgs/<slug>/. That
keeps one gitignore rule (orgs/*) covering all of it, inputs and outputs
alike. This module is the single place that knows those paths, so nothing
else hardcodes a specific org's slug or the "orgs/" prefix.
"""

from pathlib import Path

ROOT = Path(__file__).parent
ORGS_DIR = ROOT / "orgs"


def discover_orgs():
    """Every orgs/<slug>/ directory, sorted."""
    if not ORGS_DIR.exists():
        return []
    return sorted(p.name for p in ORGS_DIR.iterdir() if p.is_dir())


def select_org(cli_value):
    """Validate an --org value, or prompt with a numbered list if None."""
    orgs = discover_orgs()
    if not orgs:
        raise SystemExit(f"No orgs found under {ORGS_DIR}. Create orgs/<slug>/ first.")

    if cli_value:
        if cli_value not in orgs:
            raise SystemExit(f"Unknown org {cli_value!r}. Available: {', '.join(orgs)}")
        return cli_value

    if len(orgs) == 1:
        return orgs[0]

    print("Which organisation?")
    for i, org in enumerate(orgs, 1):
        print(f"  {i}. {org}")
    choice = input(f"Enter a number or name [1-{len(orgs)}]: ").strip()
    if choice in orgs:
        return choice
    try:
        return orgs[int(choice) - 1]
    except (ValueError, IndexError):
        raise SystemExit(f"Invalid choice: {choice!r}")


def org_paths(org):
    """All the paths a build script needs for this org."""
    org_dir = ORGS_DIR / org
    return {
        "org_dir": org_dir,
        "env_file": org_dir / ".env.local",
        "raw_schema": org_dir / "beacon-schema-raw.json",
        "assets_dir": org_dir / "assets",
        "branding_file": org_dir / "branding.json",
        "out_dir": org_dir / "out",
        "reports_dir": org_dir / "reports",
        "report_target": org_dir / "beacon-report.html",
    }


if __name__ == "__main__":
    orgs = discover_orgs()
    assert orgs, "expected at least one org under orgs/"
    for org in orgs:
        paths = org_paths(org)
        assert paths["org_dir"].is_dir(), f"{org}: org_dir missing"
    print(f"ok: {len(orgs)} org(s) found: {', '.join(orgs)}")
