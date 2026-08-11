"""End-to-end smoke test of lot 0, run from outside the container."""
import json
import sys
import urllib.parse
import urllib.request
import http.cookiejar

BASE = "http://localhost:8000"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(path, body=None, method=None):
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
    ok = ok and condition
    print(f"  {'PASS' if condition else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))


print("== Greek column matching (UTF-8 over the wire) ==")
cols = ["Vc (m/min)", "γ (°)", "rβ (µm)", "Cutting Speed", "zzz unknown"]
qs = urllib.parse.urlencode([("columns", c) for c in cols])
status, matched = call(f"/api/variables/match?{qs}")
check("match endpoint responds", status == 200, f"status={status}")
got = {}
for row in matched or []:
    best = row["matches"][0] if row["matches"] else None
    got[row["column"]] = (best["variable"]["key"] if best else None, row["normalised"])
    print(f"    {row['column']!r:16} normalised={row['normalised']!r:14} -> {got[row['column']][0]}")

check("Vc (m/min) -> cutting_speed", got.get("Vc (m/min)", (None,))[0] == "cutting_speed")
check("gamma column -> rake_angle", got.get("γ (°)", (None,))[0] == "rake_angle")
check("r-beta column -> edge_radius", got.get("rβ (µm)", (None,))[0] == "edge_radius")
check("free text 'Cutting Speed' -> cutting_speed", got.get("Cutting Speed", (None,))[0] == "cutting_speed")
check("unknown column matches nothing", got.get("zzz unknown", (None,))[0] is None)

print("\n== Auth round trip ==")
status, body = call("/api/auth/me")
check("/me is 200 and null when signed out", status == 200 and body is None, f"status={status}")

status, body = call("/api/auth/register", {
    "email": "Smoke.Test@Example.com", "password": "correct-horse-battery",
    "full_name": "Smoke Test", "institution": "Nowhere",
})
check("register", status == 201, f"status={status} {body}")
check("email is lowercased", (body or {}).get("email") == "smoke.test@example.com", str((body or {}).get("email")))

status, body = call("/api/auth/me")
check("/me returns the new user after register", status == 200 and body and body["email"] == "smoke.test@example.com")

status, body = call("/api/auth/register", {
    "email": "smoke.test@example.com", "password": "another-password-here",
    "full_name": "Duplicate",
})
check("duplicate email rejected", status == 409, f"status={status}")

status, _ = call("/api/auth/logout", {})
check("logout", status == 204, f"status={status}")
status, body = call("/api/auth/me")
check("/me null after logout", status == 200 and body is None)

status, body = call("/api/auth/login", {"email": "smoke.test@example.com", "password": "wrong"})
check("wrong password rejected", status == 401, f"status={status}")
check("error message does not reveal account existence",
      "Incorrect email address or password" in str((body or {}).get("detail")))

status, body = call("/api/auth/login", {"email": "nobody@example.com", "password": "wrong"})
check("unknown account gives the same message", status == 401 and
      "Incorrect email address or password" in str((body or {}).get("detail")))

status, body = call("/api/auth/login", {"email": "SMOKE.TEST@example.com", "password": "correct-horse-battery"})
check("login is case-insensitive on email", status == 200, f"status={status}")

print("\n== Protected route ==")
call("/api/auth/logout", {})
status, _ = call("/api/variables", {"key": "x", "display_name": "X"})
check("proposing a variable while signed out is 401", status == 401, f"status={status}")

print("\n== Demo project seeded ==")
status, body = call("/api/health")
check("health ok", status == 200 and body["ok"])

print("\n" + ("ALL PASS" if ok else "FAILURES ABOVE"))
sys.exit(0 if ok else 1)
