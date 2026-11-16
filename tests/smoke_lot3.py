"""End-to-end smoke test of lot 3: the project page and what it is allowed to show.

Lot 3 is where the permission matrix of ARCHITECTURE.md §4.1 stops being a
table and starts being endpoints, so most of what is checked here is who is
refused. The rest is the validity domain — the numbers the bar on the project
page draws — and the audit trail that makes handing over a file reasonable.
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


OWNER, OTHER, ANON = session(), session(), session()
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
    """A download rather than JSON — the export and the raw-file endpoints.

    The headers are returned as the message object rather than a plain dict:
    lookups on it are case-insensitive, and the server sends header names
    lowercased, so a dict would miss `Content-Disposition` and report a header
    that is present as absent.
    """
    req = urllib.request.Request(BASE + path, method="GET")
    try:
        with opener.open(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


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


def commit(opener, slug, preview, **extra):
    mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
    return call(opener, f"/api/projects/{slug}/datasets", {
        "upload_token": preview["upload_token"], "mapping": mapping,
        "mode": "shared", **extra,
    })


def wait_for_version(slug, minimum, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, versions = call(ANON, f"/api/projects/{slug}/versions")
        if status == 200 and versions and versions[0]["number"] >= minimum:
            return versions
        time.sleep(1.5)
    return None


HEADER = "gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa),note\n"
# The owner's measurements. gamma -6..8, r_beta 16..30, Vc 20..60, h 0.15..0.20.
ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
    (-6, 30, 60, 0.15, -479.0, 57.0), (0, 20, 40, 0.18, -350.0, 20.0),
    (2, 24, 30, 0.16, -390.0, 5.0), (8, 28, 50, 0.19, -430.0, 35.0),
]
# An unmapped text column carrying a spreadsheet payload. It must come back
# from the download neutralised, while the negative numbers beside it — which
# also begin with a formula character — must come back untouched.
PAYLOAD = "=cmd|'/c calc'!A1"
NOTES = [PAYLOAD] + ["ok"] * (len(ROWS) - 1)
CSV = (HEADER + "".join(
    ",".join(str(v) for v in row) + f",{note}\n" for row, note in zip(ROWS, NOTES)
)).encode()

# Someone else's measurements, from a far higher speed regime. They land
# pending, and pending data must not move anything the project advertises.
OTHER_ROWS = [
    (3, 18, 150, 0.15, -500.0, 10.0), (3, 18, 160, 0.16, -505.0, 12.0),
    (3, 20, 170, 0.17, -510.0, 14.0), (4, 20, 180, 0.18, -515.0, 16.0),
    (4, 22, 190, 0.19, -520.0, 18.0), (4, 22, 200, 0.20, -525.0, 20.0),
    (5, 24, 150, 0.15, -530.0, 22.0), (5, 24, 160, 0.16, -535.0, 24.0),
    (6, 26, 170, 0.17, -540.0, 26.0), (6, 26, 180, 0.18, -545.0, 28.0),
]
OTHER_CSV = (HEADER + "".join(
    ",".join(str(v) for v in row) + ",ok\n" for row in OTHER_ROWS
)).encode()

TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]
IN_DOMAIN = {
    "rake_angle": 0, "edge_radius": 22,
    "cutting_speed": 40, "uncut_chip_thickness": 0.17,
}

print("== setup ==")
for opener, who in ((OWNER, "owner"), (OTHER, "other")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-3-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}", "institution": f"{who.title()} Institute",
    })
    check(f"register {who}", status == 201, f"status={status}")

status, project = call(OWNER, "/api/projects", {
    "title": f"Domain and access {tag}", "material": "Ti-6Al-4V", "process": "turning",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "licence": "CC-BY-4.0",
    "inputs": [
        # Declared wider than the data will be: covered ⊂ declared.
        {"variable_key": "rake_angle", "required": True, "penalised_sign": -1,
         "expected_min": -10, "expected_max": 10},
        {"variable_key": "edge_radius", "required": True, "penalised_sign": -1,
         "expected_min": 10, "expected_max": 40},
        {"variable_key": "cutting_speed", "required": True, "penalised_sign": 1,
         "expected_min": 10, "expected_max": 80},
        {"variable_key": "uncut_chip_thickness", "required": True, "penalised_sign": 1,
         "expected_min": 0.1, "expected_max": 0.3},
    ],
    "targets": [{"variable_key": k} for k in TARGETS],
})
check("create project", status == 201, f"status={status}")
slug = (project or {}).get("slug")

status, preview = upload(OWNER, slug, "owner-trials.csv", CSV)
check("owner upload previews", status == 200, f"status={status}")
status, owner_contribution = commit(OWNER, slug, preview, measurement_method="XRD")
check("owner data committed", status == 201, f"status={status}")
owner_contribution_id = (owner_contribution or {}).get("id")
check("owner data is accepted without review",
      (owner_contribution or {}).get("status") == "accepted",
      str((owner_contribution or {}).get("status")))

versions = wait_for_version(slug, 1)
check("a model was trained", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

# --------------------------------------------------------------------------- #
print("\n== the validity domain ==")
# These four numbers per input are what the bar on the project page draws. The
# declared range is a claim; the observed range is the only one that licenses
# belief in a prediction.
status, detail = call(ANON, f"/api/projects/{slug}")
check("project readable anonymously", status == 200, f"status={status}")
inputs = {item["variable"]["key"]: item for item in (detail or {}).get("inputs", [])}

check("every input carries all four bounds",
      all({"expected_min", "expected_max", "observed_min", "observed_max",
           "owner_min", "owner_max"} <= set(item) for item in inputs.values()))

speed = inputs.get("cutting_speed", {})
check("declared range is what the owner declared",
      (speed.get("expected_min"), speed.get("expected_max")) == (10, 80), str(speed))
check("observed range is where the data actually is",
      (speed.get("observed_min"), speed.get("observed_max")) == (20, 60), str(speed))
check("with only the owner's data, owner coverage equals total coverage",
      (speed.get("owner_min"), speed.get("owner_max"))
      == (speed.get("observed_min"), speed.get("observed_max")), str(speed))

angle = inputs.get("rake_angle", {})
check("a negative-valued input is not mangled",
      (angle.get("observed_min"), angle.get("observed_max")) == (-6, 8), str(angle))
thickness = inputs.get("uncut_chip_thickness", {})
check("a fractional input keeps its scale",
      (thickness.get("observed_min"), thickness.get("observed_max")) == (0.15, 0.20),
      str(thickness))
check("input order is preserved",
      [i["variable"]["key"] for i in (detail or {}).get("inputs", [])]
      == ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"])

# --------------------------------------------------------------------------- #
print("\n== pending data advertises nothing ==")
status, other_preview = upload(OTHER, slug, "other-trials.csv", OTHER_CSV)
check("another lab may upload", status == 200, f"status={status}")
status, other_contribution = commit(OTHER, slug, other_preview, measurement_method="hole-drilling")
check("their data is recorded", status == 201, f"status={status}")
other_contribution_id = (other_contribution or {}).get("id")
check("and lands pending, not accepted",
      (other_contribution or {}).get("status") == "pending",
      str((other_contribution or {}).get("status")))

status, detail = call(ANON, f"/api/projects/{slug}")
after = {item["variable"]["key"]: item for item in (detail or {}).get("inputs", [])}
check("pending data does not widen the published domain",
      (after["cutting_speed"]["observed_min"], after["cutting_speed"]["observed_max"])
      == (20, 60), str(after["cutting_speed"]))
check("nor the row count", (detail or {}).get("n_rows_total") == 10,
      str((detail or {}).get("n_rows_total")))
check("nor the contributor count", (detail or {}).get("n_contributors") == 1,
      str((detail or {}).get("n_contributors")))

# --------------------------------------------------------------------------- #
print("\n== contributors are public, files are not ==")
status, contributors = call(ANON, f"/api/projects/{slug}/contributors")
check("contributor list is public", status == 200, f"status={status}")
check("only the accepted contribution is credited", len(contributors or []) == 1,
      str(len(contributors or [])))
if contributors:
    entry = contributors[0]
    check("the contributor is named", entry["name"].startswith("Owner"), str(entry["name"]))
    check("their institution is shown", entry["institution"] == "Owner Institute",
          str(entry.get("institution")))
    check("with the size of the contribution", entry["n_rows"] == 10, str(entry["n_rows"]))
    check("and how it was measured", entry["measurement_method"] == "XRD",
          str(entry.get("measurement_method")))
    check("but nothing that identifies the file",
          set(entry) == {"name", "institution", "n_rows", "measurement_method",
                         "mode", "contributed_at"},
          str(sorted(entry)))

# --------------------------------------------------------------------------- #
print("\n== owner settings ==")
status, _ = call(ANON, f"/api/projects/{slug}", {"title": "Hijacked"}, method="PATCH")
check("an anonymous visitor cannot edit a project", status == 401, f"status={status}")
status, _ = call(OTHER, f"/api/projects/{slug}", {"title": "Hijacked"}, method="PATCH")
check("nor can another signed-in user", status == 403, f"status={status}")

status, edited = call(OWNER, f"/api/projects/{slug}", {
    "title": f"Renamed {tag}", "description": "Edited by the owner.",
    "licence": "CC-BY-SA-4.0", "accepts_federated": False,
}, method="PATCH")
check("the owner can edit", status == 200, f"status={status}")
check("the title changed", (edited or {}).get("title") == f"Renamed {tag}",
      str((edited or {}).get("title")))
check("the description changed",
      (edited or {}).get("description") == "Edited by the owner.")
check("a flag can be turned off", (edited or {}).get("accepts_federated") is False,
      str((edited or {}).get("accepts_federated")))
# A link handed to a colleague or printed in a paper has to keep working.
check("the address is permanent", (edited or {}).get("slug") == slug,
      str((edited or {}).get("slug")))

status, rebounded = call(OWNER, f"/api/projects/{slug}", {
    "input_bounds": {"cutting_speed": {"expected_min": 15, "expected_max": 75,
                                       "penalised_sign": 1}},
}, method="PATCH")
check("declared bounds can be moved", status == 200, f"status={status}")
moved = {i["variable"]["key"]: i for i in (rebounded or {}).get("inputs", [])}
check("the new bounds are stored",
      (moved["cutting_speed"]["expected_min"], moved["cutting_speed"]["expected_max"])
      == (15, 75), str(moved["cutting_speed"]))
check("moving the declaration does not move the data",
      (moved["cutting_speed"]["observed_min"], moved["cutting_speed"]["observed_max"])
      == (20, 60), str(moved["cutting_speed"]))

status, _ = call(OWNER, f"/api/projects/{slug}", {
    "input_bounds": {"feed": {"expected_min": 0}},
}, method="PATCH")
check("bounds cannot be set on a quantity the project does not use",
      status == 422, f"status={status}")
status, unchanged = call(ANON, f"/api/projects/{slug}")
check("the input list is not editable through this endpoint",
      len((unchanged or {}).get("inputs", [])) == 4,
      str(len((unchanged or {}).get("inputs", []))))

# --------------------------------------------------------------------------- #
print("\n== prediction is behind the model gate ==")
status, _ = call(ANON, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("an anonymous visitor cannot predict", status == 403, f"status={status}")
status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
# The whole incentive rests on this: submitting is not the same as being
# accepted, and a pending contribution unlocks nothing.
check("a pending contributor cannot predict either", status == 403, f"status={status}")

status, predicted = call(OWNER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("the owner can predict", status == 200, f"status={status}")
if status == 200:
    check("one prediction per target", len(predicted["predictions"]) == len(TARGETS),
          str(len(predicted["predictions"])))
    check("predictions are numbers",
          all(isinstance(p["value"], (int, float)) for p in predicted["predictions"]))
    check("targets are named and carry units",
          all(p["target_name"] and "target_unit" in p for p in predicted["predictions"]))
    check("inside the covered domain nothing is flagged",
          predicted["out_of_domain"] == [], str(predicted["out_of_domain"]))
    check("the version used is reported", predicted["version"] >= 1,
          str(predicted.get("version")))

status, extrapolated = call(OWNER, f"/api/projects/{slug}/predict", {
    "values": {**IN_DOMAIN, "cutting_speed": 500},
})
check("an extrapolation is answered, not refused", status == 200, f"status={status}")
if status == 200:
    check("but it is flagged", len(extrapolated["out_of_domain"]) == 1,
          str(extrapolated["out_of_domain"]))
    warning = " ".join(extrapolated["out_of_domain"])
    check("the warning names the input", "speed" in warning.lower(), warning)
    # Against the data, not against the declared range: the declared maximum is
    # 75 and the data stops at 60, and only the second one licenses belief.
    check("and quotes the range there is data for, not the declared one",
          "60" in warning and "75" not in warning, warning)

status, _ = call(OWNER, f"/api/projects/{slug}/predict", {
    "values": {k: v for k, v in IN_DOMAIN.items() if k != "edge_radius"},
})
check("a missing input is refused rather than guessed", status == 422, f"status={status}")

status, reference = call(OWNER, f"/api/projects/{slug}/predict", {
    "values": IN_DOMAIN, "track": "reference",
})
check("the reference track can be queried too", status == 200, f"status={status}")
if status == 200:
    check("and it answers on the reference track",
          all(p["track"] == "reference" for p in reference["predictions"]),
          str([p["track"] for p in reference["predictions"]]))

status, pinned = call(OWNER, f"/api/projects/{slug}/predict",
                      {"values": IN_DOMAIN, "version": 1})
check("an older version stays queryable", status == 200 and pinned["version"] == 1,
      f"status={status}")
status, _ = call(OWNER, f"/api/projects/{slug}/predict",
                 {"values": IN_DOMAIN, "version": 99})
check("a version that does not exist is a 404", status == 404, f"status={status}")

# --------------------------------------------------------------------------- #
print("\n== export is citable and gated ==")
status, _, _ = fetch_bytes(ANON, f"/api/projects/{slug}/export")
check("anonymous export is refused", status == 403, f"status={status}")
status, _, _ = fetch_bytes(OTHER, f"/api/projects/{slug}/export")
check("a pending contributor cannot export", status == 403, f"status={status}")

status, raw, _ = fetch_bytes(OWNER, f"/api/projects/{slug}/export")
check("the owner can export", status == 200, f"status={status}")
if status == 200:
    document = json.loads(raw)
    check("it declares its schema", document.get("schema") == "mlfl-model/1",
          str(document.get("schema")))
    check("it names the project and its licence",
          document["project"]["slug"] == slug
          and document["project"]["licence"] == "CC-BY-SA-4.0",
          str(document["project"]))
    check("it carries the covered range per input, not the declared one",
          document["inputs"][2]["covered_range"] == [20, 60],
          str(document["inputs"][2]))
    check("inputs keep their position", [i["position"] for i in document["inputs"]]
          == [0, 1, 2, 3], str([i["position"] for i in document["inputs"]]))
    check("it lists who to cite",
          [c["contributor"] for c in document["provenance"]["contributions"]]
          == [f"Owner {tag}"], str(document["provenance"]["contributions"]))
    check("a pending contribution is not credited in the export",
          all("Other" not in c["contributor"]
              for c in document["provenance"]["contributions"]))
    check("and it says it holds no raw data",
          document["provenance"]["contains_raw_data"] is False)
    check("the coefficients are in it",
          any(m.get("coefficients") for m in document["models"]))

# --------------------------------------------------------------------------- #
print("\n== raw files, and the record of who read them ==")
status, _, _ = fetch_bytes(
    ANON, f"/api/projects/{slug}/contributions/{owner_contribution_id}/download")
check("an anonymous visitor cannot download a file", status == 401, f"status={status}")
status, _, _ = fetch_bytes(
    OTHER, f"/api/projects/{slug}/contributions/{owner_contribution_id}/download")
# §4.1: a contributor never sees another contributor's file. Only the owner does.
check("one contributor cannot read another's file", status == 403, f"status={status}")

status, downloaded, headers = fetch_bytes(
    OWNER, f"/api/projects/{slug}/contributions/{owner_contribution_id}/download")
check("the owner can read a file contributed to their project", status == 200,
      f"status={status}")
if status == 200:
    text = downloaded.decode("utf-8")
    check("it is served as an attachment, not rendered",
          "attachment" in headers.get("Content-Disposition", ""),
          headers.get("Content-Disposition", ""))
    check("and the browser is told not to sniff it",
          headers.get("X-Content-Type-Options") == "nosniff")
    check("a spreadsheet formula in the file is neutralised",
          f"'{PAYLOAD}" in text, text.splitlines()[1] if text else "")
    check("while negative measurements are left alone",
          "-454.0" in text and "'-454.0" not in text)

status, _, _ = fetch_bytes(
    OTHER, f"/api/projects/{slug}/contributions/{other_contribution_id}/download")
check("a contributor can still read back their own file", status == 200, f"status={status}")

status, log = call(OWNER, f"/api/projects/{slug}/access-log")
check("the owner sees the access log", status == 200, f"status={status}")
check("their own download is recorded", any(
    e["action"] == "dataset.download" and e["detail"].get("filename") == "owner-trials.csv"
    for e in (log or [])), str(log))
check("the log names who did it",
      all(e["actor_name"] for e in (log or [])), str(log))
check("the owner sees both files' reads", len(log or []) == 2, str(len(log or [])))

status, their_log = call(OTHER, f"/api/projects/{slug}/access-log")
check("a contributor sees the log too", status == 200, f"status={status}")
# The transparency runs one way only: they learn who opened *their* file, not
# what happens to anyone else's.
check("but only the reads of their own file", len(their_log or []) == 1,
      str(their_log))
check("which is their own file",
      all(e["detail"].get("filename") == "other-trials.csv" for e in (their_log or [])),
      str(their_log))

status, _ = call(ANON, f"/api/projects/{slug}/access-log")
check("the access log is not public", status == 401, f"status={status}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
