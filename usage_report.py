"""Optional analytics report: how the schema is actually used.

Separate from out/ on purpose. out/ is the architecture and stays true as
records are added; this report is a snapshot that goes stale, so it lives in
reports/ and is regenerated on demand.

Answers the question that matters for tidying the CRM: for each select field,
how many records hold each option, and which options are used by nobody.

Records are streamed and counted. No record value is ever written to disk.
Special-category and free-text fields contribute a fill count only.
"""

import json
from collections import Counter
from datetime import date

import beacon
import org_context
from build_schema import is_special_category


def option_values(value):
    """Normalise a select value to a list of option strings."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def profile(org):
    beacon.set_org(org)
    REPORTS = org_context.org_paths(org)["reports_dir"]
    schema = beacon.load_schema()
    report = {
        "generated": date.today().isoformat(),
        "note": "Snapshot of record usage. Contains counts only, never values. "
                "Special-category and free-text fields report fill counts only.",
        "entity_types": [],
    }

    for e in sorted(schema["results"], key=lambda x: x["key"]):
        key = e["key"]
        fields = e["fields"]
        filled = Counter()
        opts = {f["key"]: Counter() for f in fields if f["type"] == "select"}
        total = 0

        for page in beacon.pages(key):
            for row in page:
                entity = row.get("entity", row)
                total += 1
                for f in fields:
                    v = entity.get(f["key"])
                    if v in (None, "", [], {}):
                        continue
                    filled[f["key"]] += 1
                    # Only non-sensitive select fields get value-level counts.
                    if f["key"] in opts and not is_special_category(f):
                        for o in option_values(v):
                            opts[f["key"]][o] += 1

        field_rows = []
        for f in sorted(fields, key=lambda x: x["key"]):
            row = {
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "records_filled": filled[f["key"]],
                "fill_rate": round(filled[f["key"]] / total, 3) if total else None,
            }
            if is_special_category(f):
                row["value_counts_suppressed"] = "special_category"
            elif f["type"] == "text":
                row["value_counts_suppressed"] = "free_text"
            elif f["type"] == "select":
                declared = (f.get("metadata") or {}).get("options", [])
                used = opts[f["key"]]
                row["options"] = [{"option": o, "records": used.get(o, 0)} for o in declared]
                row["unused_options"] = [o for o in declared if not used.get(o)]
                row["declared_option_count"] = len(declared)
                row["unused_option_count"] = len(row["unused_options"])
            field_rows.append(row)

        report["entity_types"].append({
            "key": key,
            "label": e["label"],
            "record_count": total,
            "empty_fields": [r["key"] for r in field_rows if r["records_filled"] == 0],
            "fields": field_rows,
        })
        print(f"  {key}: {total} records")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "usage.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary(report, REPORTS)
    return report


def write_summary(report, REPORTS):
    """A short markdown digest of the two things worth acting on."""
    lines = [f"# Beacon usage snapshot — {report['generated']}", "",
             "Counts only. No record values. Regenerate with `python usage_report.py`.", ""]

    lines += ["## Select options nobody has used", ""]
    any_unused = False
    for t in report["entity_types"]:
        rows = [f for f in t["fields"] if f.get("unused_option_count")]
        if not rows:
            continue
        any_unused = True
        lines.append(f"### {t['label']} (`{t['key']}`) — {t['record_count']} records")
        for f in rows:
            lines.append(f"- **{f['label']}** (`{f['key']}`): "
                         f"{f['unused_option_count']} of {f['declared_option_count']} unused — "
                         + ", ".join(f"`{o}`" for o in f["unused_options"][:12])
                         + (" …" if len(f["unused_options"]) > 12 else ""))
        lines.append("")
    if not any_unused:
        lines += ["None.", ""]

    lines += ["## Fields no record has ever filled", ""]
    for t in report["entity_types"]:
        if t["empty_fields"] and t["record_count"]:
            lines.append(f"- **{t['label']}** (`{t['key']}`): "
                         + ", ".join(f"`{k}`" for k in t["empty_fields"]))
    lines.append("")

    (REPORTS / "usage-summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()
    org = org_context.select_org(args.org)

    r = profile(org)
    REPORTS = org_context.org_paths(org)["reports_dir"]
    # Self-check: the report must carry no values from suppressed fields.
    blob = (REPORTS / "usage.json").read_text(encoding="utf-8")
    assert "@" not in blob, "an email address reached the report"
    for t in r["entity_types"]:
        for f in t["fields"]:
            if f.get("value_counts_suppressed"):
                assert "options" not in f, f"{t['key']}.{f['key']} leaked values"
    unused = sum(f.get("unused_option_count", 0) for t in r["entity_types"] for f in t["fields"])
    print(f"\nok: {sum(t['record_count'] for t in r['entity_types'])} records profiled, "
          f"{unused} unused select options found -> reports/usage-summary.md")
