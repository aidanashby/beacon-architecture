"""Gate: out/ is committed, so prove it holds no personal data. Run before pushing.

Exits non-zero on any hit, so it can be wired into a hook later.
"""

import json
import re
import sys

import org_context

PATTERNS = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "uk_phone": r"(?:\+44|\b0)(?:\d[ -]?){9,10}\d\b",
    "postcode": r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b",
    "free_text_prose": r"[A-Za-z ,]{200,}",
}

# Keys that would indicate record data crept in.
BANNED_KEYS = {"records", "results", "entity", "created_by_id", "avatar"}


def main(org):
    import beacon
    beacon.set_org(org)
    OUT = org_context.org_paths(org)["out_dir"]

    failures = []
    files = sorted(list(OUT.glob("*.json")) + list(OUT.glob("*.md")))
    if not files:
        sys.exit(f"{OUT} is empty — run build_schema.py --org {org} first")

    for path in files:
        text = path.read_text(encoding="utf-8")
        for name, rx in PATTERNS.items():
            if name == "free_text_prose" and path.suffix == ".md":
                continue
            hits = re.findall(rx, text)
            if hits:
                failures.append(f"{path.name}: {len(hits)} {name} match(es), e.g. {hits[0]!r}")
        if path.suffix == ".md":
            # Prose legitimately contains long sentences; only the identifier
            # patterns apply to it.
            continue
        for key in BANNED_KEYS:
            # Only as an actual JSON key. These names also appear as harmless
            # string literals in list_columns, which is view config, not data.
            if re.search(rf'"{key}"\s*:', text):
                failures.append(f"{path.name}: contains banned key {key!r} — record data may have leaked")

    schema = json.loads((OUT / "schema.json").read_text(encoding="utf-8"))
    if schema.get("contains_records") is not False:
        failures.append("schema.json: contains_records is not false")

    # Every field in the raw schema must still be present: sanitisation must
    # never drop a field, only values.
    raw = beacon.load_schema()
    raw_keys = {(e["key"], f["key"]) for e in raw["results"] for f in e["fields"]}
    out_keys = {(t["key"], f["key"]) for t in schema["entity_types"] for f in t["fields"]}
    missing = raw_keys - out_keys
    if missing:
        failures.append(f"{len(missing)} field(s) missing from out/schema.json, e.g. {sorted(missing)[:3]}")

    if failures:
        print("FAIL — out/ must not be committed:")
        for f in failures:
            print("  -", f)
        sys.exit(1)

    print(f"ok: {len(files)} file(s) in out/, {len(out_keys)} fields, no personal data detected")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()
    main(org_context.select_org(args.org))
