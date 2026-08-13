"""End-to-end smoke test of the notification system and the personal dashboard.

ROADMAP.md named this the platform's most keenly felt gap: an owner learned of
a pending contribution only by visiting the project page, and a contributor
learned of a decision the same way — a contribution could sit unseen
indefinitely. This walks the loop that closes it: a contribution submitted
notifies the owner, and a review decision notifies the contributor, each
reflected in `/api/notifications` and in the `/api/me/*` dashboard endpoints
`Me.tsx` reads.

Deliberately not re-testing what smoke_lot5.py already covers (access grant,
revocation, the two §5.3 scores) — only the notification and dashboard layer
on top of that same review flow.
"""
import http.cookiejar
import json
import sys
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


def unread(opener):
    status, body = call(opener, "/api/notifications/unread-count")
    check("unread-count call succeeds", status == 200, f"status={status}")
    return (body or {}).get("count", -1)


HEADER = "gamma (deg),r_beta (um),Vc (m/min),h (mm),SRS_L (MPa),SRS_T (MPa)\n"


def to_csv(rows):
    return (HEADER + "".join(",".join(str(v) for v in r) + "\n" for r in rows)).encode()


OWNER_ROWS = [
    (5, 16, 20, 0.15, -454.0, -73.0), (5, 16, 20, 0.20, -387.0, 9.0),
    (5, 16, 60, 0.15, -400.0, 52.0), (5, 30, 60, 0.15, -619.0, -51.0),
    (5, 16, 60, 0.20, -423.0, 25.0), (-6, 16, 60, 0.15, -273.0, 64.0),
]
OTHER_ROWS = [
    (3, 18, 150, 0.15, -240.0, 40.0), (3, 26, 200, 0.20, -260.0, 35.0),
    (6, 18, 200, 0.15, -255.0, 38.0), (6, 26, 150, 0.20, -245.0, 42.0),
    (3, 22, 175, 0.18, -250.0, 39.0),
]
SECOND_OTHER_ROWS = [
    (4, 20, 160, 0.19, -252.0, 37.0), (5, 24, 190, 0.15, -248.0, 41.0),
    (3, 26, 150, 0.17, -256.0, 36.0), (6, 18, 200, 0.20, -244.0, 43.0),
    (3, 18, 150, 0.16, -258.0, 34.0),
]
TARGETS = ["residual_stress_axial", "residual_stress_circumferential"]

print("== setup ==")
for opener, who in ((OWNER, "owner"), (OTHER, "other")):
    status, _ = call(opener, "/api/auth/register", {
        "email": f"{who}-notif-{tag}@example.com", "password": "a-long-enough-password",
        "full_name": f"{who.title()} {tag}", "institution": f"{who.title()} Institute",
    })
    check(f"register {who}", status == 201, f"status={status}")

status, project = call(OWNER, "/api/projects", {
    "title": f"Notifications {tag}", "material": "Ti-6Al-4V", "process": "turning",
    "visibility": "public", "main_engine": "piml", "accepts_federated": True,
    "inputs": [
        {"variable_key": "rake_angle", "required": True},
        {"variable_key": "edge_radius", "required": True},
        {"variable_key": "cutting_speed", "required": True},
        {"variable_key": "uncut_chip_thickness", "required": True},
    ],
    "targets": [{"variable_key": k} for k in TARGETS],
})
check("create project", status == 201, f"status={status}")
slug = (project or {}).get("slug")

status, _ = call(ANON, "/api/notifications/unread-count")
check("notifications require sign-in", status == 401, f"status={status}")

owner_before = unread(OWNER)
other_before = unread(OTHER)
check("nobody starts with unread notifications", owner_before == 0 and other_before == 0,
      f"owner={owner_before} other={other_before}")

# --------------------------------------------------------------------------- #
print("\n== the owner's own data notifies nobody ==")
status, preview = upload(OWNER, slug, "owner.csv", to_csv(OWNER_ROWS))
check("owner uploads", status == 200, f"status={status}")
status, owner_contribution = commit(OWNER, slug, preview, measurement_method="XRD")
check("owner data is auto-accepted", status == 201 and owner_contribution["status"] == "accepted",
      f"status={status}")
check("the owner does not notify themselves", unread(OWNER) == 0, f"count={unread(OWNER)}")

status, mine = call(OWNER, "/api/me/contributions")
check("it shows up in the owner's own contribution list", status == 200 and len(mine or []) == 1,
      f"status={status} n={len(mine or [])}")
status, queue = call(OWNER, "/api/me/review-queue")
check("nothing is waiting for review yet", status == 200 and queue == [], str(queue))

# --------------------------------------------------------------------------- #
print("\n== a submitted contribution notifies the owner ==")
status, other_preview = upload(OTHER, slug, "other.csv", to_csv(OTHER_ROWS))
check("another lab uploads", status == 200, f"status={status}")
status, contribution = commit(OTHER, slug, other_preview, measurement_method="hole-drilling")
check("it lands pending", status == 201 and contribution["status"] == "pending", f"status={status}")
contribution_id = (contribution or {}).get("id")

check("the owner's unread count went up by one", unread(OWNER) == owner_before + 1,
      f"count={unread(OWNER)}")
check("the contributor was not notified of their own submission", unread(OTHER) == other_before,
      f"count={unread(OTHER)}")

status, notes = call(OWNER, "/api/notifications")
check("the owner's list has it", status == 200 and len(notes or []) >= 1, f"status={status}")
submitted = next((n for n in (notes or []) if n["contribution_id"] == contribution_id), None)
check("it is a contribution_submitted notification, unread, for this project",
      submitted is not None
      and submitted["kind"] == "contribution_submitted"
      and submitted["read_at"] is None
      and submitted["project_slug"] == slug,
      str(submitted))

status, queue = call(OWNER, "/api/me/review-queue")
check("the owner's review queue has exactly this one", status == 200 and len(queue or []) == 1
      and queue[0]["contribution_id"] == contribution_id
      and queue[0]["contributor_name"] == f"Other {tag}",
      str(queue))

status, other_mine = call(OTHER, "/api/me/contributions")
check("the contributor sees it as pending in their own list",
      status == 200 and other_mine and other_mine[0]["status"] == "pending", str(other_mine))
status, other_access = call(OTHER, "/api/me/access")
check("no model access yet", status == 200 and other_access == [], str(other_access))

# --------------------------------------------------------------------------- #
print("\n== acceptance notifies the contributor ==")
owner_before, other_before = unread(OWNER), unread(OTHER)
status, result = call(OWNER, f"/api/projects/{slug}/contributions/{contribution_id}/review",
                      {"decision": "accept", "note": "Clean data, welcome aboard."})
check("the owner accepts", status == 200, f"status={status}")

check("the contributor's unread count went up by one", unread(OTHER) == other_before + 1,
      f"count={unread(OTHER)}")
check("the owner was not notified of their own decision", unread(OWNER) == owner_before,
      f"count={unread(OWNER)}")

status, notes = call(OTHER, "/api/notifications")
accepted = next((n for n in (notes or []) if n["contribution_id"] == contribution_id), None)
check("it is a contribution_accepted notification carrying the review note",
      accepted is not None
      and accepted["kind"] == "contribution_accepted"
      and "Clean data, welcome aboard." in (accepted["body"] or ""),
      str(accepted))

status, queue = call(OWNER, "/api/me/review-queue")
check("the owner's review queue is empty again", status == 200 and queue == [], str(queue))
status, other_access = call(OTHER, "/api/me/access")
check("the contributor now has model access", status == 200 and len(other_access or []) == 1
      and other_access[0]["project_slug"] == slug and other_access[0]["role"] == "contributor",
      str(other_access))

# --------------------------------------------------------------------------- #
print("\n== rejection notifies the contributor too ==")
status, second_preview = upload(OTHER, slug, "other-2.csv", to_csv(SECOND_OTHER_ROWS))
check("a second contribution uploads", status == 200, f"status={status}")
status, second = commit(OTHER, slug, second_preview, measurement_method="hole-drilling")
check("it lands pending", status == 201, f"status={status}")
second_id = (second or {}).get("id")

other_before = unread(OTHER)
status, rejected = call(OWNER, f"/api/projects/{slug}/contributions/{second_id}/review",
                        {"decision": "reject", "note": "Duplicate of the first submission."})
check("the owner rejects", status == 200, f"status={status}")
status, notes = call(OTHER, "/api/notifications")
rejection = next((n for n in (notes or []) if n["contribution_id"] == second_id), None)
check("a contribution_rejected notification arrives with the note",
      rejection is not None
      and rejection["kind"] == "contribution_rejected"
      and "Duplicate of the first submission." in (rejection["body"] or ""),
      str(rejection))
check("the contributor's unread count went up by one", unread(OTHER) == other_before + 1,
      f"count={unread(OTHER)}")

# --------------------------------------------------------------------------- #
print("\n== reading and permissions ==")
status, _ = call(ANON, f"/api/notifications/{rejection['id']}/read")
check("an anonymous visitor cannot read someone else's notification", status == 401,
      f"status={status}")
status, _ = call(OWNER, f"/api/notifications/{rejection['id']}/read")
check("the owner cannot mark the contributor's notification read", status == 404,
      f"status={status}")

status, marked = call(OTHER, f"/api/notifications/{rejection['id']}/read")
check("the contributor marks it read", status == 200 and marked["read_at"] is not None,
      f"status={status}")
check("unread count dropped by one", unread(OTHER) == other_before, f"count={unread(OTHER)}")

status, result = call(OTHER, "/api/notifications/read-all")
check("read-all succeeds", status == 200, f"status={status}")
check("unread count is now zero", unread(OTHER) == 0, f"count={unread(OTHER)}")

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
