"""End-to-end smoke test of lot 5: owner review, access grant, and undoing both.

This is the lot that closes the loop the platform runs on — share data, get the
model — so what is checked here is mostly that the loop is *reversible*. Access
follows the data: it arrives when a contribution is accepted and it leaves when
that contribution stops being accepted, whether the owner rejected it or the
contributor took it back. If it did not leave, anyone could unlock a model and
then withdraw their data, which is exactly the free ride review exists to stop.

Also checked: ARCHITECTURE.md §8.4 — a rejected or withdrawn contribution
leaves **no trace** in the next trained version.
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


def commit(opener, slug, preview, **extra):
    mapping = {k: v["column"] for k, v in preview["suggested_mapping"].items() if v["column"]}
    return call(opener, f"/api/projects/{slug}/datasets", {
        "upload_token": preview["upload_token"], "mapping": mapping,
        "mode": "shared", **extra,
    })


def wait_for_version(slug, minimum, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, versions = call(ANON, f"/api/projects/{slug}/versions")
        if status == 200 and versions and versions[0]["number"] >= minimum:
            return versions
        time.sleep(1.5)
    return None


HEADER = "gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)\n"


def to_csv(rows):
    return (HEADER + "".join(",".join(str(v) for v in r) + "\n" for r in rows)).encode()


# The owner's measurements: a low-speed regime, Vc 20..60.
OWNER_ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
    (-6, 30, 60, 0.15, -479.0, 57.0), (0, 20, 40, 0.18, -350.0, 20.0),
    (2, 24, 30, 0.16, -390.0, 5.0), (8, 28, 50, 0.19, -430.0, 35.0),
]

# Another lab's measurements, from a far higher speed regime (Vc 150..200) and
# generated from an exactly linear rule. That combination is deliberate: it is
# the §5.3 case worth getting right — the existing model cannot reach this
# regime, so **transfer is poor**, while the data is perfectly self-consistent,
# so **refit is excellent**. That contribution is the most valuable kind there
# is, and an owner who reads only the transfer score would throw it away.
#
# The coefficients agree with the project's declared physical priors, so the
# PIML penalty is zero here and the refit is not biased by it.
DESIGN = [
    (3, 18, 150, 0.15), (3, 26, 200, 0.20), (6, 18, 200, 0.15), (6, 26, 150, 0.20),
    (3, 22, 175, 0.18), (6, 22, 175, 0.16), (4, 20, 160, 0.19), (5, 24, 190, 0.15),
    (3, 26, 150, 0.17), (6, 18, 200, 0.20),
]
OTHER_ROWS = [
    (g, rb, vc, h,
     round(-300.0 + 2.0 * g + 1.5 * rb - 1.0 * vc - 100.0 * h, 4),
     round(50.0 + 1.0 * g + 0.5 * rb - 0.5 * vc - 50.0 * h, 4))
    for g, rb, vc, h in DESIGN
]

TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]
IN_DOMAIN = {
    "rake_angle": 0, "edge_radius": 22,
    "cutting_speed": 40, "uncut_chip_thickness": 0.17,
}

print("== setup ==")
for opener, who in ((OWNER, "owner"), (OTHER, "other")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-5-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}", "institution": f"{who.title()} Institute",
    })
    check(f"register {who}", status == 201, f"status={status}")

status, project = call(OWNER, "/api/projects", {
    "title": f"Review and access {tag}", "material": "Ti-6Al-4V", "process": "turning",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "inputs": [
        # Priors the synthetic data above agrees with, so PIML costs nothing.
        {"variable_key": "rake_angle", "required": True, "penalised_sign": -1},
        {"variable_key": "edge_radius", "required": True, "penalised_sign": -1},
        {"variable_key": "cutting_speed", "required": True, "penalised_sign": 1},
        {"variable_key": "uncut_chip_thickness", "required": True, "penalised_sign": 1},
    ],
    "targets": [{"variable_key": k} for k in TARGETS],
})
check("create project", status == 201, f"status={status}")
slug = (project or {}).get("slug")

status, preview = upload(OWNER, slug, "owner.csv", to_csv(OWNER_ROWS))
check("owner uploads", status == 200, f"status={status}")
status, owner_contribution = commit(OWNER, slug, preview, measurement_method="XRD")
check("owner data accepted without review", status == 201, f"status={status}")

# The very first contribution has nothing to transfer against, and the score
# says so rather than inventing a number.
first_transfer = (owner_contribution or {}).get("transfer_score") or {}
check("the first contribution has no transfer score",
      first_transfer.get("version") is None and bool(first_transfer.get("note")),
      str(first_transfer)[:120])

versions = wait_for_version(slug, 1)
check("a first model was published", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

# --------------------------------------------------------------------------- #
print("\n== the two scores (§5.3) ==")
status, other_preview = upload(OTHER, slug, "other.csv", to_csv(OTHER_ROWS))
check("another lab uploads", status == 200, f"status={status}")
status, contribution = commit(OTHER, slug, other_preview, measurement_method="hole-drilling")
check("it lands pending", status == 201 and contribution["status"] == "pending",
      f"status={status}")
contribution_id = (contribution or {}).get("id")

transfer = (contribution or {}).get("transfer_score") or {}
refit = (contribution or {}).get("refit_score") or {}
check("a transfer score was computed on arrival", bool(transfer.get("per_target")),
      str(transfer)[:160])
check("it records which version it was measured against", transfer.get("version") == 1,
      str(transfer.get("version")))
check("a refit score was computed on arrival", bool(refit.get("per_target")),
      str(refit)[:160])
check("the refit uses the linear reference engine", refit.get("engine") in ("piml", "linear"),
      str(refit.get("engine")))

target = TARGETS[0]
transfer_r2 = (transfer.get("per_target", {}).get(target) or {}).get("r2")
refit_r2 = (refit.get("per_target", {}).get(target) or {}).get("r2_cv")
check("both scores are numbers", transfer_r2 is not None and refit_r2 is not None,
      f"transfer={transfer_r2} refit={refit_r2}")
if transfer_r2 is not None and refit_r2 is not None:
    # The case the review interface must not let an owner misread: data the
    # current model cannot reach, which is nonetheless entirely self-consistent.
    check("this data is internally predictable (refit is excellent)", refit_r2 > 0.9,
          f"refit r2_cv={refit_r2:.4f}")
    check("but the published model does not reach it (transfer is far worse)",
          transfer_r2 < refit_r2, f"transfer={transfer_r2:.3f} refit={refit_r2:.3f}")

# --------------------------------------------------------------------------- #
print("\n== only the owner reviews ==")
status, _ = call(ANON, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                 {"decision": "accept"})
check("an anonymous visitor cannot review", status == 401, f"status={status}")
status, _ = call(OTHER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                 {"decision": "accept"})
check("a contributor cannot accept their own contribution", status == 403, f"status={status}")
status, _ = call(OWNER, f"/api/projects/{slug}/contributions/999999/review",
                 {"decision": "accept"})
check("a contribution from another project is a 404", status == 404, f"status={status}")

print("\n== before acceptance, nothing is unlocked ==")
status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("a pending contributor cannot predict", status == 403, f"status={status}")

# --------------------------------------------------------------------------- #
print("\n== accepting ==")
status, result = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                      {"decision": "accept", "note": "Different regime, clean data."})
check("the owner accepts", status == 200, f"status={status}")
check("access was granted", (result or {}).get("access_granted") is True, str(result)[:120])
check("a retrain was queued", (result or {}).get("training_job") is not None)
check("the decision is recorded on the contribution",
      (result or {}).get("contribution", {}).get("review_note") == "Different regime, clean data.")
check("and it is now accepted",
      (result or {}).get("contribution", {}).get("status") == "accepted")

versions = wait_for_version(slug, 2)
check("a new version was published", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("the contributor can now use the model", status == 200, f"status={status}")
status, _ = fetch_bytes(OTHER, f"/api/projects/{slug}/export")
check("and export it", status == 200, f"status={status}")
# Model access is not file access. §4.1: a contributor never sees another
# contributor's file, however much they have contributed themselves.
owner_contribution_id = (owner_contribution or {}).get("id")
status, _ = fetch_bytes(
    OTHER, f"/api/projects/{slug}/contributions/{owner_contribution_id}/download")
check("but still cannot read the owner's file", status == 403, f"status={status}")

status, detail = call(ANON, f"/api/projects/{slug}")
check("the row count grew", (detail or {}).get("n_rows_total") == 20,
      str((detail or {}).get("n_rows_total")))
check("the project now has two contributors", (detail or {}).get("n_contributors") == 2,
      str((detail or {}).get("n_contributors")))

speed = next(i for i in detail["inputs"] if i["variable"]["key"] == "cutting_speed")
# The validity-domain bar of lot 3 finally has something to draw: the owner's
# band stays where the owner's data is, and the covered band reaches past it.
check("the published domain widened past the owner's own data",
      speed["observed_max"] == 200 and speed["owner_max"] == 60, str(speed))
check("and the lower bound is still the owner's",
      speed["observed_min"] == 20 and speed["owner_min"] == 20, str(speed))

status, contributors = call(ANON, f"/api/projects/{slug}/contributors")
check("the new contributor is credited publicly", len(contributors or []) == 2,
      str([c["name"] for c in (contributors or [])]))

if versions:
    sources = {s["contributor_name"] for s in versions[0]["sources"]}
    check("the lineage names both labs", len(sources) == 2, str(sources))

print("\n== accepting twice changes nothing ==")
status, again = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                     {"decision": "accept"})
check("a second accept is accepted quietly", status == 200, f"status={status}")
check("and queues no second retrain", (again or {}).get("training_job") is None,
      str((again or {}).get("training_job")))

# --------------------------------------------------------------------------- #
print("\n== rejecting what was accepted ==")
status, rejected = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                        {"decision": "reject", "note": "On reflection, method mismatch."})
check("the owner can reject an accepted contribution", status == 200, f"status={status}")
check("access was revoked", (rejected or {}).get("access_revoked") is True, str(rejected)[:120])
check("a retrain was queued", (rejected or {}).get("training_job") is not None)

versions = wait_for_version(slug, 3)
check("a version without it was published", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")

status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("the model locks again", status == 403, f"status={status}")
status, _ = fetch_bytes(OTHER, f"/api/projects/{slug}/export")
check("so does the export", status == 403, f"status={status}")

status, detail = call(ANON, f"/api/projects/{slug}")
check("the row count fell back", (detail or {}).get("n_rows_total") == 10,
      str((detail or {}).get("n_rows_total")))
speed = next(i for i in detail["inputs"] if i["variable"]["key"] == "cutting_speed")
check("the published domain narrowed back to the owner's data",
      speed["observed_max"] == 60, str(speed))
status, contributors = call(ANON, f"/api/projects/{slug}/contributors")
check("and the credit is withdrawn with it", len(contributors or []) == 1,
      str([c["name"] for c in (contributors or [])]))

if versions:
    # ARCHITECTURE.md §8.4 — this is the invariant, stated plainly.
    ids = {s["contribution_id"] for s in versions[0]["sources"]}
    check("the rejected contribution left no trace in the new version",
          contribution_id not in ids, str(ids))
    check("the owner's own data is still in it", owner_contribution_id in ids, str(ids))

# --------------------------------------------------------------------------- #
print("\n== the contributor can take their data back ==")
status, reaccepted = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                          {"decision": "accept", "note": "Reinstated."})
check("a rejection is not final", status == 200, f"status={status}")
check("access comes back", (reaccepted or {}).get("access_granted") is True)
versions = wait_for_version(slug, 4)
check("and so does the data", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")
status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("the contributor can use the model again", status == 200, f"status={status}")

status, _ = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/withdraw", {})
check("the owner cannot withdraw on the contributor's behalf", status == 403, f"status={status}")

status, withdrawn = call(OTHER, f"/api/projects/{slug}/contributions/{contribution_id}/withdraw", {})
check("the contributor withdraws", status == 200, f"status={status}")
check("their contribution is withdrawn",
      (withdrawn or {}).get("contribution", {}).get("status") == "withdrawn",
      str((withdrawn or {}).get("contribution", {}).get("status")))
# Access is the counterpart of the data being there, not a reward for having
# once uploaded it.
check("and their access goes with it", (withdrawn or {}).get("access_revoked") is True)
check("a retrain was queued", (withdrawn or {}).get("training_job") is not None)

versions = wait_for_version(slug, 5)
check("a version without the withdrawn data was published", versions is not None,
      "timed out" if versions is None else f"v{versions[0]['number']}")
if versions:
    ids = {s["contribution_id"] for s in versions[0]["sources"]}
    check("the withdrawn contribution left no trace either",
          contribution_id not in ids, str(ids))

status, _ = call(OTHER, f"/api/projects/{slug}/predict", {"values": IN_DOMAIN})
check("the model is locked to them once more", status == 403, f"status={status}")

status, _ = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                 {"decision": "accept"})
check("the owner cannot reinstate what the contributor withdrew", status == 409,
      f"status={status}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
