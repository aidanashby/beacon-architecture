"""Turn the raw entity_types response into the AI-readable architecture docs.

Pure transformation. No network, no records, no counts. Everything written
here is CRM configuration, which is not personal data.
"""

import importlib
import json

import beacon
import org_context

# Fields whose values are never profiled or exported anywhere. Listed here so
# the boundary is declared once and both scripts read the same list.
SPECIAL_CATEGORY_HINTS = (
    "ethnic", "religio", "sexual_orientation", "disabilit", "health",
    "allerg", "date_of_birth", "dob", "gender", "marital",
    "right_to_reside", "net_worth", "household_type", "safeguard",
)
FREE_TEXT_TYPES = ("text",)


def is_special_category(field):
    k = field["key"].lower()
    return any(h in k for h in SPECIAL_CATEGORY_HINTS)


def build(org):
    beacon.set_org(org)
    taxonomy = importlib.import_module(f"orgs.{org}.taxonomy")
    semantics = importlib.import_module(f"orgs.{org}.semantics")
    OUT = org_context.org_paths(org)["out_dir"]

    schema = beacon.load_schema()
    types = schema["results"]
    by_id = {e["id"]: e["key"] for e in types}

    entity_types, edges, attachments = [], [], []

    for e in sorted(types, key=lambda x: x["key"]):
        fields = []
        file_fields = []

        for f in sorted(e["fields"], key=lambda x: x["key"]):
            meta = f.get("metadata") or {}
            out = {
                "id": f["id"],
                "key": f["key"],
                "label": f["label"],
                "type": f["type"],
                "is_custom": f["is_custom"],
                "is_read_only": f["is_read_only"],
                "is_hidden": f["is_hidden"],
            }
            if f.get("help"):
                out["help"] = f["help"]
            if f.get("default_value") is not None:
                out["default_value"] = f["default_value"]

            if f["type"] == "select":
                out["options"] = meta.get("options", [])
                out["allow_multiple"] = meta.get("allow_multiple", False)
                if meta.get("fixed_options"):
                    out["fixed_options"] = meta["fixed_options"]
            elif f["type"] == "reference":
                targets = [by_id[i] for i in meta.get("entity_types", []) if i in by_id]
                out["references"] = targets
                out["allow_multiple"] = meta.get("allow_multiple", False)
                for t in targets:
                    edges.append({
                        "from": e["key"],
                        "via_field": f["key"],
                        "to": t,
                        "cardinality": "many_to_many" if meta.get("allow_multiple") else "many_to_one",
                    })
            elif f["type"] == "file":
                out["allow_multiple"] = meta.get("allow_multiple", False)
                file_fields.append({"key": f["key"], "label": f["label"],
                                    "allow_multiple": meta.get("allow_multiple", False)})
            elif meta:
                out["settings"] = meta

            if f["is_smart_field"]:
                out["smart_field"] = (f.get("smart_metadata") or {}).get("template")
            if f["is_rollup_field"] and f.get("rollup_metadata"):
                rm = f["rollup_metadata"]
                out["rollup"] = {
                    "aggregation": rm.get("aggregation"),
                    "over_entity_type": by_id.get(rm.get("entity_type_id")),
                    "filter_strictness": rm.get("filter_strictness"),
                    "filter_conditions": rm.get("filter_conditions"),
                }

            if is_special_category(f):
                out["special_category"] = True
            if f["type"] in FREE_TEXT_TYPES:
                out["free_text"] = True

            fields.append(out)

        primary = next((f["key"] for f in e["fields"] if f["id"] == e.get("primary_field_id")), None)
        group = taxonomy.group_of(e["key"])
        entry = {
            "id": e["id"],
            "key": e["key"],
            "label": e["label"],
            "label_plural": e["label_plural"],
            "is_custom": e["is_custom"],
            "group": group,
            "group_label": taxonomy.GROUPS[group]["label"],
            "money_direction": taxonomy.GROUPS[group]["money_direction"],
            "primary_field_key": primary,
            "field_count": len(fields),
            "layout": e.get("layout"),
            "list_columns": e.get("list_columns"),
            "fields": fields,
        }
        if e["key"] in taxonomy.LABEL_WARNINGS:
            entry["label_warning"] = taxonomy.LABEL_WARNINGS[e["key"]]
        entity_types.append(entry)

        if file_fields:
            attachments.append({"entity_type": e["key"], "label": e["label"],
                                "file_fields": file_fields})

    OUT.mkdir(exist_ok=True)
    write(OUT / "schema.json", {
        "account_id": schema["results"][0]["account_id"],
        "source": "GET /entity_types",
        "contains_records": False,
        "reading_notes": [
            "Record types carry an editorial `group` and `money_direction` "
            "(in / out / null). These are not Beacon concepts; they are added "
            "here because Beacon's own labels do not make the distinction.",
            "Beacon's grant labels invert the direction of money. See the "
            "`label_warning` field on the affected record types.",
        ],
        "groups": {
            k: {"label": v["label"], "money_direction": v["money_direction"],
                "note": v["note"]}
            for k, v in taxonomy.GROUPS.items()
        },
        "entity_type_count": len(entity_types),
        "field_count": sum(t["field_count"] for t in entity_types),
        "entity_types": entity_types,
    })
    write(OUT / "relationships.json", {
        "note": "Derived wholly from reference-field metadata in the schema.",
        "edge_count": len(edges),
        "edges": sorted(edges, key=lambda x: (x["from"], x["via_field"])),
    })
    write(OUT / "attachments.json", {
        "note": "Which entity types accept file attachments. No filenames, no file contents.",
        "entity_types_with_file_fields": len(attachments),
        "attachments": attachments,
    })
    (OUT / "semantics.md").write_text(semantics.render(entity_types), encoding="utf-8")
    return entity_types, edges, attachments


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()
    org = org_context.select_org(args.org)

    types, edges, attach = build(org)
    OUT = org_context.org_paths(org)["out_dir"]

    # Self-check: architecture only, and every field survived the transform.
    raw = beacon.load_schema()
    assert sum(len(e["fields"]) for e in raw["results"]) == sum(t["field_count"] for t in types), \
        "field count changed: sanitisation must never drop a field"
    blob = (OUT / "schema.json").read_text(encoding="utf-8")
    assert '"contains_records": false' in blob
    assert (OUT / "semantics.md").exists(), "semantics.md not written"
    print(f"ok: {len(types)} entity types, {sum(t['field_count'] for t in types)} fields, "
          f"{len(edges)} relationship edges, {len(attach)} types accept files, "
          f"semantics.md {len((OUT / 'semantics.md').read_text(encoding='utf-8'))//1024} KB")
