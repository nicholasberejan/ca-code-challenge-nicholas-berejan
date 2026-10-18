"""End-to-end token flow against the running services (run by scripts/verify.sh).

Runs in a one-off `auth` container: it reaches both services over HTTP like
any client, and uses the auth service's ORM only to set up test users and to
demote/deactivate them as an operator would. Phases, run in order:

  main    login, PATCH, 401/403, demotion, deactivation, replay, logout;
          leaves an editor access token in the state file
  outage  (auth service stopped) public reads and PATCH with that token work,
          login fails
  verify  (after import_wordpress) the edited description survived;
          restores it and removes the test users
  cleanup restore and remove test users (also run after a failure)
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth.models import Group  # noqa: E402

from accounts.models import User  # noqa: E402

AUTH = "http://auth:8001"
WEB = "http://web:8000"
BRAND = "acme-insurance"
PASSWORD = "e2e-password-not-secret"
STATE = Path("/state/state.json")
USERS = {"e2e-editor": "editor", "e2e-editor-2": "editor", "e2e-reader": "reader"}


def request(method: str, url: str, body: dict | None = None, token: str | None = None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Host": "localhost"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, raw.decode(errors="replace")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")
    print(f"  ok  {message}")


def login(username: str) -> dict:
    status, body = request("POST", f"{AUTH}/api/token/", {"username": username, "password": PASSWORD})
    check(status == 200, f"{username} logs in")
    return body


def refresh(token: str):
    return request("POST", f"{AUTH}/api/token/refresh/", {"refresh": token})


def patch(token: str | None, text: str):
    return request("PATCH", f"{WEB}/api/brands/{BRAND}/", {"short_description": text}, token)


def current_description() -> str:
    status, body = request("GET", f"{WEB}/api/brands/?page_size=50")
    check(status == 200, "GET /api/brands/ is public")
    return next(b["short_description"] for b in body["results"] if b["slug"] == BRAND)


def create_users() -> None:
    for username, role in USERS.items():
        User.objects.filter(username=username).delete()
        user = User.objects.create_user(username=username, password=PASSWORD)
        user.groups.add(Group.objects.get(name=role))


def main() -> None:
    create_users()
    state = {"original": current_description()}
    STATE.write_text(json.dumps(state))

    editor = login("e2e-editor")
    status, body = patch(editor["access"], "  Edited end to end.  ")
    check(status == 200 and body["short_description"] == "Edited end to end.", "editor PATCH succeeds (trimmed)")

    reader = login("e2e-reader")
    check(patch(reader["access"], "x")[0] == 403, "reader PATCH is 403")
    check(patch(None, "x")[0] == 401, "PATCH without a token is 401")
    check(patch("not.a.token", "x")[0] == 401, "PATCH with an invalid token is 401")
    check(patch(editor["refresh"], "x")[0] == 401, "a refresh token is not accepted as an access token")

    # Demotion takes effect at refresh; the old access token stays valid.
    user = User.objects.get(username="e2e-editor")
    user.groups.set([Group.objects.get(name="reader")])
    status, rotated = refresh(editor["refresh"])
    check(status == 200, "demoted editor can still refresh")
    check(patch(rotated["access"], "x")[0] == 403, "access token from refresh after demotion: PATCH is 403")
    check(patch(editor["access"], "Edited end to end.")[0] == 200, "pre-demotion access token still works until it expires (accepted)")

    # Replay of a rotated refresh token.
    check(refresh(editor["refresh"])[0] == 401, "a used refresh token cannot be replayed")
    status, again = refresh(rotated["refresh"])
    check(status == 200, "the rotated refresh token works")

    # Deactivation stops refresh.
    User.objects.filter(username="e2e-editor").update(is_active=False)
    check(refresh(again["refresh"])[0] == 401, "deactivated user cannot refresh")

    # Logout.
    session = login("e2e-reader")
    status, _ = request("POST", f"{AUTH}/api/token/logout/", {"refresh": session["refresh"]})
    check(status == 204, "logout succeeds")
    check(refresh(session["refresh"])[0] == 401, "a logged-out refresh token cannot be used")

    # An editor token for the outage phase.
    state["outage_token"] = login("e2e-editor-2")["access"]
    STATE.write_text(json.dumps(state))


def outage() -> None:
    state = json.loads(STATE.read_text())
    try:
        request("POST", f"{AUTH}/api/token/", {"username": "e2e-editor-2", "password": PASSWORD})
        check(False, "login fails while auth is down")
    except urllib.error.URLError:
        check(True, "login fails while auth is down")
    for path in ["/", "/brand/", f"/brand/{BRAND}/", "/api/brands/", "/api/industries/"]:
        check(_page(path) == 200, f"GET {path} works while auth is down")
    review = next(iter(request("GET", f"{WEB}/api/brands/?page_size=1")[1]["results"]))["top_review"]["slug"]
    check(_page(f"/review/{review}/") == 200, "GET /review/<slug>/ works while auth is down")
    status, body = patch(state["outage_token"], "Edited while auth is down.")
    check(status == 200, "a valid editor token still PATCHes while auth is down")


def _page(path: str) -> int:
    req = urllib.request.Request(f"{WEB}{path}", headers={"Host": "localhost"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def verify() -> None:
    check(current_description() == "Edited while auth is down.", "the edited description survived import_wordpress")


def cleanup() -> None:
    if STATE.exists():
        state = json.loads(STATE.read_text())
        User.objects.filter(username__in=list(USERS)).delete()
        user = User.objects.create_user(username="e2e-restore", password=PASSWORD)
        user.groups.add(Group.objects.get(name="editor"))
        token = login("e2e-restore")["access"]
        check(patch(token, state["original"])[0] == 200, "original description restored")
        STATE.unlink()
    User.objects.filter(username__in=[*USERS, "e2e-restore"]).delete()


if __name__ == "__main__":
    {"main": main, "outage": outage, "verify": verify, "cleanup": cleanup}[sys.argv[1]]()
