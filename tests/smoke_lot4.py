"""End-to-end smoke test of lot 4: faceted discovery and "match my file".

The half that matters is the reverse search. A researcher does not know which
projects exist — they know what they measured — so the load-bearing behaviour
is that dropping a file ranks projects sensibly, reports *parts* rather than a
verdict, and stores nothing.

Everything here is tagged, including the materials and processes, so the facet
counts can be asserted exactly against a database that other runs have already
written to.
"""
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
tag = uuid.uuid4().hex[:8]

MATERIAL = f"Alloy-{tag}"
PROCESS = f"turning-{tag}"


def session():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


OWNER, ANON = session(), session()
ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


def call(opener, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with opener.open(req) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, (json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return e.code, raw


def post_file(opener, path, filename, content: bytes):
    boundary = "----mlfl" + uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n", content,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Accept": "application/json"},
    )
    try:
        with opener.open(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, (json.loads(raw) if raw else None)
        except json.JSONDecodeError:
            return e.code, raw


def wait_for_version(slug, minimum, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, versions = call(ANON, f"/api/projects/{slug}/versions")
        if status == 200 and versions and versions[0]["number"] >= minimum:
            return versions
        time.sleep(1.5)
    return None


def slugs(rows):
    return [row["slug"] for row in (rows or [])]


# The literal headings of the source study: Greek letters, units in the name.
# Matching has to survive this on the discovery path too, not only on upload.
HEADER = "γ (°),rβ (µm),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa),zzz_unknown_column\n"
NEAR_ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
    (-6, 30, 60, 0.15, -479.0, 57.0), (0, 20, 40, 0.18, -350.0, 20.0),
    (2, 24, 30, 0.16, -390.0, 5.0), (8, 28, 50, 0.19, -430.0, 35.0),
]
# Same quantities, a regime the project has no data for: every row sits outside
# on cutting speed while staying inside on everything else.
FAR_ROWS = [
    (3, 18, 150, 0.15, -500.0, 10.0), (3, 26, 200, 0.20, -505.0, 12.0),
    (6, 18, 200, 0.15, -510.0, 14.0), (6, 26, 150, 0.20, -515.0, 16.0),
    (3, 22, 175, 0.18, -520.0, 18.0), (6, 22, 175, 0.16, -525.0, 20.0),
    (4, 20, 160, 0.19, -530.0, 22.0), (5, 24, 190, 0.15, -535.0, 24.0),
    (3, 26, 150, 0.17, -540.0, 26.0), (6, 18, 200, 0.20, -545.0, 28.0),
]


def to_csv(rows):
    return (HEADER + "".join(
        ",".join(str(v) for v in row) + ",note\n" for row in rows
    )).encode("utf-8")


FOUR_INPUTS = ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"]
TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]

print("== setup ==")
status, _ = call(OWNER, "/api/auth/register", {
    "email": f"owner-4-{tag}@example.com", "password": "a-long-enough-password",
    "full_name": f"Owner {tag}", "institution": "Somewhere",
})
check("register owner", status == 201, f"status={status}")

# A registry quantity this file does not carry, so one project can be a
# deliberately partial match. Picked from the live registry rather than assumed.
status, registry = call(ANON, "/api/variables")
approved = [v["key"] for v in (registry or []) if v["status"] == "approved"]
extra = next((k for k in approved if k not in FOUR_INPUTS + TARGETS), None)
check("found a registry quantity absent from the file", extra is not None, str(extra))


def create(title, material, process, inputs, targets, visibility="public"):
    status, body = call(OWNER, "/api/projects", {
        "title": title, "material": material, "process": process,
        "visibility": visibility, "main_engine": "piml", "accepts_federated": True,
        "inputs": [{"variable_key": k, "required": True} for k in inputs],
        "targets": [{"variable_key": k} for k in targets],
    })
    return status, (body or {}).get("slug")


status, full_slug = create(f"Full match {tag}", MATERIAL, PROCESS, FOUR_INPUTS, TARGETS)
check("create the fully matching project", status == 201, f"status={status}")

status, small_slug = create(
    f"Small match {tag}", f"Other-{tag}", f"milling-{tag}",
    ["cutting_speed", "uncut_chip_thickness"], ["residual_stress_axial"],
)
check("create a two-input project", status == 201, f"status={status}")

status, partial_slug = create(
    f"Partial match {tag}", f"Other-{tag}", f"milling-{tag}",
    ["cutting_speed", "uncut_chip_thickness", extra], ["residual_stress_axial"],
)
check("create a partially matching project", status == 201, f"status={status}")

status, hidden_slug = create(
    f"Unlisted {tag}", MATERIAL, PROCESS, FOUR_INPUTS, TARGETS, visibility="unlisted",
)
check("create an unlisted project", status == 201, f"status={status}")

# Only the first project gets data, so size and model filters have something to
# separate. It also gives the domain fraction something to measure against.
status, preview = post_file(OWNER, f"/api/projects/{full_slug}/uploads", "owner.csv",
                            to_csv(NEAR_ROWS))
check("owner uploads to the full project", status == 200, f"status={status}")
mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
check("all six quantities were matched from Greek headings", len(mapping) == 6, str(mapping))
status, _ = call(OWNER, f"/api/projects/{full_slug}/datasets", {
    "upload_token": preview["upload_token"], "mapping": mapping, "mode": "shared",
})
check("data committed", status == 201, f"status={status}")
check("a model was trained", wait_for_version(full_slug, 1) is not None)

# --------------------------------------------------------------------------- #
print("\n== facets are built from the data ==")
status, facets = call(ANON, "/api/projects/facets")
check("facets are public", status == 200, f"status={status}")
materials = {item["value"]: item["count"] for item in (facets or {}).get("materials", [])}
processes = {item["value"]: item["count"] for item in (facets or {}).get("processes", [])}
check("our material appears once", materials.get(MATERIAL) == 1, str(materials.get(MATERIAL)))
check("our process appears once", processes.get(PROCESS) == 1, str(processes.get(PROCESS)))
check("the unlisted project is not counted in its material",
      materials.get(MATERIAL) == 1, f"{MATERIAL}={materials.get(MATERIAL)}")

target_keys = {item["key"] for item in (facets or {}).get("targets", [])}
input_keys = {item["key"] for item in (facets or {}).get("inputs", [])}
check("targets are offered as facets", set(TARGETS) <= target_keys, str(sorted(target_keys))[:120])
check("inputs are offered as facets", set(FOUR_INPUTS) <= input_keys, str(sorted(input_keys))[:120])
check("facet variables carry a label and unit",
      all(item.get("display_name") for item in (facets or {}).get("inputs", [])))

# --------------------------------------------------------------------------- #
print("\n== faceted search ==")
status, rows = call(ANON, f"/api/projects?material={MATERIAL}")
check("filter by material", status == 200 and slugs(rows) == [full_slug], str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?process={PROCESS}")
check("filter by process", slugs(rows) == [full_slug], str(slugs(rows)))

status, rows = call(ANON, "/api/projects?target=residual_stress_circumferential"
                          f"&material={MATERIAL}")
check("filter by target quantity", slugs(rows) == [full_slug], str(slugs(rows)))

# Inputs accumulate: the question is "which projects can use my columns", and a
# project missing one of them cannot.
status, rows = call(ANON, "/api/projects?input=cutting_speed&input=rake_angle"
                          f"&material={MATERIAL}")
check("two inputs are required together", slugs(rows) == [full_slug], str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?input=cutting_speed&material=Other-{tag}")
check("one shared input matches both small projects",
      set(slugs(rows)) == {small_slug, partial_slug}, str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?input=rake_angle&material=Other-{tag}")
check("an input neither declares matches nothing", slugs(rows) == [], str(slugs(rows)))

status, rows = call(ANON, f"/api/projects?min_rows=5&material={MATERIAL}")
check("size filter keeps the project with data", slugs(rows) == [full_slug], str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?min_rows=5&material=Other-{tag}")
check("and drops the ones without", slugs(rows) == [], str(slugs(rows)))

status, rows = call(ANON, f"/api/projects?has_model=true&material={MATERIAL}")
check("has_model=true finds the trained project", slugs(rows) == [full_slug], str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?has_model=false&material={MATERIAL}")
check("has_model=false excludes it", slugs(rows) == [], str(slugs(rows)))
status, rows = call(ANON, f"/api/projects?has_model=false&material=Other-{tag}")
check("and finds the untrained ones", set(slugs(rows)) == {small_slug, partial_slug},
      str(slugs(rows)))

status, rows = call(ANON, f"/api/projects?q=Full match {tag}".replace(" ", "%20"))
check("text search still works", slugs(rows) == [full_slug], str(slugs(rows)))

status, rows = call(ANON, "/api/projects?sort=rows&limit=200")
listed = slugs(rows)
check("an unlisted project never appears in search", hidden_slug not in listed,
      f"{hidden_slug} in results")
if full_slug in listed and small_slug in listed:
    check("sorting by size puts data first",
          listed.index(full_slug) < listed.index(small_slug),
          f"full at {listed.index(full_slug)}, small at {listed.index(small_slug)}")

# --------------------------------------------------------------------------- #
print("\n== match my file ==")
# Asked for a deep page on purpose. This database accumulates projects from
# every previous run, many of them structurally identical and therefore tied at
# the top; the assertions below are about the *ranking*, not about what fits on
# the first page.
status, result = post_file(ANON, "/api/projects/match?limit=200", "mine.csv",
                           to_csv(NEAR_ROWS))
check("matching needs no account", status == 200, f"status={status}")

status, capped = post_file(ANON, "/api/projects/match?limit=1", "mine.csv",
                           to_csv(NEAR_ROWS))
check("the result count can be capped", len((capped or {}).get("matches", [])) == 1,
      str(len((capped or {}).get("matches", []))))

detected = {item["variable_key"]: item for item in (result or {}).get("detected", [])}
check("the four inputs were recognised from Greek headings",
      set(FOUR_INPUTS) <= set(detected), str(sorted(detected)))
check("so were both targets", set(TARGETS) <= set(detected), str(sorted(detected)))
check("a heading nobody recognises is reported rather than dropped",
      "zzz_unknown_column" in (result or {}).get("unmatched_columns", []),
      str((result or {}).get("unmatched_columns")))
check("each detection carries a confidence, not a verdict",
      all("confidence" in item and "exact" in item for item in detected.values()))
check("the numbers behind each column were counted",
      detected["cutting_speed"]["n_values"] == 10,
      str(detected["cutting_speed"]["n_values"]))

by_slug = {m["project"]["slug"]: m for m in (result or {}).get("matches", [])}
check("the fully matching project is ranked", full_slug in by_slug, str(list(by_slug))[:160])
check("the unlisted project is never ranked", hidden_slug not in by_slug)

full = by_slug.get(full_slug, {})
check("all four of its inputs matched", full.get("inputs_matched") == 4
      and full.get("inputs_total") == 4, str(full)[:160])
check("both of its targets are in the file", len(full.get("matched_targets", [])) == 2,
      str(full.get("matched_targets")))
check("nothing required is missing", full.get("missing_required_inputs") == [],
      str(full.get("missing_required_inputs")))
check("the whole file sits inside its covered domain",
      full.get("fraction_in_domain") == 1.0
      and full.get("rows_in_domain") == full.get("rows_scanned") == 10,
      f"{full.get('rows_in_domain')}/{full.get('rows_scanned')}")

partial = by_slug.get(partial_slug, {})
check("a partial match is reported as partial",
      partial.get("inputs_matched") == 2 and partial.get("inputs_total") == 3,
      str(partial)[:160])
check("and names what is missing", partial.get("missing_required_inputs") == [extra],
      str(partial.get("missing_required_inputs")))
check("a project with no data has no domain fraction rather than a fake one",
      partial.get("fraction_in_domain") is None, str(partial.get("fraction_in_domain")))

check("the complete match outranks the partial one",
      full.get("score", 0) > partial.get("score", 1),
      f"full={full.get('score')} partial={partial.get('score')}")
scores = [m["score"] for m in (result or {}).get("matches", [])]
check("results come back ordered", scores == sorted(scores, reverse=True), str(scores[:6]))

print("\n== data from an uncovered regime still matches ==")
status, far = post_file(ANON, "/api/projects/match?limit=200", "far.csv", to_csv(FAR_ROWS))
check("the far file matches too", status == 200, f"status={status}")
far_full = next(
    (m for m in (far or {}).get("matches", []) if m["project"]["slug"] == full_slug), {}
)
check("its inputs still all match", far_full.get("inputs_matched") == 4, str(far_full)[:120])
# This is the signal that marks the most valuable kind of contribution there
# is. It must be reported, and it must not be reported as a failure.
check("but none of it falls inside the covered domain",
      far_full.get("fraction_in_domain") == 0.0, str(far_full.get("fraction_in_domain")))
check("the rows were still counted", far_full.get("rows_scanned") == 10,
      str(far_full.get("rows_scanned")))

print("\n== matching stores nothing ==")
status, detail = call(ANON, f"/api/projects/{full_slug}")
check("the project's row count is untouched", (detail or {}).get("n_rows_total") == 10,
      str((detail or {}).get("n_rows_total")))
status, contributions = call(OWNER, f"/api/projects/{full_slug}/contributions")
check("no contribution was recorded by matching", len(contributions or []) == 1,
      str(len(contributions or [])))
status, versions = call(ANON, f"/api/projects/{full_slug}/versions")
check("and no retrain was triggered", len(versions or []) == 1, str(len(versions or [])))

print("\n== refusals ==")
status, _ = post_file(ANON, "/api/projects/match", "notes.pdf", b"%PDF-1.4 nonsense")
check("an unsupported file type is refused", status == 415, f"status={status}")
status, _ = post_file(ANON, "/api/projects/match", "empty.csv", b"")
check("an empty file is refused", status == 400, f"status={status}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
