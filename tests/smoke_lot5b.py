"""End-to-end smoke test of lot 5b: contributing without handing over the data.

Three claims are checked, and they are the three the mode exists for.

**Exactness (§5.1).** Fitting the reference model from summed sufficient
statistics gives the *same coefficients* as fitting on the pooled raw rows. Not
close — the same. `check_aggregation.py` proves the arithmetic in isolation;
this proves it survives the whole round trip through HTTP, JSONB and a
background retrain. Two projects are built from identical measurements, one
receiving half of them as a file and half as sums, the other receiving all of
them as one file, and their published coefficients are compared.

**The incentive holds (§4).** A federated contribution is credited, widens the
published validity domain and feeds the reference model — and unlocks **no**
model access. If that ever inverts, sharing data stops being worth anything.

**The double-counting trap (§5.5).** A contributor who sent sums and later
shares their file stays one row whose mode changes. If it ever became two rows,
their measurements would enter the reference model twice, silently, and the
coefficients would simply be wrong.

The summaries below are computed in pure Python, the way the browser computes
them in JavaScript — deliberately not by importing the server's own code, so
this is a check of the contract rather than of one implementation against
itself.
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


def session():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


OWNER, COLLEAGUE, ANON = session(), session(), session()
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


def fetch_bytes(opener, path):
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with opener.open(req) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def upload(opener, slug, filename, content: bytes):
    boundary = "----mlfl" + uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n", content,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        f"{BASE}/api/projects/{slug}/uploads", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Accept": "application/json"},
    )
    try:
        with opener.open(req) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def wait_for_version(slug, minimum, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, versions = call(ANON, f"/api/projects/{slug}/versions")
        if status == 200 and versions and versions[0]["number"] >= minimum:
            return versions
        time.sleep(1.5)
    return None


def sufficient_statistics(X, y):
    """n, D'D, D'y, y'y with D = [1, X]. What the browser transmits.

    Written out longhand on purpose: this is the contract a JavaScript client
    has to meet, so computing it with the server's own helper would prove
    nothing about whether the contract is right.
    """
    n = len(X)
    width = len(X[0]) + 1
    design = [[1.0] + [float(v) for v in row] for row in X]
    dtd = [[sum(design[k][i] * design[k][j] for k in range(n)) for j in range(width)]
           for i in range(width)]
    dty = [sum(design[k][i] * float(y[k]) for k in range(n)) for i in range(width)]
    return {"n": n, "dtd": dtd, "dty": dty, "yty": sum(float(v) ** 2 for v in y)}


HEADER = "gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)\n"
OWNER_ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
    (-6, 30, 60, 0.15, -479.0, 57.0), (0, 20, 40, 0.18, -350.0, 20.0),
    (2, 24, 30, 0.16, -390.0, 5.0), (8, 28, 50, 0.19, -430.0, 35.0),
]
COLLEAGUE_ROWS = [
    (3, 18, 90, 0.15, -500.0, 10.0), (3, 26, 120, 0.20, -505.0, 12.0),
    (6, 18, 130, 0.15, -510.0, 14.0), (6, 26, 95, 0.20, -515.0, 16.0),
    (3, 22, 110, 0.18, -520.0, 18.0), (6, 22, 105, 0.16, -525.0, 20.0),
    (4, 20, 100, 0.19, -530.0, 22.0), (5, 24, 125, 0.15, -535.0, 24.0),
    (3, 26, 85, 0.17, -540.0, 26.0), (6, 18, 115, 0.20, -545.0, 28.0),
]


def to_csv(rows):
    return (HEADER + "".join(",".join(str(v) for v in r) + "\n" for r in rows)).encode()


INPUT_KEYS = ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"]
TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]
IN_DOMAIN = {"rake_angle": 0, "edge_radius": 22,
             "cutting_speed": 40, "uncut_chip_thickness": 0.17}


def stats_payload(rows):
    X = [row[:4] for row in rows]
    return {
        TARGETS[0]: sufficient_statistics(X, [row[4] for row in rows]),
        TARGETS[1]: sufficient_statistics(X, [row[5] for row in rows]),
    }


def ranges(rows):
    return {
        key: [min(row[i] for row in rows), max(row[i] for row in rows)]
        for i, key in enumerate(INPUT_KEYS)
    }


def create(title, accepts_federated=True):
    # `penalised_sign: 0` explicitly, meaning "no prior". Omitting it would not
    # do: project creation falls back to the registry's suggested prior, and
    # every one of these four quantities carries one, so the reference engine
    # would silently be PIML.
    #
    # That matters for the exactness comparison below. PIML selects its lambda
    # by cross-validation over whatever rows are locally available, so a project
    # holding ten shared rows plus a summary would legitimately choose a
    # different lambda from one holding all twenty as rows — and the comparison
    # would be measuring hyperparameter selection rather than the aggregation.
    # Least squares has no hyperparameter, so any disagreement is the algebra.
    status, body = call(OWNER, "/api/projects", {
        "title": title, "material": "Ti-6Al-4V", "process": "turning",
        "visibility": "public", "main_engine": "linear",
        "accepts_federated": accepts_federated,
        "inputs": [{"variable_key": k, "required": True, "penalised_sign": 0}
                   for k in INPUT_KEYS],
        "targets": [{"variable_key": k} for k in TARGETS],
    })
    return status, (body or {}).get("slug")


def commit_file(opener, slug, rows, filename):
    status, preview = upload(opener, slug, filename, to_csv(rows))
    if status != 200:
        return status, preview
    mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
    return call(opener, f"/api/projects/{slug}/datasets", {
        "upload_token": preview["upload_token"], "mapping": mapping, "mode": "shared",
    })


def reference_coefficients(opener, slug, target):
    status, version = call(opener, f"/api/projects/{slug}/model")
    if status != 200:
        return None
    for model in version["models"]:
        if model["track"] == "reference" and model["target_key"] == target:
            return model["coefficients"]
    return None


print("== setup ==")
for opener, who in ((OWNER, "owner"), (COLLEAGUE, "colleague")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-5b-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}", "institution": f"{who.title()} Lab",
    })
    check(f"register {who}", status == 201, f"status={status}")

status, federated_slug = create(f"Federated {tag}")
check("create the federated project", status == 201, f"status={status}")
status, pooled_slug = create(f"Pooled control {tag}")
check("create the pooled control project", status == 201, f"status={status}")

status, owner_contribution = commit_file(OWNER, federated_slug, OWNER_ROWS, "owner.csv")
check("owner seeds the federated project", status == 201, f"status={status}")
check("a first model was published", wait_for_version(federated_slug, 1) is not None)

# The control receives every measurement as one ordinary file.
status, _ = commit_file(OWNER, pooled_slug, OWNER_ROWS + COLLEAGUE_ROWS, "everything.csv")
check("control project holds all twenty rows", status == 201, f"status={status}")
check("and trained", wait_for_version(pooled_slug, 1) is not None)

# --------------------------------------------------------------------------- #
print("\n== summaries are checked, not trusted ==")
good = stats_payload(COLLEAGUE_ROWS)
bounds = ranges(COLLEAGUE_ROWS)


def submit(stats, feature_ranges=None, opener=COLLEAGUE):
    return call(opener, f"/api/projects/{federated_slug}/federated", {
        "stats": stats, "feature_ranges": feature_ranges or bounds,
        "measurement_method": "hole-drilling",
    })


broken = json.loads(json.dumps(good))
broken[TARGETS[0]]["dtd"] = [row[:-1] for row in broken[TARGETS[0]]["dtd"][:-1]]
status, body = submit(broken)
check("a design matrix of the wrong size is refused", status == 422, f"status={status}")

broken = json.loads(json.dumps(good))
broken[TARGETS[0]]["dtd"][0][0] += 5
status, _ = submit(broken)
check("D'D[0,0] must equal the row count", status == 422, f"status={status}")

broken = json.loads(json.dumps(good))
broken[TARGETS[0]]["dtd"][0][1] += 1000.0
status, _ = submit(broken)
check("an asymmetric D'D is refused", status == 422, f"status={status}")

broken = json.loads(json.dumps(good))
broken[TARGETS[0]]["yty"] = 1.0
status, _ = submit(broken)
# y'y far too small for the given D'y implies a negative residual sum of
# squares, which no dataset can produce.
check("mutually inconsistent sums are refused", status == 422, f"status={status}")

broken = json.loads(json.dumps(good))
for key in broken:
    broken[key]["n"] = 2
    broken[key]["dtd"][0][0] = 2
status, _ = submit(broken)
check("too few rows to be anonymous is refused", status == 422, f"status={status}")

lying = {key: [value[0], value[1]] for key, value in bounds.items()}
lying["cutting_speed"] = [0.0, 1.0]
status, _ = submit(good, feature_ranges=lying)
check("a fabricated validity range is caught by the sums", status == 422, f"status={status}")

status, _ = call(COLLEAGUE, f"/api/projects/{federated_slug}/federated", {
    "stats": {"not_a_target_here": good[TARGETS[0]]}, "feature_ranges": bounds,
})
check("statistics for a quantity the project does not predict are refused",
      status == 422, f"status={status}")

# --------------------------------------------------------------------------- #
print("\n== a real summary is accepted ==")
status, contribution = submit(good)
check("the contribution is recorded", status == 201, f"status={status}")
contribution_id = (contribution or {}).get("id")
check("in federated mode", (contribution or {}).get("mode") == "federated",
      str((contribution or {}).get("mode")))
check("and pending review", (contribution or {}).get("status") == "pending",
      str((contribution or {}).get("status")))
check("with no file attached", (contribution or {}).get("original_filename") is None,
      str((contribution or {}).get("original_filename")))

transfer = (contribution or {}).get("transfer_score") or {}
refit = (contribution or {}).get("refit_score") or {}
check("the server computed a transfer score from the sums",
      (transfer.get("per_target", {}).get(TARGETS[0]) or {}).get("r2") is not None,
      str(transfer)[:140])
check("against the version published at the time", transfer.get("version") == 1,
      str(transfer.get("version")))
check("and a refit score", (refit.get("per_target", {}).get(TARGETS[0]) or {}).get("r2_train")
      is not None, str(refit)[:140])
# Honest about what summed statistics cannot do.
check("which says it is not cross-validated", "not a cross-validated" in (refit.get("note") or ""),
      str(refit.get("note"))[:120])

status, _ = fetch_bytes(OWNER, f"/api/projects/{federated_slug}/contributions/{contribution_id}/download")
check("there is no file for the owner to download", status == 404, f"status={status}")

# Checked against a throwaway project, never the control: posting statistics as
# the owner would auto-accept them, and the control has to stay exactly the
# pooled twenty rows for the exactness comparison to mean anything.
status, closed_slug = create(f"No federated {tag}", accepts_federated=False)
check("a project can refuse this mode", status == 201, f"status={status}")
status, _ = call(COLLEAGUE, f"/api/projects/{closed_slug}/federated",
                 {"stats": good, "feature_ranges": bounds})
check("and then turns the contribution away", status == 409, f"status={status}")

# --------------------------------------------------------------------------- #
print("\n== accepted: credited, counted, and still locked out ==")
status, result = call(
    OWNER, f"/api/projects/{federated_slug}/contributions/{contribution_id}/review",
    {"decision": "accept", "note": "Summary statistics, different speed regime."})
check("the owner accepts it", status == 200, f"status={status}")
# The incentive gradient the whole platform runs on.
check("accepting grants NO model access", (result or {}).get("access_granted") is False,
      str((result or {}).get("access_granted")))
check("a retrain was queued", (result or {}).get("training_job") is not None)

versions = wait_for_version(federated_slug, 2)
check("a new version was published", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

status, _ = call(COLLEAGUE, f"/api/projects/{federated_slug}/predict", {"values": IN_DOMAIN})
check("the contributor still cannot use the model", status == 403, f"status={status}")
status, _ = fetch_bytes(COLLEAGUE, f"/api/projects/{federated_slug}/export")
check("nor export it", status == 403, f"status={status}")

status, contributors = call(ANON, f"/api/projects/{federated_slug}/contributors")
names = {c["name"]: c for c in (contributors or [])}
check("but they are credited publicly", any("Colleague" in n for n in names), str(list(names)))
check("and the credit says how the data arrived",
      any(c["mode"] == "federated" for c in names.values()),
      str([c["mode"] for c in names.values()]))

status, detail = call(ANON, f"/api/projects/{federated_slug}")
speed = next(i for i in detail["inputs"] if i["variable"]["key"] == "cutting_speed")
check("their data widened the published validity domain",
      speed["observed_max"] == 130 and speed["owner_max"] == 60, str(speed))
check("and counts towards the project's size", (detail or {}).get("n_rows_total") == 20,
      str((detail or {}).get("n_rows_total")))

if versions:
    source_ids = {s["contribution_id"] for s in versions[0]["sources"]}
    check("the version lineage credits the federated contribution",
          contribution_id in source_ids, str(source_ids))
    check("and counts its rows", versions[0]["n_rows_total"] == 20,
          str(versions[0]["n_rows_total"]))
    tracks = {m["track"] for m in versions[0]["models"]}
    check("both tracks are still published", tracks == {"main", "reference"}, str(tracks))
    main = next(m for m in versions[0]["models"] if m["track"] == "main")
    # §5.4: no summary can carry the individual rows a flexible engine needs.
    check("the main model saw only the shared rows", main["n_train"] == 10,
          str(main["n_train"]))

# --------------------------------------------------------------------------- #
print("\n== exactness: sums equal pooled rows (§5.1) ==")
from_sums = reference_coefficients(OWNER, federated_slug, TARGETS[0])
from_rows = reference_coefficients(OWNER, pooled_slug, TARGETS[0])
check("both projects published a reference model",
      from_sums is not None and from_rows is not None)
if from_sums and from_rows:
    gap = abs(from_sums["intercept"] - from_rows["intercept"])
    for key in INPUT_KEYS:
        gap = max(gap, abs(from_sums["coef"][key] - from_rows["coef"][key]))
    scale = max(abs(v) for v in [from_rows["intercept"], *from_rows["coef"].values()])
    # This is the claim the federated design rests on. Not "close" — equal, to
    # the precision the arithmetic allows.
    check("fitting on summed statistics equals fitting on the pooled rows",
          gap <= 1e-6 * max(scale, 1.0), f"largest disagreement {gap:.3e} on scale {scale:.3g}")

# --------------------------------------------------------------------------- #
print("\n== the double-counting trap (§5.5) ==")
status, refused = commit_file(COLLEAGUE, federated_slug, COLLEAGUE_ROWS, "mine.csv")
check("uploading the same data as a second contribution is refused",
      status == 409, f"status={status}")
check("and the refusal names the conversion route",
      "/share" in str((refused or {}).get("detail", "")), str(refused)[:180])

status, preview = upload(COLLEAGUE, federated_slug, "mine.csv", to_csv(COLLEAGUE_ROWS))
check("the file can be staged for conversion", status == 200, f"status={status}")
mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
status, shared = call(
    COLLEAGUE, f"/api/projects/{federated_slug}/contributions/{contribution_id}/share",
    {"upload_token": preview["upload_token"], "mapping": mapping})
check("converting to shared succeeds", status == 200, f"status={status}")
check("it is now a shared contribution",
      (shared or {}).get("contribution", {}).get("mode") == "shared",
      str((shared or {}).get("contribution", {}).get("mode")))
# Sharing is what earns access, and it earns it immediately.
check("and sharing unlocks the model", (shared or {}).get("access_granted") is True,
      str((shared or {}).get("access_granted")))

versions = wait_for_version(federated_slug, 3)
check("a version was retrained from the rows", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

status, contributions = call(COLLEAGUE, f"/api/projects/{federated_slug}/contributions")
check("the contributor still has exactly one contribution here",
      len(contributions or []) == 1, str(len(contributions or [])))
check("it is the same row, with its mode changed",
      (contributions or [{}])[0].get("id") == contribution_id,
      str((contributions or [{}])[0].get("id")))

status, detail = call(ANON, f"/api/projects/{federated_slug}")
# Twenty, not thirty. Thirty would mean the measurements went in twice.
check("the row count is twenty, not thirty", (detail or {}).get("n_rows_total") == 20,
      str((detail or {}).get("n_rows_total")))
if versions:
    check("and the version agrees", versions[0]["n_rows_total"] == 20,
          str(versions[0]["n_rows_total"]))
    main = next(m for m in versions[0]["models"] if m["track"] == "main")
    check("the main model now sees all twenty rows", main["n_train"] == 20,
          str(main["n_train"]))

after = reference_coefficients(OWNER, federated_slug, TARGETS[0])
if after and from_rows:
    gap = abs(after["intercept"] - from_rows["intercept"])
    for key in INPUT_KEYS:
        gap = max(gap, abs(after["coef"][key] - from_rows["coef"][key]))
    scale = max(abs(v) for v in [from_rows["intercept"], *from_rows["coef"].values()])
    # If the sums had been left behind when the rows went in, this is where it
    # would show — and nowhere else.
    check("the model after conversion still matches the pooled fit",
          gap <= 1e-6 * max(scale, 1.0), f"largest disagreement {gap:.3e}")

status, _ = call(COLLEAGUE, f"/api/projects/{federated_slug}/predict", {"values": IN_DOMAIN})
check("the contributor can now use the model", status == 200, f"status={status}")

status, _ = call(
    COLLEAGUE, f"/api/projects/{federated_slug}/contributions/{contribution_id}/share",
    {"upload_token": preview["upload_token"], "mapping": mapping})
check("converting an already-shared contribution is refused", status == 409, f"status={status}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
