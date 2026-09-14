"""Read-only Beacon API client.

Hard rule: this module can only issue GET. There is no code path here that
sends any other verb, and urlopen is called with a Request whose method is
fixed. Do not add one.
"""

import json
import os
import time
import urllib.error
import urllib.request

import org_context

BASE = "https://api.beaconcrm.org/v1/account"

# 300 req/min is the documented ceiling; 4/sec leaves plenty of headroom.
_MIN_INTERVAL = 0.25
_last_call = 0.0

# Set once per process via set_org(). Every call below is scoped to this org.
_org = None


def set_org(org):
    """Pick which org's credentials and raw schema every call below uses."""
    global _org
    _org = org


def _env():
    """Read orgs/<org>/.env.local. Never logged, never returned to a caller that prints."""
    if _org is None:
        raise SystemExit("beacon.set_org(...) must be called before beacon.get()/load_schema().")
    path = org_context.org_paths(_org)["env_file"]
    if not path.exists():
        raise SystemExit(f"{path} not found. Create it with BEACON_API_KEY and BEACON_ACCOUNT_ID.")
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    key = env.get("BEACON_API_KEY") or os.environ.get("BEACON_API_KEY")
    account = env.get("BEACON_ACCOUNT_ID") or os.environ.get("BEACON_ACCOUNT_ID")
    if not key or not account:
        raise SystemExit("BEACON_API_KEY and BEACON_ACCOUNT_ID must both be set.")
    return key, account


def get(path, **params):
    """GET {BASE}/{account}/{path}. The only network call in this project."""
    global _last_call
    key, account = _env()
    url = f"{BASE}/{account}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)

    req = urllib.request.Request(url, method="GET")  # ponytail: GET is hardcoded, on purpose
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Beacon-Application", "developer_api")
    req.add_header("Content-Type", "application/json")

    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                _last_call = time.monotonic()
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            _last_call = time.monotonic()
            if e.code == 429 and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            # Never include the URL: it carries the account id, and a stray
            # header dump would carry the key.
            raise SystemExit(f"Beacon API returned HTTP {e.code} for /{path}")
        except urllib.error.URLError as e:
            if attempt < 3:
                time.sleep(3)
                continue
            raise SystemExit(f"Network error calling /{path}: {e.reason}")


def pages(entity_type_key, populate=False):
    """Yield each page of records for an entity type. Caller must not persist them."""
    page = 1
    while True:
        data = get(f"entities/{entity_type_key}", page=page,
                   populate="true" if populate else "false")
        results = data.get("results", [])
        if not results:
            return
        yield results
        if page * 200 >= data.get("total", 0):
            return
        page += 1


def load_schema():
    """Prefer the committed raw schema; fall back to a live fetch."""
    raw = org_context.org_paths(_org)["raw_schema"]
    if raw.exists():
        return json.loads(raw.read_text(encoding="utf-8-sig"))
    return get("entity_types")


import urllib.parse  # noqa: E402  (used by get(); kept low to avoid shadowing)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--org")
    args = parser.parse_args()
    set_org(org_context.select_org(args.org))

    # Self-check: the client refuses to be talked into a non-GET verb.
    import inspect
    src = inspect.getsource(get)
    assert 'method="GET"' in src, "GET must stay hardcoded"
    for verb in ("POST", "PATCH", "PUT", "DELETE"):
        assert verb not in src, f"{verb} must never appear in the client"
    s = load_schema()
    assert s["total"] == len(s["results"]), "total must match result count"
    print(f"ok: read-only client, {s['total']} entity types, "
          f"{sum(len(e['fields']) for e in s['results'])} fields")
