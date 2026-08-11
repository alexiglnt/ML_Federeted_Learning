"""End-to-end smoke test of lot 1: project creation."""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request

BASE = "http://localhost:8000"


def session():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


A = session()   # first researcher
B = session()   # second researcher
ANON = session()


def call(opener, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with opener.open(req) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw else None)


ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


import uuid
tag = uuid.uuid4().hex[:8]

print("== accounts ==")
for opener, who in ((A, "a"), (B, "b")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"Researcher {who.upper()}", "institution": "Lab " + who.upper(),
    })
    check(f"register {who}", status == 201, f"status={status}")

BASE_PROJECT = {
    "title": f"Residual stress in turning of Ti-6Al-4V {tag}",
    "description": "Seven conditions, and that is the problem.",
    "material": "Ti-6Al-4V", "process": "orthogonal turning",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "licence": "CC-BY-4.0",
    "inputs": [
        {"variable_key": "rake_angle", "required": True, "expected_min": -6, "expected_max": 10, "penalised_sign": -1},
        {"variable_key": "edge_radius", "required": True, "expected_min": 16, "expected_max": 30},
        {"variable_key": "cutting_speed", "required": True, "expected_min": 20, "expected_max": 60},
        {"variable_key": "uncut_chip_thickness", "required": True},
    ],
    "targets": [
        {"variable_key": "residual_stress_axial"},
        {"variable_key": "residual_stress_circumferential"},
    ],
}

print("\n== creation ==")
status, project = call(A, "/api/projects", BASE_PROJECT)
check("create", status == 201, f"status={status} {project if status != 201 else ''}")
slug = (project or {}).get("slug")
check("slug derived from title", slug and slug.startswith("residual-stress-in-turning-of-ti-6al-4v"), slug)
check("starts as draft", (project or {}).get("status") == "draft")
check("creator is owner", (project or {}).get("viewer_role") == "owner")
check("owner may read raw data", (project or {}).get("viewer_can_read_raw_data") is True)
check("two targets kept", len((project or {}).get("targets", [])) == 2)

order = [i["variable"]["key"] for i in (project or {}).get("inputs", [])]
check("input order preserved", order == ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"], str(order))
positions = [i["position"] for i in (project or {}).get("inputs", [])]
check("positions are 0..3", positions == [0, 1, 2, 3], str(positions))

signs = {i["variable"]["key"]: i["penalised_sign"] for i in (project or {}).get("inputs", [])}
check("explicit prior kept", signs.get("rake_angle") == -1.0, str(signs.get("rake_angle")))
check("prior falls back to registry suggestion",
      signs.get("cutting_speed") == 1.0, str(signs.get("cutting_speed")))
units = {i["variable"]["key"]: i["unit"] for i in (project or {}).get("inputs", [])}
check("unit falls back to registry", units.get("cutting_speed") == "m/min", str(units.get("cutting_speed")))

print("\n== slug collisions ==")
status, second = call(B, "/api/projects", BASE_PROJECT)
check("same title by another user creates a distinct project", status == 201, f"status={status}")
check("slug is suffixed, not reused", (second or {}).get("slug") != slug, f"{slug} vs {(second or {}).get('slug')}")

print("\n== validation ==")
bad = dict(BASE_PROJECT, title=f"Overlap {tag}",
           inputs=[{"variable_key": "cutting_speed", "required": True}],
           targets=[{"variable_key": "cutting_speed"}])
status, body = call(A, "/api/projects", bad)
check("variable cannot be input and target", status == 422, f"status={status}")

bad = dict(BASE_PROJECT, title=f"Dup input {tag}",
           inputs=[{"variable_key": "cutting_speed", "required": True},
                   {"variable_key": "cutting_speed", "required": True}])
status, _ = call(A, "/api/projects", bad)
check("duplicate input rejected", status == 422, f"status={status}")

bad = dict(BASE_PROJECT, title=f"Unknown {tag}",
           inputs=[{"variable_key": "does_not_exist", "required": True}])
status, body = call(A, "/api/projects", bad)
check("unknown variable rejected", status == 422, f"status={status}")

status, _ = call(ANON, "/api/projects", dict(BASE_PROJECT, title=f"Anon {tag}"))
check("anonymous cannot create", status == 401, f"status={status}")

print("\n== proposed variables are private until moderated ==")
status, proposed = call(A, "/api/variables", {
    "key": f"weird_quantity_{tag}", "display_name": f"Weird quantity {tag}",
    "unit": "mm", "dimension": "length",
})
check("A proposes a variable", status == 201, f"status={status}")
key = (proposed or {}).get("key")
check("it is marked proposed", (proposed or {}).get("status") == "proposed")

status, _ = call(A, "/api/projects", dict(
    BASE_PROJECT, title=f"Uses own proposal {tag}",
    inputs=[{"variable_key": key, "required": True}]))
check("proposer may use it immediately", status == 201, f"status={status}")

status, body = call(B, "/api/projects", dict(
    BASE_PROJECT, title=f"Steals proposal {tag}",
    inputs=[{"variable_key": key, "required": True}]))
check("someone else may not use it yet", status == 422, f"status={status}")

print("\n== listing and reading ==")
status, listed = call(ANON, "/api/projects")
check("public list works signed out", status == 200 and isinstance(listed, list))
check("our project is listed", any(p["slug"] == slug for p in listed or []))

status, mine = call(A, "/api/projects/mine")
check("'mine' is not read as a slug", status == 200, f"status={status}")
# A made five create attempts; three were rejected (overlap, duplicate input,
# unknown variable), so exactly two projects should exist.
check("A owns exactly the 2 projects that were accepted", len(mine or []) == 2, str(len(mine or [])))
check("'mine' contains our project", any(p["slug"] == slug for p in mine or []))
check("'mine' excludes B's project", all(p["slug"] != (second or {}).get("slug") for p in mine or []))

status, seen = call(ANON, f"/api/projects/{slug}")
check("anonymous can read the declaration", status == 200)
check("anonymous has no role", (seen or {}).get("viewer_role") is None)
check("anonymous cannot use the model", (seen or {}).get("viewer_can_use_model") is False)
check("anonymous cannot read raw data", (seen or {}).get("viewer_can_read_raw_data") is False)

status, other = call(B, f"/api/projects/{slug}")
check("another user sees the declaration but no role", status == 200 and (other or {}).get("viewer_role") is None)
check("another user cannot read raw data", (other or {}).get("viewer_can_read_raw_data") is False)

status, _ = call(ANON, "/api/projects/no-such-project-anywhere")
check("missing project is 404", status == 404, f"status={status}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
