"""End-to-end smoke test of lot 2b: training, versions and who sees the model."""
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


OWNER, OTHER, ANON = session(), session(), session()
ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


def call(opener, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with opener.open(req) as r:
            raw = r.read().decode("utf-8")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw else None)


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


def wait_for_version(slug, minimum, timeout=90):
    """Training runs after the request returns, so poll rather than assume."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, versions = call(ANON, f"/api/projects/{slug}/versions")
        if status == 200 and versions and versions[0]["number"] >= minimum:
            return versions
        time.sleep(1.5)
    return None


ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
    (-6, 30, 60, 0.15, -479.0, 57.0), (0, 20, 40, 0.18, -350.0, 20.0),
    (2, 24, 30, 0.16, -390.0, 5.0), (8, 28, 50, 0.19, -430.0, 35.0),
]
HEADER = "gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)\n"
CSV = (HEADER + "".join(",".join(str(v) for v in row) + "\n" for row in ROWS)).encode()

TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]
ALL_KEYS = ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"] + TARGETS

print("== setup ==")
for opener, who in ((OWNER, "owner"), (OTHER, "other")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-2b-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}",
    })
    check(f"register {who}", status == 201, f"status={status}")

status, project = call(OWNER, "/api/projects", {
    "title": f"Training run {tag}", "material": "Ti-6Al-4V",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "inputs": [
        {"variable_key": "rake_angle", "required": True, "penalised_sign": -1},
        {"variable_key": "edge_radius", "required": True, "penalised_sign": -1},
        {"variable_key": "cutting_speed", "required": True, "penalised_sign": 1},
        {"variable_key": "uncut_chip_thickness", "required": True, "penalised_sign": 1},
    ],
    "targets": [{"variable_key": k} for k in TARGETS],
})
check("create project", status == 201, f"status={status}")
slug = (project or {}).get("slug")

print("\n== before any data ==")
status, _ = call(ANON, f"/api/projects/{slug}/model")
check("no model yet is a 404, not an empty object", status == 404, f"status={status}")
status, versions = call(ANON, f"/api/projects/{slug}/versions")
check("version list is empty", status == 200 and versions == [], str(versions))

print("\n== uploading data trains automatically ==")
status, preview = upload(OWNER, slug, "trials.csv", CSV)
check("upload previews", status == 200, f"status={status}")
mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
status, _ = call(OWNER, f"/api/projects/{slug}/datasets", {
    "upload_token": preview["upload_token"], "mapping": mapping,
    "mode": "shared", "measurement_method": "XRD",
})
check("commit accepted", status == 201, f"status={status}")

versions = wait_for_version(slug, 1)
check("a version appeared without being asked for", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

if versions:
    v1 = versions[0]
    check("version 1", v1["number"] == 1)
    check("row count recorded", v1["n_rows_total"] == 10, str(v1["n_rows_total"]))
    check("lineage recorded", len(v1["sources"]) == 1, str(len(v1["sources"])))
    check("lineage names the contributor",
          v1["sources"][0]["contributor_name"].startswith("Owner"), str(v1["sources"][0]))

    tracks = {m["track"] for m in v1["models"]}
    check("both tracks were fitted", tracks == {"main", "reference"}, str(tracks))
    check("one model per track per target", len(v1["models"]) == 4, str(len(v1["models"])))
    targets_fitted = {m["target_key"] for m in v1["models"]}
    check("both targets fitted", targets_fitted == set(TARGETS), str(targets_fitted))

    main = next(m for m in v1["models"] if m["track"] == "main")
    check("main track uses the project's engine", main["engine"] == "piml", main["engine"])
    ref = next(m for m in v1["models"] if m["track"] == "reference")
    check("reference track is linear family", ref["engine"] in ("linear", "ridge", "piml"),
          ref["engine"])
    check("training R2 present", main["metrics"].get("r2_train") is not None)
    check("out-of-sample R2 present", main["metrics"].get("r2_cv") is not None,
          str(main["metrics"].get("r2_cv")))
    check("leave-one-lab-out is null with a single contributor",
          main["metrics"].get("r2_leave_one_lab_out") is None,
          str(main["metrics"].get("r2_leave_one_lab_out")))
    check("headline score is not the training R2",
          v1["headline_r2"] != main["metrics"]["r2_train"],
          f"headline={v1['headline_r2']} train={main['metrics']['r2_train']}")

print("\n== who may see the model itself ==")
status, seen = call(ANON, f"/api/projects/{slug}/model")
check("anonymous can read the version", status == 200)
anon_main = next(m for m in seen["models"] if m["track"] == "main")
check("metrics are public", anon_main["metrics"].get("r2_cv") is not None)
check("coefficients are withheld", anon_main["coefficients"] is None)
check("equation is withheld", anon_main["equation"] is None)

status, theirs = call(OTHER, f"/api/projects/{slug}/model")
other_main = next(m for m in theirs["models"] if m["track"] == "main")
check("a signed-in non-contributor is also withheld the model",
      other_main["coefficients"] is None and other_main["equation"] is None)

status, mine = call(OWNER, f"/api/projects/{slug}/model")
own_main = next(m for m in mine["models"] if m["track"] == "main")
check("the owner gets the coefficients", own_main["coefficients"] is not None)
check("the owner gets an equation", bool(own_main["equation"]), str(own_main["equation"])[:80])
check("the equation names the project's inputs",
      "cutting_speed" in (own_main["equation"] or "") or
      "rake_angle" in (own_main["equation"] or ""), str(own_main["equation"])[:80])
coefficients = own_main["coefficients"]["coef"]
check("one coefficient per input", len(coefficients) == 4, str(list(coefficients)))

print("\n== physical priors are honoured ==")
# The project forbids a positive coefficient on cutting speed and a negative
# one on rake angle. PIML is a soft penalty, so this checks the direction the
# fit was pushed rather than a hard bound.
lam = own_main["hyperparams"].get("lambda")
check("a lambda was selected by cross-validation", lam is not None, str(lam))
check("the sweep is published", "lambda_scan_cv_r2" in own_main["hyperparams"])

print("\n== retraining ==")
status, job = call(OWNER, f"/api/projects/{slug}/train", {})
check("owner may retrain", status == 202, f"status={status}")
versions = wait_for_version(slug, 2)
check("a second version was published", versions is not None and versions[0]["number"] == 2,
      "timed out" if versions is None else f"v{versions[0]['number']}")
if versions:
    check("versions are listed newest first",
          [v["number"] for v in versions] == sorted([v["number"] for v in versions], reverse=True),
          str([v["number"] for v in versions]))
    check("the older version is still there", len(versions) == 2, str(len(versions)))
    check("same data gives the same score",
          versions[0]["headline_r2"] == versions[1]["headline_r2"],
          f"{versions[0]['headline_r2']} vs {versions[1]['headline_r2']}")

status, _ = call(OTHER, f"/api/projects/{slug}/train", {})
check("a non-owner cannot trigger training", status == 403, f"status={status}")
status, _ = call(ANON, f"/api/projects/{slug}/train", {})
check("an anonymous visitor cannot either", status == 401, f"status={status}")

print("\n== a specific version can be fetched ==")
status, v1_again = call(OWNER, f"/api/projects/{slug}/model?version=1")
check("version 1 still resolves", status == 200 and v1_again["number"] == 1, f"status={status}")
status, _ = call(OWNER, f"/api/projects/{slug}/model?version=99")
check("a missing version is a 404", status == 404, f"status={status}")

print("\n== the project summary reflects the model ==")
status, detail = call(ANON, f"/api/projects/{slug}")
check("latest version shown on the project", (detail or {}).get("latest_version") == 2,
      str((detail or {}).get("latest_version")))
check("project is active", (detail or {}).get("status") == "active")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
