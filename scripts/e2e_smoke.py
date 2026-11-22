#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end smoke test of a running Annona server: the first-run path of the README.

    python scripts/e2e_smoke.py http://localhost:8000 <token>

It sets up a household, a person and a kitchen, expects the ``demo`` store to be loaded
(``python -m annona_server.seed --demo-store``) and the server to run with ``ANNONA_FAKE_LLM=1`` (or
a real AI key), generates a menu, and reads back the plan, today's meals, a recipe and the shopping
list. Standard library only. Exits non-zero with a clear message on the first failure.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta


def call(base: str, token: str, method: str, path: str, body: dict | None = None):
    request = urllib.request.Request(
        base + path,
        method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as error:
        raw = error.read()
        return error.code, (json.loads(raw) if raw else None)


def check(ok: bool, message: str) -> None:
    print(("ok   " if ok else "FAIL ") + message)
    if not ok:
        sys.exit(1)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    base, token = sys.argv[1].rstrip("/"), sys.argv[2]

    for _ in range(30):  # the server may still be starting
        try:
            with urllib.request.urlopen(base + "/health", timeout=5) as r:
                if r.status == 200:
                    break
        except OSError:
            time.sleep(2)
    else:
        check(False, "the server answers /health")
    check(True, "the server answers /health")

    status, _ = call(base, token, "GET", "/api/v1/stores")
    check(status == 200, "the token is accepted")

    status, _ = call(
        base, token, "PUT", "/api/v1/household", {"name": "Casa", "weekly_budget_cents": 8000}
    )
    check(status == 200, "household created")
    status, person = call(
        base,
        token,
        "POST",
        "/api/v1/profiles",
        {
            "name": "Sam",
            "sex": "female",
            "birth_date": "1990-01-01",
            "height_cm": 165,
            "weight_kg": 60,
            "activity": "active",
            "allergies_confirmed": True,
        },
    )
    check(status in (200, 201), "person created with daily targets")
    check(float(person["targets"]["energy_kcal"]) > 1000, "daily energy target is computed")
    status, _ = call(base, token, "PUT", "/api/v1/equipment", {"hob_type": "ceramic", "oven": True})
    check(status == 200, "kitchen saved")

    status, stores = call(base, token, "GET", "/api/v1/catalog/stores")
    check(
        status == 200 and any(s["store_id"] == "demo" for s in stores), "the demo store is loaded"
    )

    today = date.today()
    monday = (today - timedelta(days=today.weekday())).isoformat()
    status, job = call(
        base,
        token,
        "POST",
        "/api/v1/plans",
        {
            "store_id": "demo",
            "regenerate": True,
            "schedule": {"week_start": monday, "weekdays": [0, 1, 2]},
        },
    )
    check(status == 202, "plan generation accepted")
    for _ in range(90):
        _, state = call(base, token, "GET", job["status_url"])
        if state["status"] in ("done", "failed"):
            break
        time.sleep(2)
    check(state["status"] == "done", f"the plan job finished ({state.get('error')})")
    check(
        state["result"].get("accepted") is True,
        f"the menu passed the checks {state['result'].get('issues', '')}",
    )
    plan_id = state["result"]["plan_id"]

    _, week = call(base, token, "GET", f"/api/v1/plans?week={monday}")
    check(len(week["meals"]) == 12, "the week has 12 meals (3 days x 4)")
    _, shopping = call(base, token, "GET", f"/api/v1/plans/{plan_id}/shopping-list")
    check(shopping["total_cents"] > 0 and shopping["items"], "the shopping list is priced")
    status, recipe = call(
        base, token, "POST", "/api/v1/meals/recipe", {"day": monday, "slot": "lunch"}
    )
    check(status == 200 and recipe["steps"], "a recipe is written for a meal")
    total = shopping["total_cents"] / 100
    print(f"\nAll good: {len(week['meals'])} meals, shopping list {total:.2f} EUR.")


if __name__ == "__main__":
    main()
