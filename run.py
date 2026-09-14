"""Single entry point. Run this — nothing else — to set up or build an org.

python run.py [--org <slug>]

New organisation: walks you through creating orgs/<slug>/ (branding, an
.env.local with placeholders for your API key, taxonomy/semantics stubs),
tells you where to add the real key, and stops there.

Existing, fully set up organisation: asks what you want to do (rebuild the
schema export, regenerate the report, run the optional usage report, or all
of it) and does it — the same steps build_schema.py/verify_out.py/
usage_report.py/build_report.py perform individually, in the right order.
"""

import json
import re

import beacon
import build_report
import build_schema
import org_context
import usage_report
import verify_out

STUB_TAXONOMY = '''"""Editorial grouping of {name}'s Beacon record types.

Stub: no groupings written yet. Everything falls into "admin" (the
catch-all) until this is filled in from the account's actual entity types —
see orgs/README.md for the shape to follow.
"""

GROUPS = {{
    "admin": {{
        "label": "All record types",
        "colour": "#33475b",
        "money_direction": None,
        "note": "Ungrouped — taxonomy not written yet.",
    }},
}}

MEMBERSHIP = {{}}
PENDING_SOON = {{}}
LABEL_WARNINGS = {{}}


def group_of(key):
    return MEMBERSHIP.get(key, "admin")


def money_direction(key):
    return GROUPS[group_of(key)]["money_direction"]


if __name__ == "__main__":
    unknown = {{g for g in MEMBERSHIP.values()}} - set(GROUPS)
    assert not unknown, f"unknown groups: {{unknown}}"
    print(f"ok: {{len(GROUPS)}} groups, {{len(MEMBERSHIP)}} record types mapped, "
          f"{{len(LABEL_WARNINGS)}} label warnings")
'''

STUB_SEMANTICS = '''"""Editorial notes on what Beacon fields mean in practice, for {name}.

Stub: no field/type notes written yet. See orgs/README.md for the shape to
follow once the account's fields are known.
"""

import json

FIELD_NOTES = {{}}
TYPE_NOTES = {{}}

INTRO = """# What the fields mean

Companion to `schema.json`. This file says what a field is **for**, where a
label misleads, and which conventions a reader would otherwise have to guess.
Not written yet for this account.
"""


def render(entity_types):
    return INTRO


if __name__ == "__main__":
    import pathlib
    schema = json.loads((pathlib.Path(__file__).parent / "out" / "schema.json")
                        .read_text(encoding="utf-8"))
    keys = {{t["key"] for t in schema["entity_types"]}}
    for tk, fk in FIELD_NOTES:
        assert tk in keys, f"unknown record type in FIELD_NOTES: {{tk}}"
    for tk in TYPE_NOTES:
        assert tk in keys, f"unknown record type in TYPE_NOTES: {{tk}}"
    print(f"ok: {{len(FIELD_NOTES)}} field notes, {{len(TYPE_NOTES)}} type notes")
'''


def slugify(text):
    """Whatever the user typed, turned into a safe folder name — lowercase,
    hyphens instead of spaces/underscores, nothing else."""
    text = re.sub(r"[\s_]+", "-", text.strip().lower())
    return re.sub(r"[^a-z0-9-]", "", text).strip("-")


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val or default


def has_real_credentials(org):
    path = org_context.org_paths(org)["env_file"]
    if not path.exists():
        return False
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return bool(env.get("BEACON_API_KEY")) and bool(env.get("BEACON_ACCOUNT_ID"))


def pick_org(cli_org):
    orgs = org_context.discover_orgs()
    if cli_org:
        return cli_org, cli_org not in orgs

    if not orgs:
        print("No organisations set up yet.")
        return slugify(ask('Short name for it, lowercase with hyphens instead of spaces (e.g. "charity-name")')), True

    print("Which organisation?")
    for i, o in enumerate(orgs, 1):
        print(f"  {i}. {o}")
    print(f"  {len(orgs) + 1}. Set up a new organisation")
    choice = input(f"Enter a number, an existing name, or a new one "
                    f'(lowercase, hyphens instead of spaces, e.g. "charity-name"): ').strip()
    if choice in orgs:
        return choice, False
    if choice.isdigit():
        n = int(choice)
        if 1 <= n <= len(orgs):
            return orgs[n - 1], False
        if n == len(orgs) + 1:
            return slugify(ask('New organisation name, lowercase with hyphens instead of spaces (e.g. "charity-name")')), True
    slug = slugify(choice)
    return slug, slug not in orgs


def setup_org(slug, is_new):
    paths = org_context.org_paths(slug)

    if is_new:
        name = ask("Organisation display name", slug.replace("-", " ").title())
        paths["org_dir"].mkdir(parents=True, exist_ok=True)
        paths["assets_dir"].mkdir(exist_ok=True)
        print(f"Created orgs/{slug}/")
    else:
        name = slug

    if not paths["env_file"].exists():
        paths["env_file"].write_text("BEACON_API_KEY=\nBEACON_ACCOUNT_ID=\n", encoding="utf-8")
        print(f"Created {paths['env_file']} with empty placeholders.")

    if not paths["branding_file"].exists():
        print(f"\nBranding for {name} — press Enter to skip any and use a neutral default:")
        branding = {"name": name}
        primary = ask("  Primary colour (hex)")
        secondary = ask("  Secondary/accent colour (hex)")
        logo_white = ask("  Logo URL for dark backgrounds (blank if none)")
        logo_purple = ask("  Logo URL for print/light backgrounds (blank if none)")
        if primary:
            branding["primary"] = primary
        if secondary:
            branding["secondary"] = secondary
        if logo_white:
            branding["logo_white"] = logo_white
        if logo_purple:
            branding["logo_purple"] = logo_purple
        paths["branding_file"].write_text(json.dumps(branding, indent=2), encoding="utf-8")
        print(f"Wrote {paths['branding_file']}")

    taxonomy_file = paths["org_dir"] / "taxonomy.py"
    if not taxonomy_file.exists():
        taxonomy_file.write_text(STUB_TAXONOMY.format(name=name), encoding="utf-8")
        print(f"Wrote {taxonomy_file} (stub — fill in once you've seen the real schema)")

    semantics_file = paths["org_dir"] / "semantics.py"
    if not semantics_file.exists():
        semantics_file.write_text(STUB_SEMANTICS.format(name=name), encoding="utf-8")
        print(f"Wrote {semantics_file} (stub)")


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()

    slug, is_new = pick_org(args.org)
    setup_org(slug, is_new)

    paths = org_context.org_paths(slug)
    if not paths["raw_schema"].exists():
        if not has_real_credentials(slug):
            print(f"\nSet up so far, but no schema yet. Add {slug}'s real "
                  f"BEACON_API_KEY and BEACON_ACCOUNT_ID to {paths['env_file']}, "
                  f"then run `python run.py --org {slug}` again.")
            return
        print("\nFetching the schema from Beacon (read-only, one call)...")
        beacon.set_org(slug)
        schema = beacon.get("entity_types")
        paths["raw_schema"].write_text(
            json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Saved {paths['raw_schema']}")

    print(f"\n{slug} is set up. What do you want to do?")
    print("  1. Everything (rebuild schema, verify, regenerate report)")
    print("  2. Just rebuild the schema export (out/)")
    print("  3. Just regenerate the HTML report (needs out/ already built)")
    choice = ask("Enter a number", "1")

    if choice in ("1", "2"):
        build_schema.build(slug)
        verify_out.main(slug)
        if ask("Run the optional usage report too? (~60 API requests) [y/N]", "n").lower().startswith("y"):
            usage_report.profile(slug)

    if choice in ("1", "3"):
        if not (paths["out_dir"] / "schema.json").exists():
            print(f"\nNo schema built yet for {slug} — run option 1 or 2 first.")
            return
        build_report.build(slug)
        print(f"\nDone. Report: {paths['report_target']}")


if __name__ == "__main__":
    main()
