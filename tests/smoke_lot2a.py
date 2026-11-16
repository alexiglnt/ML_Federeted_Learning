"""End-to-end smoke test of lot 2a: uploading, reading and mapping files.

Needs `openpyxl` to build the spreadsheet fixture:

    pip install openpyxl
"""
import http.cookiejar
import io
import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = "http://localhost:8000"
tag = uuid.uuid4().hex[:8]


def session():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


OWNER = session()
OTHER = session()

ok = True


def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


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


def upload(opener, slug, filename, content: bytes):
    """Multipart POST without any third-party HTTP library."""
    boundary = "----mlfl" + uuid.uuid4().hex
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content,
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
        raw = e.read().decode("utf-8")
        return e.code, (json.loads(raw) if raw else None)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
# The seven conditions of the study the platform grew out of.
OUTEIRO = b"""gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)
5,16,20,0.15,-454.0,-73.0
5,16,20,0.20,-387.0,9.0
5,16,60,0.15,-400.0,52.0
5,30,60,0.15,-619.0,-51.0
5,16,60,0.20,-423.0,25.0
-6,16,60,0.15,-273.0,64.0
-6,30,60,0.15,-479.0,57.0
"""

# The hostile case: two title rows, semicolons, decimal commas, Greek headings.
EUROPEAN = """Essais d'usinage - laboratoire X
Export du 12/03/2026;;;;;
γ (°);rβ (µm);Vc (m/min);h (mm);SRS_L (MPa);SRS_T (MPa)
5;16;20;0,15;-454,0;-73,0
5;16;20;0,20;-387,0;9,0
5;16;60;0,15;-400,0;52,0
5;30;60;0,15;-619,0;-51,0
5;16;60;0,20;-423,0;25,0
-6;16;60;0,15;-273,0;64,0
-6;30;60;0,15;-479,0;57,0
""".encode("utf-8")


def make_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Machining trials", None, None, None, None, None])
    ws.append(["gamma (deg)", "r_beta (um)", "Vc (m/min)", "h (mm)", "SRS_L (MPa)", "SRS_T (MPa)"])
    for row in [
        [5, 16, 20, 0.15, -454.0, -73.0], [5, 16, 20, 0.20, -387.0, 9.0],
        [5, 16, 60, 0.15, -400.0, 52.0], [5, 30, 60, 0.15, -619.0, -51.0],
        [5, 16, 60, 0.20, -423.0, 25.0], [-6, 16, 60, 0.15, -273.0, 64.0],
        [-6, 30, 60, 0.15, -479.0, 57.0],
    ]:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


INPUT_KEYS = ["rake_angle", "edge_radius", "cutting_speed", "uncut_chip_thickness"]
TARGET_KEYS = ["residual_stress_axial", "residual_stress_circumferential"]
ALL_KEYS = INPUT_KEYS + TARGET_KEYS

# --------------------------------------------------------------------------- #
print("== setup ==")
for opener, who in ((OWNER, "owner"), (OTHER, "other")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}", "institution": "Lab " + who,
    })
    check(f"register {who}", status == 201, f"status={status}")

status, project = call(OWNER, "/api/projects", {
    "title": f"Residual stress uploads {tag}",
    "material": "Ti-6Al-4V", "process": "orthogonal turning",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "inputs": [
        {"variable_key": "rake_angle", "required": True, "expected_min": -6, "expected_max": 10},
        {"variable_key": "edge_radius", "required": True, "expected_min": 16, "expected_max": 30},
        {"variable_key": "cutting_speed", "required": True, "expected_min": 20, "expected_max": 60},
        {"variable_key": "uncut_chip_thickness", "required": True, "expected_min": 0.15, "expected_max": 0.20},
    ],
    "targets": [{"variable_key": k} for k in TARGET_KEYS],
})
check("create project", status == 201, f"status={status}")
slug = (project or {}).get("slug")
check("project starts as draft", (project or {}).get("status") == "draft")

print("\n== reading a plain CSV ==")
status, preview = upload(OWNER, slug, "outeiro.csv", OUTEIRO)
check("upload accepted", status == 200, f"status={status} {preview}")
report = (preview or {}).get("parse_report", {})
check("7 rows read", report.get("n_rows") == 7, str(report.get("n_rows")))
check("6 columns read", report.get("n_columns") == 6, str(report.get("n_columns")))
check("comma separator detected", report.get("separator") == ",", repr(report.get("separator")))
check("dot decimal detected", report.get("decimal") == ".", repr(report.get("decimal")))
check("header on first row", report.get("header_row") == 0)

suggested = (preview or {}).get("suggested_mapping", {})
mapped = {k: v.get("column") for k, v in suggested.items()}
check("all six quantities suggested", all(mapped.get(k) for k in ALL_KEYS), str(mapped))
check("every suggestion is exact", all(suggested[k]["exact"] for k in ALL_KEYS if suggested.get(k)))
check("no column reused across quantities",
      len({c for c in mapped.values() if c}) == len([c for c in mapped.values() if c]), str(mapped))

print("\n== the hostile European export ==")
status, euro = upload(OWNER, slug, "essais.csv", EUROPEAN)
check("upload accepted", status == 200, f"status={status}")
er = (euro or {}).get("parse_report", {})
check("semicolon separator detected", er.get("separator") == ";", repr(er.get("separator")))
check("decimal comma detected", er.get("decimal") == ",", repr(er.get("decimal")))
check("two title rows skipped", er.get("header_row") == 2, str(er.get("header_row")))
check("7 data rows found", er.get("n_rows") == 7, str(er.get("n_rows")))
euro_map = {k: v.get("column") for k, v in (euro or {}).get("suggested_mapping", {}).items()}
check("Greek gamma column matched", euro_map.get("rake_angle") == "γ (°)", repr(euro_map.get("rake_angle")))
check("Greek r-beta column matched", euro_map.get("edge_radius") == "rβ (µm)", repr(euro_map.get("edge_radius")))
first = (euro or {}).get("preview_rows", [{}])[0]
check("decimal comma parsed to a number", first.get("h (mm)") == 0.15, repr(first.get("h (mm)")))
check("negative decimal comma parsed", first.get("SRS_L (MPa)") == -454.0, repr(first.get("SRS_L (MPa)")))

print("\n== a spreadsheet ==")
status, xl = upload(OWNER, slug, "trials.xlsx", make_xlsx())
check("xlsx accepted", status == 200, f"status={status} {xl}")
xr = (xl or {}).get("parse_report", {})
check("read as xlsx", xr.get("source") == "xlsx", str(xr.get("source")))
check("title row skipped", xr.get("header_row") == 1, str(xr.get("header_row")))
check("7 data rows found", xr.get("n_rows") == 7, str(xr.get("n_rows")))

print("\n== rejected uploads ==")
status, _ = upload(OWNER, slug, "notes.pdf", b"%PDF-1.4 not a table")
check("unsupported extension rejected", status == 415, f"status={status}")
status, _ = upload(OWNER, slug, "empty.csv", b"")
check("empty file rejected", status == 400, f"status={status}")
status, _ = upload(OWNER, slug, "one.csv", b"a,b\n1,2\n")
check("a readable but tiny file still previews", status == 200, f"status={status}")

print("\n== committing ==")
good_mapping = {k: mapped[k] for k in ALL_KEYS}
status, contribution = call(OWNER, f"/api/projects/{slug}/datasets", {
    "upload_token": preview["upload_token"], "mapping": good_mapping,
    "mode": "shared", "measurement_method": "XRD", "notes": "seven conditions",
})
check("commit accepted", status == 201, f"status={status} {contribution}")
check("7 usable rows recorded", (contribution or {}).get("n_rows") == 7, str((contribution or {}).get("n_rows")))
check("owner's own data is auto-accepted", (contribution or {}).get("status") == "accepted")
ranges = (contribution or {}).get("feature_ranges", {})
check("cutting speed range captured", ranges.get("cutting_speed") == [20, 60], str(ranges.get("cutting_speed")))
check("rake angle range captured", ranges.get("rake_angle") == [-6, 5], str(ranges.get("rake_angle")))

status, detail = call(OWNER, f"/api/projects/{slug}")
check("project became active", (detail or {}).get("status") == "active", str((detail or {}).get("status")))
check("row count on the project", (detail or {}).get("n_rows_total") == 7, str((detail or {}).get("n_rows_total")))
observed = {i["variable"]["key"]: [i["observed_min"], i["observed_max"]] for i in (detail or {}).get("inputs", [])}
check("observed coverage shown", observed.get("cutting_speed") == [20, 60], str(observed.get("cutting_speed")))

print("\n== the same file twice ==")
status, again = upload(OWNER, slug, "outeiro-copy.csv", OUTEIRO)
check("re-upload previews fine", status == 200)
status, body = call(OWNER, f"/api/projects/{slug}/datasets", {
    "upload_token": again["upload_token"], "mapping": good_mapping, "mode": "shared",
})
check("identical file rejected on commit", status == 409, f"status={status}")

print("\n== mapping validation ==")
status, fresh = upload(OWNER, slug, "essais.csv", EUROPEAN)
token = fresh["upload_token"]
bad = {k: v for k, v in euro_map.items() if k != "cutting_speed"}
status, body = call(OWNER, f"/api/projects/{slug}/datasets", {"upload_token": token, "mapping": bad})
check("missing required input rejected", status == 422, f"status={status}")
check("message names the missing quantity", "Cutting speed" in str((body or {}).get("detail")), str((body or {}).get("detail"))[:90])

status, fresh = upload(OWNER, slug, "essais.csv", EUROPEAN)
no_target = {k: euro_map[k] for k in INPUT_KEYS}
status, body = call(OWNER, f"/api/projects/{slug}/datasets", {"upload_token": fresh["upload_token"], "mapping": no_target})
check("no target mapped rejected", status == 422, f"status={status}")

status, fresh = upload(OWNER, slug, "essais.csv", EUROPEAN)
collide = dict(euro_map)
collide["edge_radius"] = collide["cutting_speed"]
status, body = call(OWNER, f"/api/projects/{slug}/datasets", {"upload_token": fresh["upload_token"], "mapping": collide})
check("one column for two quantities rejected", status == 422, f"status={status}")

status, tiny = upload(OWNER, slug, "tiny.csv",
                      b"gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa)\n5,16,20,0.15,-454\n")
status, body = call(OWNER, f"/api/projects/{slug}/datasets", {
    "upload_token": tiny["upload_token"],
    "mapping": {k: v.get("column") for k, v in tiny["suggested_mapping"].items() if v.get("column")},
})
check("too few rows rejected", status == 422, f"status={status}")
check("privacy reason given", "privacy" in str((body or {}).get("detail")).lower(), str((body or {}).get("detail"))[:80])

print("\n== another user's upload ==")
status, theirs = upload(OTHER, slug, "other-lab.csv", b"""gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)
0,20,90,0.10,-300,10
2,22,95,0.12,-310,12
4,24,100,0.14,-320,14
6,26,105,0.16,-330,16
8,28,110,0.18,-340,18
10,30,115,0.22,-350,20
""")
check("other user may upload", status == 200, f"status={status}")
status, theirs_committed = call(OTHER, f"/api/projects/{slug}/datasets", {
    "upload_token": theirs["upload_token"],
    "mapping": {k: v.get("column") for k, v in theirs["suggested_mapping"].items() if v.get("column")},
    "mode": "shared", "measurement_method": "hole-drilling",
})
check("their commit accepted", status == 201, f"status={status} {theirs_committed}")
check("but it lands pending, not accepted",
      (theirs_committed or {}).get("status") == "pending", str((theirs_committed or {}).get("status")))
warnings = ((theirs_committed or {}).get("validation") or {}).get("warnings", [])
check("out-of-range data warns rather than blocks", any("above the project" in w for w in warnings), str(warnings)[:120])

status, detail = call(OWNER, f"/api/projects/{slug}")
check("pending data does not inflate the row count",
      (detail or {}).get("n_rows_total") == 7, str((detail or {}).get("n_rows_total")))
observed = {i["variable"]["key"]: [i["observed_min"], i["observed_max"]] for i in (detail or {}).get("inputs", [])}
check("pending data does not widen the published domain",
      observed.get("cutting_speed") == [20, 60], str(observed.get("cutting_speed")))

print("\n== who sees which contributions ==")
status, all_of_them = call(OWNER, f"/api/projects/{slug}/contributions")
check("owner sees both contributions", status == 200 and len(all_of_them or []) == 2, str(len(all_of_them or [])))
status, just_mine = call(OTHER, f"/api/projects/{slug}/contributions")
check("contributor sees only their own", status == 200 and len(just_mine or []) == 1, str(len(just_mine or [])))
check("and it is theirs", (just_mine or [{}])[0].get("contributor_name", "").lower().startswith("other"))

print("\n== staged uploads are not transferable ==")
status, staged = upload(OWNER, slug, "outeiro.csv", OUTEIRO)
status, body = call(OTHER, f"/api/projects/{slug}/datasets", {
    "upload_token": staged["upload_token"], "mapping": good_mapping,
})
check("another user cannot claim a staged upload", status == 410, f"status={status}")

print("\n== federated mode is not made by uploading a file ==")
# Until lot 5b this returned 501. The mode now exists, but it is reached by
# POSTing summary statistics to .../federated — the whole point is that no file
# is uploaded — so asking for it here is a request that does not make sense
# rather than a feature that is missing. Covered end to end by smoke_lot5b.py.
status, fresh = upload(OTHER, slug, "outeiro.csv", OUTEIRO)
status, body = call(OTHER, f"/api/projects/{slug}/datasets", {
    "upload_token": fresh["upload_token"], "mapping": good_mapping, "mode": "federated",
})
check("federated is refused on the file endpoint, not silently accepted",
      status == 400, f"status={status}")
check("and the refusal says where it does belong",
      "/federated" in str((body or {}).get("detail", "")), str(body)[:160])

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
