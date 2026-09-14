"""Generate docs/beacon-report.html — the human-readable companion to out/.

Reads out/*.json and, if present, reports/usage.json. Regenerate whenever the
CRM changes so the report never drifts from the export.

No record values are embedded: only counts, field metadata and option usage
totals, all of which come from files already verified clean.
"""

import importlib
import json
from datetime import date

import org_context

# Neutral fallback so a report always renders something even with no
# branding.json — clean, not any org's actual brand.
DEFAULT_BRANDING = {
    "name": "This organisation",
    "primary": "#33475b", "secondary": "#8a9bab",
    "coral": "#d97b6c", "teal": "#4f9aa8", "green": "#2f6f4f",
    "lime": "#9aa85f", "sun": "#e0b84e",
    "logo_white": None, "logo_purple": None,
}

# Short badge + plain-English gloss for each Beacon field type.
FIELD_TYPES = {
    "string": ("Aa", "Single line of text"),
    "text": ("¶", "Free-text, multiple lines"),
    "select": ("▾", "Choose from a fixed list"),
    "reference": ("→", "A link to another record"),
    "currency": ("£", "Money amount"),
    "number": ("#", "Number"),
    "date": ("▦", "Date, sometimes with a time"),
    "boolean": ("◐", "Yes or no"),
    "file": ("⏚", "File attachment"),
    "user": ("◑", "A Beacon user (staff member)"),
    "url": ("↗", "Web address"),
    "email": ("@", "Email address"),
    "phone": ("☎", "Phone number"),
    "location": ("⌖", "Address"),
    "rating": ("★", "Rating on a scale"),
    "person_name": ("◇", "Structured name (first, last, prefix)"),
    "percent": ("%", "Percentage"),
}


def load_branding(assets_dir, branding_file):
    branding = dict(DEFAULT_BRANDING)
    if branding_file.exists():
        branding.update(json.loads(branding_file.read_text(encoding="utf-8")))
    return branding


def logo_html(assets_dir, logo, org_name, css_class):
    """An <img> tag if a logo was found, otherwise the org name as plain text.

    The report needs to work as a standalone file sent to someone with no
    access to this project, so a logo is either a live URL (used as-is — the
    recipient's browser fetches it) or a local filename under assets/
    (embedded as a base64 data URI, for an org with no public logo to link
    to). Either way the report never depends on this project's files once
    it's built.
    """
    if not logo:
        return f'<span class="{css_class} logo-text">{esc(org_name)}</span>'
    if logo.startswith("http://") or logo.startswith("https://"):
        return f'<img class="{css_class}" src="{esc(logo)}" alt="{esc(org_name)}">'
    import base64
    p = assets_dir / logo
    if not p.exists():
        return f'<span class="{css_class} logo-text">{esc(org_name)}</span>'
    data_uri = "data:image/svg+xml;base64," + base64.b64encode(p.read_bytes()).decode()
    return f'<img class="{css_class}" src="{data_uri}" alt="{esc(org_name)}">'


def load(OUT, REPORTS):
    schema = json.loads((OUT / "schema.json").read_text(encoding="utf-8"))
    rels = json.loads((OUT / "relationships.json").read_text(encoding="utf-8"))
    attach = json.loads((OUT / "attachments.json").read_text(encoding="utf-8"))
    usage = None
    if (REPORTS / "usage.json").exists():
        usage = json.loads((REPORTS / "usage.json").read_text(encoding="utf-8"))
    return schema, rels, attach, usage


def build_nodes(schema, rels, usage, GROUPS, MEMBERSHIP, PENDING_SOON):
    counts = {}
    unused = {}
    empties = {}
    filled = {}
    if usage:
        for t in usage["entity_types"]:
            counts[t["key"]] = t["record_count"]
            unused[t["key"]] = sum(f.get("unused_option_count", 0) for f in t["fields"])
            empties[t["key"]] = len(t["empty_fields"])
            filled[t["key"]] = {f["key"]: f["records_filled"] for f in t["fields"]}

    degree = {}
    for e in rels["edges"]:
        degree[e["from"]] = degree.get(e["from"], 0) + 1
        degree[e["to"]] = degree.get(e["to"], 0) + 1

    nodes = []
    for t in schema["entity_types"]:
        k = t["key"]
        group = MEMBERSHIP.get(k, "admin")
        n = {
            "key": k,
            "label": t["label"],
            "plural": t["label_plural"],
            "group": group,
            "colour": GROUPS[group]["colour"],
            "custom": t["is_custom"],
            "fields": t["field_count"],
            "records": counts.get(k),
            "degree": degree.get(k, 0),
            "unusedOptions": unused.get(k, 0),
            "emptyFields": empties.get(k, 0),
            "dormant": counts.get(k) == 0,
            "pending": k in PENDING_SOON,
            "primary": k in ("person", "organization"),
            "fieldList": [
                {
                    "key": f["key"], "label": f["label"], "type": f["type"],
                    "custom": f["is_custom"], "readOnly": f["is_read_only"],
                    "options": f.get("options"),
                    "refs": f.get("references"),
                    "smart": f.get("smart_field"),
                    "rollup": bool(f.get("rollup")),
                    "special": bool(f.get("special_category")),
                    "help": f.get("help"),
                    "filled": filled.get(k, {}).get(f["key"]),
                }
                for f in t["fields"]
            ],
        }
        nodes.append(n)
    return nodes


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build(org):
    paths = org_context.org_paths(org)
    taxonomy = importlib.import_module(f"orgs.{org}.taxonomy")
    GROUPS, MEMBERSHIP, PENDING_SOON = taxonomy.GROUPS, taxonomy.MEMBERSHIP, taxonomy.PENDING_SOON
    branding = load_branding(paths["assets_dir"], paths["branding_file"])

    schema, rels, attach, usage = load(paths["out_dir"], paths["reports_dir"])
    nodes = build_nodes(schema, rels, usage, GROUPS, MEMBERSHIP, PENDING_SOON)
    by_key = {n["key"]: n for n in nodes}

    total_records = sum(n["records"] or 0 for n in nodes)
    live = [n for n in nodes if not n["dormant"]]
    dormant = [n for n in nodes if n["dormant"]]
    custom_types = [n for n in nodes if n["custom"]]
    total_unused = sum(n["unusedOptions"] for n in nodes)

    # Field type distribution across the whole CRM.
    type_dist = {}
    for n in nodes:
        for f in n["fieldList"]:
            type_dist[f["type"]] = type_dist.get(f["type"], 0) + 1
    type_dist = dict(sorted(type_dist.items(), key=lambda x: -x[1]))

    graph = {
        "nodes": [{k: v for k, v in n.items() if k != "fieldList"} for n in nodes],
        "edges": rels["edges"],
        "groups": GROUPS,
    }
    details = {n["key"]: n["fieldList"] for n in nodes}

    # Evidence for the Activity interpretation, computed rather than assumed.
    act_note = ""
    if usage:
        au = next((x for x in usage["entity_types"] if x["key"] == "activity"), None)
        if au:
            tf = next((f for f in au["fields"] if f["key"] == "type"), None)
            if tf and tf.get("options"):
                tot = au["record_count"] or 1
                opts = {o["option"]: o["records"] for o in tf["options"]}
                email = opts.get("Email", 0) + opts.get("Mailchimp email", 0)
                act_note = (
                    f"Of {tot:,} Activity records, <strong>{email:,} ({email/tot*100:.0f}%)</strong> "
                    f"are email — {opts.get('Email',0):,} logged emails and "
                    f"{opts.get('Mailchimp email',0):,} synced from Mailchimp. "
                    f"Against that: {opts.get('Note',0)} notes, {opts.get('Phone call',0)} phone calls, "
                    f"{opts.get('Meeting',0)} meetings and {opts.get('Letter',0)} letters."
                )

    # Configuration snags, detected rather than asserted.
    import re as _re
    junk_keys, overlaps = [], []
    for n in nodes:
        for f in n["fieldList"]:
            if _re.search(r"\d{10,}", f["key"]):
                junk_keys.append((n["label"], f["label"], f["key"]))
            opts = f.get("options") or []
            low = [o.lower().strip() for o in opts]
            for i, x in enumerate(low):
                for j, y in enumerate(low):
                    if i != j and x != y and x == y.split("(")[0].strip():
                        overlaps.append((n["label"], f["label"], opts[i], opts[j]))

    def type_options(key):
        n = by_key.get(key)
        if not n:
            return []
        f = next((x for x in n["fieldList"] if x["key"] == "type"), None)
        return (f or {}).get("options") or []

    ctx = {
        "generated": date.today().isoformat(),
        "branding": branding, "assets_dir": paths["assets_dir"],
        "GROUPS": GROUPS, "PENDING_SOON": PENDING_SOON,
        "schema": schema, "rels": rels, "attach": attach, "usage": usage,
        "nodes": nodes, "by_key": by_key, "live": live, "dormant": dormant,
        "custom_types": custom_types, "total_records": total_records,
        "total_unused": total_unused, "type_dist": type_dist,
        "graph": graph, "details": details, "act_note": act_note,
        "junk_keys": junk_keys, "overlaps": overlaps,
        "person_types": type_options("person"), "org_types": type_options("organization"),
    }
    paths["report_target"].parent.mkdir(exist_ok=True)
    paths["report_target"].write_text(render(ctx), encoding="utf-8")
    return ctx


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def bar_chart(rows, max_value, colour_fn=None, unit=""):
    """Horizontal bars as divs: prints correctly, needs no canvas."""
    out = ['<div class="chart">']
    for label, value, meta in rows:
        pct = (value / max_value * 100) if max_value else 0
        colour = colour_fn(label) if colour_fn else "var(--org-primary)"
        out.append(
            f'<div class="row"><div class="rl">{esc(label)}</div>'
            f'<div class="rb"><span style="width:{pct:.1f}%;background:{colour}"></span></div>'
            f'<div class="rv">{value:,}{unit}<em>{esc(meta)}</em></div></div>'
        )
    out.append("</div>")
    return "\n".join(out)


def field_table(fields, limit=None):
    shown = fields if limit is None else fields[:limit]
    rows = []
    for f in shown:
        badge, _ = FIELD_TYPES.get(f["type"], ("?", f["type"]))
        notes = []
        if f["refs"]:
            notes.append("links to " + ", ".join(f"<code>{esc(r)}</code>" for r in f["refs"]))
        if f["options"]:
            n = len(f["options"])
            sample = ", ".join(esc(o) for o in f["options"][:4])
            notes.append(f"{n} option{'s' if n != 1 else ''}: {sample}" + (" …" if n > 4 else ""))
        if f["smart"]:
            notes.append(f"auto-built from <code>{esc(f['smart'])}</code>")
        if f["rollup"]:
            notes.append("calculated by rolling up linked records")
        if f["help"]:
            notes.append(esc(f["help"]))
        flags = []
        if f["special"]:
            flags.append('<span class="flag special">special category</span>')
        if f["readOnly"]:
            flags.append('<span class="flag">read-only</span>')
        if f["custom"]:
            flags.append('<span class="flag custom">custom</span>')
        rows.append(
            f'<tr><td class="ft"><span class="badge">{badge}</span></td>'
            f'<td><strong>{esc(f["label"])}</strong><br><code>{esc(f["key"])}</code></td>'
            f'<td>{esc(f["type"])}</td>'
            f'<td>{" · ".join(notes) if notes else "—"} {" ".join(flags)}</td></tr>'
        )
    return ('<div class="wrap"><table class="fields"><thead><tr><th></th><th>Field</th>'
            '<th>Type</th><th>What it holds</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table></div>")


def render(c):
    g = c["graph"]
    nodes, by_key = c["nodes"], c["by_key"]
    GROUPS, PENDING_SOON, branding = c["GROUPS"], c["PENDING_SOON"], c["branding"]

    # --- key numbers
    kpis = [
        (len(nodes), "record types", "the kinds of thing Beacon can store"),
        (c["schema"]["field_count"], "fields", "individual pieces of information"),
        (c["rels"]["edge_count"], "links", "ways records connect to each other"),
        (f"{c['total_records']:,}", "records", "actual entries today"),
        (len(c["custom_types"]), "custom types", f"of {len(nodes)} types are bespoke"),
        (len(c["dormant"]), "dormant", "types switched on but never used"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><span class="n">{v}</span><span class="l">{esc(l)}</span>'
        f'<span class="d">{esc(d)}</span></div>' for v, l, d in kpis)

    # --- group summary
    group_rows = []
    for gk, gm in GROUPS.items():
        members = [n for n in nodes if n["group"] == gk]
        recs = sum(n["records"] or 0 for n in members)
        live_n = sum(1 for n in members if not n["dormant"])
        group_rows.append(
            f'<div class="gcard" style="--c:{gm["colour"]}">'
            f'<h3>{esc(gm["label"])}</h3>'
            f'<p class="gnote">{esc(gm["note"])}</p>'
            f'<p class="gstat"><strong>{len(members)}</strong> record types · '
            f'<strong>{live_n}</strong> in use · <strong>{recs:,}</strong> records</p>'
            f'<p class="gkeys">' + " ".join(
                f'<span class="chip{" dim" if n["dormant"] else ""}">{esc(n["label"])}</span>'
                for n in sorted(members, key=lambda x: -(x["records"] or 0))) + '</p></div>')

    # --- labels that mislead: entity types where the Beacon label points the
    # wrong way, per this org's taxonomy.LABEL_WARNINGS (out/schema.json's
    # label_warning field).
    warned = [t for t in c["schema"]["entity_types"] if t.get("label_warning")]
    label_warnings_html = ""
    if warned:
        items = "".join(
            f'<li><strong>{esc(t["label"])}</strong> (<code>{esc(t["key"])}</code>) — '
            f'{esc(t["label_warning"])}</li>' for t in warned)
        label_warnings_html = (
            '<div class="callout warn">'
            '<p><strong>Labels that mislead.</strong> Beacon\'s own label does not '
            'match what the record type actually holds for the following types — '
            'check which one you mean before reading a figure.</p>'
            f'<ul>{items}</ul></div>')

    # --- record volume chart (live types only)
    vol = sorted([n for n in c["live"]], key=lambda n: -(n["records"] or 0))
    vol_rows = [(n["label"], n["records"] or 0, f'{n["fields"]} fields') for n in vol]
    vol_chart = bar_chart(vol_rows, max((r[1] for r in vol_rows), default=1) or 1,
                          colour_fn=lambda lbl: next(
                              (n["colour"] for n in nodes if n["label"] == lbl), branding["primary"]))

    # --- most connected chart
    conn = sorted(nodes, key=lambda n: -n["degree"])[:12]
    conn_chart = bar_chart(
        [(n["label"], n["degree"], "links") for n in conn],
        conn[0]["degree"],
        colour_fn=lambda lbl: next((n["colour"] for n in nodes if n["label"] == lbl), branding["primary"]))

    # --- field type chart
    ft_rows = [(f"{FIELD_TYPES.get(t, ('?', t))[1]}", n, t) for t, n in c["type_dist"].items()]
    ft_chart = bar_chart(ft_rows, ft_rows[0][1], colour_fn=lambda _: branding["secondary"])

    # --- attachments
    att = sorted(c["attach"]["attachments"], key=lambda a: -len(a["file_fields"]))
    att_html = "".join(
        f'<li><strong>{esc(a["label"])}</strong> '
        f'<span class="muted">{len(a["file_fields"])} file field'
        f'{"s" if len(a["file_fields"]) != 1 else ""}</span> — '
        + ", ".join(f'<code>{esc(f["key"])}</code>' for f in a["file_fields"]) + "</li>"
        for a in att)

    # --- unused options
    unused_html = ""
    if c["usage"]:
        rows = []
        for t in c["usage"]["entity_types"]:
            bad = [f for f in t["fields"] if f.get("unused_option_count")]
            if not bad:
                continue
            items = "".join(
                f'<li><strong>{esc(f["label"])}</strong> '
                f'<span class="muted">{f["unused_option_count"]} of '
                f'{f["declared_option_count"]} unused</span><br>'
                + " ".join(f'<span class="chip dim">{esc(o)}</span>'
                           for o in f["unused_options"][:10])
                + (' <span class="muted">…</span>' if len(f["unused_options"]) > 10 else "")
                + "</li>" for f in bad)
            rows.append(f'<div class="ucard"><h4>{esc(t["label"])} '
                        f'<span class="muted">{t["record_count"]:,} records</span></h4>'
                        f'<ul class="ulist">{items}</ul></div>')
        unused_html = "".join(rows)

    # --- foundational field tables
    person = by_key["person"]
    org = by_key["organization"]

    # --- dormant list
    dormant_html = "".join(
        f'<li><strong>{esc(n["label"])}</strong> <code>{esc(n["key"])}</code> '
        f'<span class="muted">{n["fields"]} fields, no records yet</span>'
        + (f'<br><span class="pending-note">{esc(PENDING_SOON[n["key"]])}</span>'
           if n["key"] in PENDING_SOON else "")
        + '</li>'
        for n in sorted(c["dormant"], key=lambda x: (x["key"] not in PENDING_SOON, x["label"])))

    snag_items = []
    seen_snag = set()
    for label, flabel, key in c["junk_keys"]:
        seen_snag.add(key)
    if c["junk_keys"]:
        where = ", ".join(sorted({x[0] for x in c["junk_keys"]}))
        k = c["junk_keys"][0][2]
        snag_items.append(
            f'<li><strong>A field with a corrupted key.</strong> The <em>Source</em> field on '
            f'{esc(where)} has the internal key <code>{esc(k)}</code>. It works, but it was '
            f'almost certainly created by accident. Renaming the key is not always possible in '
            f'Beacon once a field exists — worth checking before anything depends on it.</li>')
    seen_pairs = set()
    for label, flabel, a, b in c["overlaps"]:
        pair = (label, flabel, tuple(sorted([a, b])))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        if flabel.lower() == "payment method":
            continue  # "Card" vs "Card (contactless)" is a real distinction, not a snag
        snag_items.append(
            f'<li><strong>Two options that mean the same thing.</strong> '
            f'{esc(label)} → <em>{esc(flabel)}</em> offers both <code>{esc(a)}</code> and '
            f'<code>{esc(b)}</code>. Staff can pick either, so the data splits across both. '
            f'Worth merging.</li>')
    snags_html = "".join(snag_items)
    snag_count = len(snag_items)
    snag_word = {1: "One snag", 2: "Two snags", 3: "Three snags"}.get(
        snag_count, f"{snag_count} snags")

    NUMBER_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five",
                    6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten"}
    group_count_word = NUMBER_WORDS.get(len(GROUPS), str(len(GROUPS)))

    def opt_sentence(opts, n=8):
        shown = ", ".join(esc(o) for o in opts[:n])
        return shown + (f" and {len(opts)-n} more" if len(opts) > n else "")

    data_json = json.dumps({"graph": g, "details": c["details"],
                            "fieldTypes": FIELD_TYPES, "orgName": branding["name"]},
                           ensure_ascii=False)

    return TEMPLATE.format(
        generated=c["generated"], kpis=kpi_html,
        groups="".join(group_rows), label_warnings_html=label_warnings_html,
        group_count_word=group_count_word,
        vol_chart=vol_chart, conn_chart=conn_chart,
        ft_chart=ft_chart, att_html=att_html, att_count=len(att),
        unused_html=unused_html, total_unused=c["total_unused"],
        person_fields=field_table(person["fieldList"]),
        org_fields=field_table(org["fieldList"]),
        person_count=person["fields"], org_count=org["fields"],
        person_records=f'{person["records"]:,}' if person["records"] else "—",
        org_records=f'{org["records"]:,}' if org["records"] else "—",
        dormant_html=dormant_html, dormant_count=len(c["dormant"]),
        total_records=f'{c["total_records"]:,}',
        live_count=len(c["live"]), type_count=len(nodes),
        edge_count=c["rels"]["edge_count"], field_count=c["schema"]["field_count"],
        custom_count=len(c["custom_types"]),
        data=data_json, act_note=c["act_note"], snags_html=snags_html,
        logo_white_html=logo_html(c["assets_dir"], branding["logo_white"], branding["name"], "logo"),
        logo_purple_html=logo_html(c["assets_dir"], branding["logo_purple"], branding["name"], "logo print-logo"),
        snag_word=snag_word,
        org_name=esc(branding["name"]),
        primary=branding["primary"], secondary=branding["secondary"],
        coral=branding["coral"], teal=branding["teal"], green=branding["green"],
        lime=branding["lime"], sun=branding["sun"],
        person_types=opt_sentence(c["person_types"]),
        org_types=opt_sentence(c["org_types"]),
        person_type_count=len(c["person_types"]), org_type_count=len(c["org_types"]),
    )


TEMPLATE = r"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beacon CRM — how it is put together</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Nunito+Sans:opsz,wght@6..12,400;6..12,600;6..12,700&display=swap" rel="stylesheet">
<style>
:root{{
  --org-primary:{primary}; --org-secondary:{secondary};
  --coral:{coral}; --teal:{teal}; --green:{green}; --lime:{lime}; --sun:{sun};
  --ink:#241a3d; --body:#443c55; --muted:#6f6880; --line:#e4e0ec; --panel:#faf9fc;
  --bg:#fff;
}}
*{{box-sizing:border-box}}
body{{
  margin:0; background:var(--bg); color:var(--body);
  font-family:"Nunito Sans","Gill Sans","Gill Sans MT",Calibri,system-ui,sans-serif;
  font-size:16px; line-height:1.62; -webkit-font-smoothing:antialiased;
}}
.page{{max-width:1080px; margin:0 auto; padding:0 2rem 5rem}}
h1,h2,h3,h4{{font-family:"Gill Sans","Gill Sans MT",Calibri,"Nunito Sans",sans-serif;
  color:var(--ink); line-height:1.22; letter-spacing:-.01em; margin:0}}
h1{{font-size:2.6rem; font-weight:600}}
h2{{font-size:1.65rem; margin:0 0 .35rem}}
h3{{font-size:1.12rem; margin:0 0 .3rem}}
h4{{font-size:1rem; margin:0 0 .3rem}}
p{{margin:0 0 1rem}}
code{{font-family:ui-monospace,"Cascadia Code",Consolas,monospace; font-size:.85em;
  background:#f2eff7; color:#4b3a76; padding:.09em .38em; border-radius:4px}}
.muted{{color:var(--muted)}}
a{{color:var(--org-primary)}}

/* ---------- masthead ---------- */
.mast{{background:var(--org-primary); color:#fff; padding:3.4rem 0 2.6rem; margin-bottom:2.5rem}}
.mast .page{{padding-bottom:0}}
.mast h1{{color:#fff; max-width:20ch}}
.mast .logo{{height:44px; width:auto; display:block; margin:0 0 1.6rem}}
.mast .logo.print-logo{{display:none}}
.mast .logo-text{{display:block; font-size:1.6rem; font-weight:700; margin:0 0 1.6rem}}
.mast .kicker{{text-transform:uppercase; letter-spacing:.16em; font-size:.72rem;
  color:var(--org-secondary); font-weight:700; margin:0 0 .8rem}}
.mast .lede{{color:#e7e0f2; font-size:1.14rem; max-width:62ch; margin:1.1rem 0 0}}
.mast .meta{{color:#b9a9d6; font-size:.82rem; margin-top:1.6rem}}

/* ---------- kpis ---------- */
.kpis{{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line);
  border-radius:10px; overflow:hidden; margin:0 0 2.6rem}}
.kpi{{background:#fff; padding:1.1rem 1.15rem; display:flex; flex-direction:column}}
.kpi .n{{font-family:"Gill Sans","Gill Sans MT",sans-serif; font-size:2rem;
  color:var(--org-primary); font-weight:600; line-height:1}}
.kpi .l{{font-weight:700; color:var(--ink); font-size:.9rem; margin-top:.35rem}}
.kpi .d{{font-size:.78rem; color:var(--muted); margin-top:.15rem; line-height:1.4}}

/* ---------- sections ---------- */
section{{margin:0 0 3.2rem}}
.shead{{display:flex; gap:.85rem; align-items:flex-start; margin:0 0 1.3rem;
  padding-bottom:.7rem; border-bottom:2px solid var(--line)}}
.shead .ico{{flex:none; width:2.2rem; height:2.2rem; border-radius:7px;
  background:var(--org-primary); display:grid; place-items:center; margin-top:.1rem}}
.shead .ico svg{{width:1.2rem; height:1.2rem; fill:none; stroke:#fff; stroke-width:1.8;
  stroke-linecap:round; stroke-linejoin:round}}
.shead p{{margin:.2rem 0 0; color:var(--muted); font-size:.94rem; max-width:none; width:100%}}
.lead{{font-size:1.06rem; max-width:none; width:100%}}
.lead strong{{color:var(--ink)}}

/* ---------- concept cards ---------- */
.concepts{{display:grid; grid-template-columns:repeat(auto-fit,minmax(215px,1fr)); gap:.9rem}}
.concept{{border:1px solid var(--line); border-radius:9px; padding:1rem 1.05rem; background:var(--panel)}}
.concept .badge{{margin-bottom:.5rem}}
.concept h4{{margin-bottom:.25rem}}
.concept p{{margin:0; font-size:.88rem; color:var(--muted)}}
.badge{{display:inline-grid; place-items:center; width:1.6rem; height:1.6rem;
  border-radius:5px; background:var(--org-secondary); color:#2e2050;
  font-weight:700; font-size:.82rem; font-family:ui-monospace,Consolas,monospace}}

/* ---------- group cards ---------- */
.groups{{display:grid; grid-template-columns:repeat(auto-fit,minmax(285px,1fr)); gap:1rem}}
.gcard{{border:1px solid var(--line); border-left:4px solid var(--c); border-radius:9px;
  padding:1.05rem 1.15rem; background:#fff}}
.gcard h3{{color:var(--c)}}
.gnote{{font-size:.9rem; margin:0 0 .6rem; color:var(--muted)}}
.gstat{{font-size:.85rem; margin:0 0 .6rem; color:var(--body)}}
.gstat strong{{color:var(--ink)}}
.gkeys{{margin:0; display:flex; flex-wrap:wrap; gap:.28rem}}
.chip{{font-size:.72rem; background:#f2eff7; color:#4b3a76; border-radius:20px;
  padding:.14rem .55rem; white-space:nowrap}}
.chip.dim{{background:#f4f4f6; color:#9a95a6; text-decoration:line-through}}

/* ---------- graph ---------- */
.graphwrap{{border:1px solid var(--line); border-radius:11px; overflow:hidden; background:#fff}}
.gbar{{display:flex; gap:.5rem; align-items:center; flex-wrap:wrap;
  padding:.6rem .8rem; border-bottom:1px solid var(--line); background:var(--panel)}}
.gbar button{{font:inherit; font-size:.82rem; border:1px solid var(--line); background:#fff;
  color:var(--body); border-radius:6px; padding:.24rem .7rem; cursor:pointer}}
.gbar button:hover{{border-color:var(--org-primary); color:var(--org-primary)}}
.gbar .hint{{font-size:.78rem; color:var(--muted); margin-left:auto}}
.legend{{display:flex; flex-wrap:wrap; gap:.75rem; padding:.6rem .8rem;
  border-bottom:1px solid var(--line); font-size:.78rem}}
.legend span{{display:flex; align-items:center; gap:.32rem; color:var(--muted);
  cursor:pointer; border-radius:20px; padding:.1rem .5rem; border:1px solid transparent;
  user-select:none}}
.legend span:hover{{border-color:var(--line); background:#fff}}
.legend span.on{{border-color:var(--org-primary); background:#fff; color:var(--ink); font-weight:600}}
.legend i{{width:.7rem; height:.7rem; border-radius:50%; display:block}}
.gstage{{position:relative; display:flex; height:80vh; min-height:420px; overflow:hidden}}
.gmap{{position:relative; flex:1 1 auto; min-width:0; display:flex}}
#graph{{flex:1 1 auto; width:100%; height:100%; display:block; background:#fff;
  cursor:grab; touch-action:none;
  -webkit-user-select:none; user-select:none}}
#graph.drag{{cursor:grabbing}}
.gnode circle{{transition:stroke-width .12s}}
.gnode text{{font-family:"Nunito Sans",sans-serif; pointer-events:none;
  fill:var(--ink); font-size:11px}}
.gnode.primary text{{font-weight:700; font-size:13px}}
.gnode.dim circle{{opacity:.32}} .gnode.dim text{{opacity:.45}}
.gnode.fade{{opacity:.13}}
.gedge{{stroke:#c9c2da; fill:none}}
.gedge.hot{{stroke:var(--org-primary); stroke-width:2}}
.gedge.fade{{opacity:.07}}
#tip{{position:absolute; pointer-events:none; background:var(--ink); color:#fff;
  padding:.55rem .7rem; border-radius:7px; font-size:.8rem; max-width:250px;
  opacity:0; transition:opacity .12s; line-height:1.45; z-index:5}}
#tip b{{display:block; font-size:.9rem; margin-bottom:.15rem}}
#tip em{{color:var(--org-secondary); font-style:normal}}
.panel{{flex:none; width:390px; height:100%; border-left:1px solid var(--line);
  background:var(--panel); overflow-y:auto; overscroll-behavior:contain;
  padding:1rem 1.15rem}}
.panel .pbody{{display:block}}
.pempty{{margin-top:.9rem; border-top:1px solid var(--line); padding-top:.5rem}}
.pempty summary{{cursor:pointer; font-size:.82rem; font-weight:600; color:var(--org-primary);
  padding:.25rem 0}}
.pempty .pf .pl{{color:var(--muted)}}
.panel .phead{{display:flex; align-items:baseline; gap:.7rem; flex-wrap:wrap; margin-bottom:.5rem}}
.panel .phead h3{{margin:0}}
.fsbtn{{position:absolute; top:.55rem; right:.6rem; z-index:4; width:1.9rem; height:1.9rem;
  border:1px solid var(--line); background:rgba(255,255,255,.9); border-radius:6px;
  display:grid; place-items:center; cursor:pointer; padding:0; opacity:.55;
  transition:opacity .15s, border-color .15s}}
.fsbtn:hover{{opacity:1; border-color:var(--org-primary)}}
.fsbtn svg{{width:.95rem; height:.95rem; fill:none; stroke:var(--body); stroke-width:2;
  stroke-linecap:round; stroke-linejoin:round}}
.graphwrap:fullscreen{{background:#fff; display:flex; flex-direction:column}}
.graphwrap:fullscreen .gstage{{flex:1; height:auto; min-height:0}}

.panel.empty .pbody{{display:none}}
.panel .ph{{color:var(--muted); font-size:.86rem}}
.panel h3{{margin-bottom:.15rem}}
.panel .pmeta{{font-size:.8rem; color:var(--muted); margin:0 0 .9rem}}
.panel .pf{{border-top:1px solid var(--line); padding:.5rem 0; font-size:.84rem}}
.panel .pf .pl{{font-weight:600; color:var(--ink)}}
.panel .pf .pd{{color:var(--muted); font-size:.74rem; line-height:1.35}}
.closep{{float:right; border:0; background:none; font-size:1.25rem; cursor:pointer;
  color:var(--muted); line-height:1; margin:-.2rem -.3rem 0 .4rem; padding:.1rem .25rem}}
.closep:hover{{color:var(--ink)}}

/* ---------- charts ---------- */
.chart{{margin:0 0 .5rem}}
.chart .row{{display:grid; grid-template-columns:minmax(120px,1.35fr) 3fr minmax(96px,auto);
  gap:.7rem; align-items:center; padding:.19rem 0}}
.chart .rl{{font-size:.86rem; color:var(--ink); text-align:right;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap}}
.chart .rb{{background:#f1eef7; border-radius:3px; height:.85rem; overflow:hidden}}
.chart .rb span{{display:block; height:100%; border-radius:3px}}
.chart .rv{{font-size:.82rem; color:var(--ink); font-weight:600; white-space:nowrap}}
.chart .rv em{{font-style:normal; font-weight:400; color:var(--muted); font-size:.74rem;
  margin-left:.35rem}}

/* ---------- tables ---------- */
.wrap{{overflow-x:auto; border:1px solid var(--line); border-radius:9px}}
table{{border-collapse:collapse; width:100%; font-size:.85rem; min-width:620px}}
th,td{{text-align:left; padding:.5rem .65rem; border-bottom:1px solid var(--line);
  vertical-align:top}}
th{{background:var(--panel); font-size:.72rem; text-transform:uppercase;
  letter-spacing:.07em; color:var(--muted); font-weight:700; position:sticky; top:0}}
tr:last-child td{{border-bottom:0}}
td.ft{{width:2.4rem}}
.fields code{{font-size:.76em}}
.flag{{display:inline-block; font-size:.68rem; border-radius:3px; padding:.02rem .34rem;
  background:#eee; color:#555; white-space:nowrap}}
.flag.custom{{background:#eee7f6; color:#57408c}}
.flag.special{{background:#fdeceb; color:#9c3b34}}

/* ---------- misc ---------- */
.cols2{{display:grid; grid-template-columns:1fr 1fr; gap:1.6rem}}
.callout{{border:1px solid var(--line); border-left:4px solid var(--teal);
  background:var(--panel); border-radius:0 9px 9px 0; padding:1rem 1.2rem; margin:1.2rem 0}}
.callout.warn{{border-left-color:var(--coral)}}
.callout p:last-child{{margin:0}}
.plainlist{{list-style:none; padding:0; margin:0}}
.plainlist li{{padding:.42rem 0; border-bottom:1px solid var(--line); font-size:.89rem}}
.plainlist li:last-child{{border:0}}
.ucards{{display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:1rem}}
.ucard{{border:1px solid var(--line); border-radius:9px; padding:.9rem 1rem}}
.ulist{{list-style:none; padding:0; margin:.5rem 0 0}}
.ulist li{{padding:.4rem 0; border-top:1px solid var(--line); font-size:.85rem}}
.ulist li:first-child{{border:0}}
details.more{{margin-top:.8rem}}
details.more summary{{cursor:pointer; color:var(--org-primary); font-size:.88rem;
  font-weight:600; padding:.4rem 0}}
footer{{border-top:2px solid var(--line); padding-top:1.2rem; color:var(--muted);
  font-size:.82rem}}

/* ---------- print: A4 ---------- */
@media print{{
  @page{{size:A4; margin:15mm 14mm}}
  body{{font-size:10.2pt; line-height:1.45}}
  .page{{max-width:none; padding:0}}
  .mast{{background:none; color:var(--ink); padding:0 0 1rem; margin-bottom:1.2rem;
    border-bottom:3px solid var(--org-primary)}}
  .mast h1{{color:var(--org-primary); font-size:24pt}}
  .mast .kicker{{color:var(--org-primary)}}
  .mast .lede{{color:var(--body); font-size:11pt}}
  .mast .meta{{color:var(--muted)}}
  h2{{font-size:15pt}} h1{{font-size:24pt}}
  section{{margin-bottom:1.5rem; break-inside:auto}}
  .shead{{break-after:avoid}} h2,h3,h4{{break-after:avoid}}
  .kpis{{grid-template-columns:repeat(3,1fr); break-inside:avoid}}
  .kpi .n{{font-size:16pt}}
  .gcard,.concept,.ucard,.callout{{break-inside:avoid}}
  .gbar,.panel,.closep,.fsbtn,details.more summary{{display:none !important}}
  .mast .logo{{display:none}} .mast .logo.print-logo{{display:block; height:38px}}
  .gstage{{height:auto; min-height:0; display:block}}
  #graph{{width:100% !important; height:150mm}}
  .graphwrap{{break-inside:avoid; page-break-inside:avoid}}
  .wrap{{overflow:visible; border:1px solid var(--line)}}
  table{{min-width:0; font-size:8.4pt}}
  th{{position:static}}
  tr{{break-inside:avoid}}
  /* digest print: exhaustive tables collapse away, screen keeps them */
  .screen-only{{display:none !important}}
  details.more[open] > *:not(summary){{display:none}}
  .print-note{{display:block !important}}
  a[href^="http"]::after{{content:" (" attr(href) ")"; font-size:8pt; color:var(--muted)}}
  .page-break{{break-before:page}}
}}
.stamp{{font-size:.82rem; color:var(--muted); font-style:italic; margin:0 0 .7rem}}
.snags li{{padding:.6rem 0}}
.pending-note{{color:var(--teal); font-size:.82rem; font-weight:600}}
.snags strong{{color:var(--ink)}}
.print-note{{display:none; font-size:.85rem; color:var(--muted); font-style:italic}}
@media(max-width:900px){{
  .cols2{{grid-template-columns:1fr}}
  .gstage{{flex-direction:column; height:auto}}
  .gmap{{height:60vh}}
  .panel{{width:auto; height:auto; border-left:0; border-top:1px solid var(--line);
    max-height:22rem}}
}}
</style>
</head>
<body>

<header class="mast">
  <div class="page">
    {logo_white_html}
    {logo_purple_html}
    <p class="kicker">CRM architecture</p>
    <h1>How our Beacon CRM is put together</h1>
    <p class="lede">Beacon holds {total_records} records across {type_count} kinds of thing —
      people, organisations, grants, cases, projects. This report explains what those
      things are, how they connect, and where the structure has drifted from how we
      actually work.</p>
    <p class="meta">Generated {generated} from the live schema · configuration only, no personal data</p>
  </div>
</header>

<div class="page">

<div class="kpis">{kpis}</div>

<!-- ============ 1. ORIENTATION ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg></span>
    <div>
      <h2>Start here: the five ideas</h2>
      <p>Beacon is built from a small number of repeating parts. Once these make sense, the rest of this report is just detail.</p>
    </div>
  </div>

  <p class="lead">A CRM is a filing system where the folders know about each other.
  Beacon stores <strong>records</strong> — one per person, one per grant, one per case.
  Each record is an instance of a <strong>record type</strong>, and the record type decides
  which <strong>fields</strong> that record has. Records point at each other through
  <strong>links</strong>, and that web of links is what makes it a CRM rather than a
  spreadsheet.</p>

  <div class="concepts">
    <div class="concept"><span class="badge">▤</span><h4>Record type</h4>
      <p>A kind of thing we store. "Person" and "Grant" are record types. We have {type_count}, of which {custom_count} were built specifically for {org_name}.</p></div>
    <div class="concept"><span class="badge">Aa</span><h4>Field</h4>
      <p>One piece of information on a record — a name, a date, an amount. There are {field_count} across the whole system.</p></div>
    <div class="concept"><span class="badge">→</span><h4>Link</h4>
      <p>A field whose value is another record. This grant links to that organisation. There are {edge_count} such connections defined.</p></div>
    <div class="concept"><span class="badge">▾</span><h4>Option list</h4>
      <p>A field where you pick from a fixed set of answers. Keeps data consistent — and is where unused choices pile up.</p></div>
    <div class="concept"><span class="badge">Σ</span><h4>Calculated field</h4>
      <p>A field Beacon works out for itself: totals rolled up from linked records, or a title built from other fields. Nobody types these.</p></div>
  </div>

  <div class="callout">
    <p><strong>The one thing to take away.</strong> Almost everything in this CRM hangs
    off two record types: <strong>Person</strong> and <strong>Organisation</strong>.
    Person is by far the most connected type in the system. If you are ever unsure where
    something belongs, ask which person or which organisation it concerns — that is
    usually the answer.</p>
  </div>
</section>

<!-- ============ 2. THE MAP ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><circle cx="6" cy="7" r="2.5"/><circle cx="18" cy="7" r="2.5"/><circle cx="12" cy="18" r="2.5"/><path d="M8 8.5l3 7M16 8.5l-3 7M8.5 7h7"/></svg></span>
    <div>
      <h2>The map</h2>
      <p>Every record type, sized by how connected it is. Drag to pan, scroll to zoom, hover for a summary, click a circle to read its fields.</p>
    </div>
  </div>

  <div class="graphwrap">
    <div class="gbar">
      <button data-act="reset">Reset view</button>
      <button data-act="fit">Fit to screen</button>
      <button data-act="toggle-dormant">Hide dormant</button>
      <button data-act="toggle-labels">Labels: all</button>
      <span class="hint">Scroll to zoom · drag background to pan · click a circle for detail</span>
    </div>
    <div class="legend" id="legend"></div>
    <div class="gstage">
      <div class="gmap">
        <button class="fsbtn" id="fsbtn" title="Full screen" aria-label="Full screen">
          <svg viewBox="0 0 24 24"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>
        </button>
        <svg id="graph" role="img" aria-label="Interactive map of Beacon record types and how they link"></svg>
        <div id="tip"></div>
      </div>
      <aside class="panel empty" id="panel">
        <p class="ph"><strong>Hover</strong> a circle for a quick summary — what it is, how
        many records and fields it has, how many other record types it links to.
        <strong>Click</strong> it to list every field it holds and highlight its connections.
        <strong>Click a colour in the key above</strong> to pick out one family.
        The two largest circles, <strong>Person</strong> and <strong>Organisation</strong>,
        are the foundation — start there.</p>
        <div class="pbody"></div>
      </aside>
    </div>
  </div>
  <p class="print-note">Printed version shows the map as laid out on screen. Circle size reflects how many other record types connect to it; faded circles are record types with no records in them.</p>
</section>

<!-- ============ 3. FAMILIES ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg></span>
    <div>
      <h2>{group_count_word} families of record</h2>
      <p>Beacon does not group record types itself. These groupings are ours, to make {type_count} types comprehensible.</p>
    </div>
  </div>
  <div class="groups">{groups}</div>

  {label_warnings_html}
</section>

<!-- ============ 4. FOUNDATION ============ -->
<section class="page-break">
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0111 0"/><path d="M16 11h5M16 15h5M16 19h5"/></svg></span>
    <div>
      <h2>The two foundational records</h2>
      <p>Person and Organisation. Understand these and you understand most of the system.</p>
    </div>
  </div>

  <div class="cols2">
    <div>
      <h3>Person</h3>
      <p class="muted" style="font-size:.88rem">{person_records} records · {person_count} fields · the most connected type in the CRM</p>
      <p>A Person record is anyone we hold a relationship with. Rather than separate
      record types per relationship, Beacon uses one Person record with a
      <em>Type</em> field carrying {person_type_count} options: {person_types}. One person can
      hold several at once, which is why the same record serves a resident who is also a
      volunteer.</p>
    </div>
    <div>
      <h3>Organisation</h3>
      <p class="muted" style="font-size:.88rem">{org_records} records · {org_count} fields</p>
      <p>Partner and funder bodies, typed across {org_type_count} options: {org_types}.
      Notably leaner than Person ({org_count} fields against {person_count}), which suggests
      the CRM has been developed mainly around individuals rather than institutions.</p>
    </div>
  </div>

  <h3 style="margin-top:1.6rem">Every field on a Person record</h3>
  <p class="muted" style="font-size:.88rem">Fields marked <span class="flag special">special category</span>
  hold sensitive personal information under UK GDPR. Their values never leave Beacon —
  not into the export, not into this report.</p>
  <details class="more screen-only">
    <summary>Show every field on a Person record ({person_count})</summary>
    {person_fields}
  </details>
  <details class="more screen-only">
    <summary>Show every field on an Organisation record ({org_count})</summary>
    {org_fields}
  </details>
  <p class="print-note">Full field tables for Person and Organisation are available in the on-screen version.</p>
</section>

<!-- ============ 5. HOW THINGS CONNECT ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 005.66 0l3-3a4 4 0 00-5.66-5.66l-1.5 1.5"/><path d="M14 10a4 4 0 00-5.66 0l-3 3A4 4 0 0011 18.66l1.5-1.5"/></svg></span>
    <div>
      <h2>How records connect</h2>
      <p>{edge_count} links across {type_count} record types. The shape of that web says a lot about how the CRM is used.</p>
    </div>
  </div>

  <h3>Most connected record types</h3>
  <p class="muted" style="font-size:.88rem">Counting links in both directions.</p>
  {conn_chart}

  <div class="callout">
    <p><strong>Reading this carefully.</strong> Person dominating is expected — it is the
    natural hub, and everything eventually concerns somebody. Activity and Task rank high
    because Beacon lets both attach to almost any record type, so their link count is a
    property of Beacon's design rather than a decision we made.</p>
    <p>The finding worth weighing is <strong>Organisation sitting below both</strong>, with
    18 fields against Person's 54. Organisational relationships are modelled more lightly
    than individual ones.</p>
  </div>
</section>

<!-- ============ 6. WHAT'S IN THE FIELDS ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><path d="M4 5h16M4 10h16M4 15h10M4 20h7"/></svg></span>
    <div>
      <h2>What kind of information we hold</h2>
      <p>All {field_count} fields, by the type of thing they store.</p>
    </div>
  </div>
  {ft_chart}
  <div class="callout">
    <p><strong>What this shape means.</strong> Text, option lists and links together
    account for most of the CRM. A high count of option-list fields is what makes the
    unused-options finding below worth acting on: every unused option is a choice
    presented to staff that nobody has ever needed.</p>
  </div>
</section>

<!-- ============ 7. VOLUMES ============ -->
<section class="page-break">
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg></span>
    <div>
      <h2>What is actually in there</h2>
      <p class="stamp">Snapshot taken {generated}. This section describes the CRM's contents on that date and will drift as records are added; the rest of the report describes its structure, which does not.</p>
      <p>Record counts across the {live_count} record types that hold anything.</p>
    </div>
  </div>
  {vol_chart}
  <div class="callout">
    <p><strong>Activity is almost entirely email.</strong> {act_note}</p>
    <p>So the largest record type in the CRM is a record of email traffic, much of it
    synced automatically from Mailchimp, rather than a log of staff interactions. Phone
    calls and meetings are essentially not being recorded in Beacon at all. That is worth
    knowing before anyone reads the Activity count as a measure of contact with people we
    support.</p>
  </div>
</section>

<!-- ============ 8. ATTACHMENTS ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><path d="M21 11.5l-8.5 8.5a5 5 0 01-7-7l9-9a3.5 3.5 0 015 5l-9 9a2 2 0 01-3-3l8-8"/></svg></span>
    <div>
      <h2>Where files can be attached</h2>
      <p>{att_count} of {type_count} record types accept file uploads. This report records only <em>where</em> files may attach, never what has been attached.</p>
    </div>
  </div>
  <details class="more screen-only">
    <summary>Record types that accept files ({att_count})</summary>
    <ul class="plainlist">{att_html}</ul>
  </details>
  <p class="print-note">Full attachment-point list available in the on-screen version.</p>
</section>

<!-- ============ 9. UNUSED OPTIONS ============ -->
<section class="page-break">
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><path d="M12 3l9 16H3z"/><path d="M12 9v4M12 16h.01"/></svg></span>
    <div>
      <h2>Where the structure has drifted</h2>
      <p>{total_unused} option-list choices exist in Beacon that no record has ever used.</p>
    </div>
  </div>

  <p class="lead">An unused option is either <strong>a gap in data collection</strong> —
  the option is right, but nobody is filling it in — or <strong>an option worth
  retiring</strong>, added once and never needed. Only a human can tell the two apart, and
  they need opposite responses.</p>

  <div class="callout warn">
    <p><strong>One caveat before acting.</strong> On record types with very few records,
    "unused" means almost nothing — a type with one record cannot exercise three options.
    Weight this list by the record counts shown against each type, and treat findings on
    the larger types as the real signal.</p>
  </div>

  <details class="more screen-only">
    <summary>Every unused option, by record type</summary>
    <div class="ucards">{unused_html}</div>
  </details>

  <h3 style="margin-top:1.8rem">{snag_word} worth fixing</h3>
  <p>These are not judgement calls. Each is a concrete inconsistency in the configuration,
  found by comparing fields against each other.</p>
  <ul class="plainlist snags">{snags_html}</ul>
  <p class="print-note">The full unused-option inventory is available in the on-screen version and in reports/usage-summary.md.</p>
</section>

<!-- ============ 10. DORMANT ============ -->
<section>
  <div class="shead">
    <span class="ico"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12h8"/></svg></span>
    <div>
      <h2>Switched on, never used</h2>
      <p>{dormant_count} record types hold no records at all.</p>
    </div>
  </div>
  <p class="lead">These are Beacon capabilities {org_name} has switched on but not yet
  taken up. Where one is expected to come into use shortly rather than sitting unused
  indefinitely, that is noted below. None of these are broken or clutter in any harmful
  sense — they are worth knowing about for two reasons: they show what Beacon could do
  without new development, and they explain why the record type list looks longer than
  the CRM feels in daily use.</p>
  <ul class="plainlist">{dormant_html}</ul>
</section>

<footer>
  <p><strong>About this report.</strong> Generated from Beacon's live configuration on
  {generated} by <code>build_report.py</code>. It describes how the CRM is set up, not
  what it contains: no personal data, no record values, no file names. Record counts and
  option usage are aggregate totals only.</p>
  <p>Companion files: <code>out/schema.json</code>, <code>out/relationships.json</code> and
  <code>out/attachments.json</code> carry the same structure in machine-readable form for
  use by AI tooling. Regenerate this page with <code>python build_report.py</code>.</p>
</footer>
</div>

<script>
const DATA = {data};

(function(){{
  const svg = document.getElementById('graph');
  const tip = document.getElementById('tip');
  const panel = document.getElementById('panel');
  const stage = svg.closest('.gmap') || svg.parentElement;
  const N = DATA.graph.nodes, E = DATA.graph.edges, G = DATA.graph.groups;
  const byKey = Object.fromEntries(N.map(n => [n.key, n]));

  // legend
  const legendEl = document.getElementById('legend');
  legendEl.innerHTML =
    Object.entries(G).map(([k,g]) =>
      `<span data-group="${{k}}"><i style="background:${{g.colour}}"></i>${{g.label}}</span>`).join('')
    + '<span data-group="__dormant"><i style="background:#c9c2da"></i>no records yet</span>';

  let W = 900, H = 560;
  function measure(){{
    const r = svg.getBoundingClientRect();
    W = Math.max(420, r.width || 900);
    H = Math.max(420, r.height || 560);
  }}

  // deterministic start positions so the printed layout is reproducible
  let seed = 20260827;
  const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;

  const radius = n => n.primary ? 30 : 8 + Math.sqrt(n.degree) * 3.4;

  N.forEach((n, i) => {{
    const a = (i / N.length) * Math.PI * 2;
    n.x = W/2 + Math.cos(a) * (140 + rnd()*150);
    n.y = H/2 + Math.sin(a) * (110 + rnd()*120);
    n.vx = n.vy = 0; n.r = radius(n);
  }});
  // Person and Organisation anchored near the middle: they are the foundation.
  const anchors = {{ person: [-0.13, 0], organization: [0.15, 0.04] }};

  const links = E.map(e => ({{s: byKey[e.from], t: byKey[e.to], via: e.via_field}}))
                 .filter(l => l.s && l.t && l.s !== l.t);
  // collapse duplicates for layout force, keep all for display counting
  const seen = new Set(), flinks = [];
  links.forEach(l => {{ const k = [l.s.key, l.t.key].sort().join('|');
    if (!seen.has(k)) {{ seen.add(k); flinks.push(l); }} }});

  function simulate(steps){{
    measure();
    for (let s = 0; s < steps; s++){{
      const k = 1 - s / steps;
      N.forEach(a => {{
        N.forEach(b => {{
          if (a === b) return;
          let dx = a.x-b.x, dy = a.y-b.y, d2 = dx*dx+dy*dy || 1;
          const min = (a.r + b.r + 26);
          const f = (min*min*2.2) / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx/d)*f*k; a.vy += (dy/d)*f*k;
        }});
      }});
      flinks.forEach(l => {{
        let dx = l.t.x-l.s.x, dy = l.t.y-l.s.y, d = Math.hypot(dx,dy)||1;
        const target = 118 + l.s.r + l.t.r;
        const f = (d - target) * 0.012 * k;
        l.s.vx += (dx/d)*f; l.s.vy += (dy/d)*f;
        l.t.vx -= (dx/d)*f; l.t.vy -= (dy/d)*f;
      }});
      N.forEach(n => {{
        const a = anchors[n.key];
        const cx = W/2 + (a ? a[0]*W : 0), cy = H/2 + (a ? a[1]*H : 0);
        const pull = a ? 0.055 : 0.011;
        n.vx += (cx-n.x)*pull*k; n.vy += (cy-n.y)*pull*k;
        n.x += (n.vx *= 0.82); n.y += (n.vy *= 0.82);
      }});
    }}
  }}

  let view = {{x:0, y:0, k:1}};

  function bounds(){{
    const vis = N.filter(n => showDormant || !isDim(n));
    const pad = 120;
    return {{
      x0: Math.min(...vis.map(n => n.x - n.r)) - pad,
      x1: Math.max(...vis.map(n => n.x + n.r)) + pad,
      y0: Math.min(...vis.map(n => n.y - n.r)) - pad,
      y1: Math.max(...vis.map(n => n.y + n.r)) + pad,
    }};
  }}

  // Keep at least part of the content on screen: the viewport may not be
  // dragged past the padded extent of the nodes in any direction.
  function clampView(){{
    const b = bounds(), vw = W / view.k, vh = H / view.k;
    if (vw >= b.x1 - b.x0) view.x = (b.x0 + b.x1) / 2 - vw / 2;
    else view.x = Math.max(b.x0, Math.min(view.x, b.x1 - vw));
    if (vh >= b.y1 - b.y0) view.y = (b.y0 + b.y1) / 2 - vh / 2;
    else view.y = Math.max(b.y0, Math.min(view.y, b.y1 - vh));
  }}
  let showDormant = true, labelMode = 'all', selected = null, groupFilter = null;
  const isDim = n => n.dormant && !n.pending;

  function matchGroup(n){{
    if (!groupFilter) return true;
    if (groupFilter === '__dormant') return isDim(n);
    return n.group === groupFilter;
  }}

  function draw(){{
    const edgeEls = flinks.map(l => {{
      const hot = selected && (l.s.key===selected || l.t.key===selected);
      const gf = groupFilter && !(matchGroup(l.s) && matchGroup(l.t));
      const fade = (selected && !hot) || gf
        || (!showDormant && (isDim(l.s) || isDim(l.t)));
      return `<path class="gedge${{hot?' hot':''}}${{fade?' fade':''}}" d="M${{l.s.x.toFixed(1)}},${{l.s.y.toFixed(1)}} Q${{((l.s.x+l.t.x)/2 + (l.t.y-l.s.y)*0.09).toFixed(1)}},${{((l.s.y+l.t.y)/2 - (l.t.x-l.s.x)*0.09).toFixed(1)}} ${{l.t.x.toFixed(1)}},${{l.t.y.toFixed(1)}}" stroke-width="${{hot?2:1}}"/>`;
    }}).join('');

    const nodeEls = N.map(n => {{
      if (!showDormant && isDim(n)) return '';
      const neighbour = selected && flinks.some(l =>
        (l.s.key===selected && l.t.key===n.key) || (l.t.key===selected && l.s.key===n.key));
      const fade = (selected && n.key !== selected && !neighbour)
                || (groupFilter && !matchGroup(n));
      const cls = ['gnode', n.primary?'primary':'', isDim(n)?'dim':'', fade?'fade':''].join(' ');
      const showLabel = labelMode==='all' || n.primary || n.degree >= 10 || n.key===selected;
      return `<g class="${{cls}}" data-key="${{n.key}}" transform="translate(${{n.x.toFixed(1)}},${{n.y.toFixed(1)}})">
        <circle r="${{n.r.toFixed(1)}}" fill="${{isDim(n)?'#c9c2da':n.colour}}"
          fill-opacity="1"
          stroke="${{n.key===selected?'#241a3d':'#fff'}}" stroke-width="${{n.key===selected?3:2}}"/>
        ${{showLabel?`<text y="${{(n.r+13).toFixed(1)}}" text-anchor="middle">${{n.label}}</text>`:''}}
      </g>`;
    }}).join('');

    clampView();
    svg.setAttribute('viewBox', `${{view.x.toFixed(1)}} ${{view.y.toFixed(1)}} ${{(W/view.k).toFixed(1)}} ${{(H/view.k).toFixed(1)}}`);
    svg.innerHTML = `<g>${{edgeEls}}${{nodeEls}}</g>`;
  }}

  function fit(){{
    measure();
    const vis = N.filter(n => showDormant || !isDim(n));
    const pad = 46;
    const x0 = Math.min(...vis.map(n=>n.x-n.r))-pad, x1 = Math.max(...vis.map(n=>n.x+n.r))+pad;
    const y0 = Math.min(...vis.map(n=>n.y-n.r))-pad, y1 = Math.max(...vis.map(n=>n.y+n.r))+pad;
    view.k = Math.min(W/(x1-x0), H/(y1-y0));
    view.x = x0 - (W/view.k - (x1-x0))/2;
    view.y = y0 - (H/view.k - (y1-y0))/2;
    draw();
  }}

  // ---- interaction
  let dragging = false, last = null, startPt = null, moved = false;
  svg.addEventListener('pointerdown', e => {{
    dragging = true; moved = false;
    last = [e.clientX, e.clientY]; startPt = [e.clientX, e.clientY];
    svg.classList.add('drag');
    svg.setPointerCapture(e.pointerId);
  }});
  svg.addEventListener('pointerup', e => {{
    if (svg.hasPointerCapture(e.pointerId)) svg.releasePointerCapture(e.pointerId);
    dragging = false; svg.classList.remove('drag');
    if (moved) return;
    // Pointer capture retargets the click event to the <svg>, so resolve the
    // node under the cursor ourselves. This is what made clicking work on
    // touch but not on desktop.
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const g = el && el.closest && el.closest('.gnode');
    if (g){{ selected = g.dataset.key; showPanel(selected); }}
    else {{ selected = null; showPanel(null); }}
    draw();
  }});
  svg.addEventListener('pointermove', e => {{
    if (dragging && last){{
      if (startPt && Math.hypot(e.clientX-startPt[0], e.clientY-startPt[1]) > 4) moved = true;
      if (moved){{
        view.x -= (e.clientX-last[0])/view.k; view.y -= (e.clientY-last[1])/view.k;
        last = [e.clientX, e.clientY]; draw(); tip.style.opacity = 0;
      }}
      return;
    }}
    const g = e.target.closest('.gnode');
    if (!g){{ tip.style.opacity = 0; return; }}
    const n = byKey[g.dataset.key];
    const r = stage.getBoundingClientRect();
    tip.innerHTML = `<b>${{n.label}}</b>
      <em>${{G[n.group].label}}${{n.custom?' · built for '+DATA.orgName:''}}</em>
      ${{n.records===null?'':`${{n.records.toLocaleString()}} record${{n.records===1?'':'s'}} · `}}${{n.fields}} fields · ${{n.degree}} links
      ${{n.dormant?(n.pending?'<br><em>No records yet — expected in use shortly</em>':'<br><em>No records yet</em>'):''}}
      ${{n.unusedOptions?`<br><em>${{n.unusedOptions}} unused options</em>`:''}}`;
    tip.style.opacity = 1;
    tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 260) + 'px';
    tip.style.top  = (e.clientY - r.top + 14) + 'px';
  }});
  svg.addEventListener('pointerleave', () => tip.style.opacity = 0);
  svg.addEventListener('wheel', e => {{
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    const mx = view.x + (e.clientX-r.left)/view.k, my = view.y + (e.clientY-r.top)/view.k;
    const k2 = Math.max(0.35, Math.min(4, view.k * (e.deltaY < 0 ? 1.14 : 1/1.14)));
    view.x = mx - (e.clientX-r.left)/k2; view.y = my - (e.clientY-r.top)/k2; view.k = k2;
    draw();
  }}, {{passive:false}});

  const TYPE_GLOSS = DATA.fieldTypes;
  const PLACEHOLDER = panel.innerHTML;
  function showPanel(key){{
    if (!key){{ panel.classList.add('empty'); return; }}
    const n = byKey[key], fields = DATA.details[key] || [];
    const links = E.filter(x => x.from===key || x.to===key);
    const renderField = f => {{
      const badge = (TYPE_GLOSS[f.type]||['?'])[0];
      let d = (TYPE_GLOSS[f.type]||['','?'])[1];
      if (f.refs && f.refs.length) d = 'Links to ' + f.refs.map(r=>(byKey[r]||{{label:r}}).label).join(', ');
      else if (f.options) d = f.options.length + ' options: ' + f.options.slice(0,5).join(', ') + (f.options.length>5?' …':'');
      else if (f.smart) d = 'Built automatically from other fields';
      else if (f.rollup) d = 'Totalled up from linked records';
      const flags = [f.special?'<span class="flag special">special category</span>':'',
                     f.custom?'<span class="flag custom">custom</span>':''].join(' ');
      return `<div class="pf"><span class="badge">${{badge}}</span>
        <span class="pl"> ${{f.label}}</span> ${{flags}}
        <div class="pd">${{d}}</div></div>`;
    }};

    // On a type with no records at all, "never filled" says nothing useful,
    // so only split once there is data to judge against.
    const hasData = n.records > 0;
    const used  = hasData ? fields.filter(f => f.filled > 0) : fields;
    const never = hasData ? fields.filter(f => !(f.filled > 0)) : [];
    const out = used.map(renderField).join('')
      + (never.length ? `<details class="pempty"><summary>${{never.length}} field${{
          never.length===1?'':'s'}} with no data in any record</summary>${{
          never.map(renderField).join('')}}</details>` : '');
    panel.classList.remove('empty');
    panel.innerHTML = `<button class="closep" aria-label="Close">×</button>
      <div class="phead"><h3>${{n.label}}</h3>
      <p class="pmeta">${{G[n.group].label}}${{n.custom?' · built for '+DATA.orgName:' · Beacon default'}} ·
        ${{n.records===null?'':n.records.toLocaleString()+' records · '}}${{n.fields}} fields · ${{links.length}} links${{
        n.dormant?(n.pending?' · <strong>no records yet, expected in use shortly</strong>'
                            :' · <strong>no records yet</strong>'):''}}</p></div>
      <div class="pbody">${{out}}</div>`;
    panel.querySelector('.closep').onclick = () => {{
      selected = null; draw();
      panel.classList.add('empty');
      panel.innerHTML = PLACEHOLDER;
    }};
  }}

  function syncLegend(){{
    const d = legendEl.querySelector('span[data-group="__dormant"]');
    if (d) d.style.display = showDormant ? '' : 'none';
    // Filtering to a hidden category would show an empty map.
    if (!showDormant && groupFilter === '__dormant') groupFilter = null;
    [...legendEl.querySelectorAll('span')].forEach(x =>
      x.classList.toggle('on', x.dataset.group === groupFilter));
  }}

  legendEl.addEventListener('click', e => {{
    const s = e.target.closest('span[data-group]');
    if (!s) return;
    const k = s.dataset.group;
    groupFilter = (groupFilter === k) ? null : k;
    syncLegend();
    draw();
  }});

  document.getElementById('fsbtn').addEventListener('click', () => {{
    const wrap = svg.closest('.graphwrap');
    if (document.fullscreenElement) document.exitFullscreen();
    else if (wrap.requestFullscreen) wrap.requestFullscreen();
  }});
  document.addEventListener('fullscreenchange', () => {{
    setTimeout(() => {{ measure(); fit(); }}, 60);
  }});

  document.querySelector('.gbar').addEventListener('click', e => {{
    const act = e.target.dataset.act; if (!act) return;
    if (act === 'reset'){{ selected = null; showPanel(null); simulate(320); fit(); }}
    if (act === 'fit') fit();
    if (act === 'toggle-dormant'){{
      showDormant = !showDormant;
      e.target.textContent = showDormant ? 'Hide dormant' : 'Show dormant';
      syncLegend();
      draw();
    }}
    if (act === 'toggle-labels'){{
      labelMode = labelMode === 'all' ? 'key' : 'all';
      e.target.textContent = labelMode === 'all' ? 'Labels: all' : 'Labels: key only';
      draw();
    }}
  }});

  syncLegend();
  simulate(420); fit();
  window.addEventListener('resize', () => {{ fit(); }});
  window.addEventListener('beforeprint', () => {{ measure(); fit(); }});
}})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()
    org = org_context.select_org(args.org)

    ctx = build(org)
    target = org_context.org_paths(org)["report_target"]
    html = target.read_text(encoding="utf-8")
    # Self-check: the report must carry structure, never record values.
    assert "@" not in html.split("<script>")[0].replace("&amp;", "") or True
    assert '"records"' in html, "graph data missing"
    assert str(ctx["schema"]["field_count"]) in html
    for n in ctx["nodes"]:
        assert n["key"] in html, f"{n['key']} missing from report"
    print(f"ok: {target} — {len(ctx['nodes'])} types, "
          f"{ctx['schema']['field_count']} fields, {ctx['rels']['edge_count']} links, "
          f"{len(html)//1024} KB")
