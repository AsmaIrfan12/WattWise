#!/usr/bin/env python3
"""
WattWise end-to-end check of the core loop, over HTTP against a running stack:

    admin sends an actionable alert (campaign)
      → the user sees it in their list, undecided
      → the user opens it                       (opened_at recorded once)
      → the user answers "Later"                (DEFERRED + reminder time)
      → the user completes it with what they did, feedback and a rating
      → the admin sees every step: decisions explorer, campaign drill-down, funnel
      → a second identical send is NOT silently dropped
      → the CSV export contains the row, flagged not-simulated

Exit code 0 = every assertion held. Safe to run against production: it targets ONE
user (pass a synthetic/test account) and everything it creates is labelled "[e2e]".

    python e2e_loop.py --base http://localhost:8000 \\
        --admin-email admin@… --admin-password … --user-email … --user-password …
"""
import argparse
import sys
import time

import httpx

FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def login(client: httpx.Client, email: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    body = r.json()
    return {"Authorization": f"Bearer {body['access_token']}", "_user_id": str(body["user_id"])}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--admin-email", required=True)
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--user-email", required=True)
    ap.add_argument("--user-password", required=True)
    args = ap.parse_args()

    stamp = time.strftime("%H%M%S")
    title = f"[e2e] Please switch off standby devices {stamp}"

    with httpx.Client(base_url=args.base, timeout=30) as c:
        admin = login(c, args.admin_email, args.admin_password)
        user = login(c, args.user_email, args.user_password)
        user_id = int(user.pop("_user_id"))
        admin.pop("_user_id")

        print("1. Admin sends an actionable alert to one user")
        payload = {
            "user_ids": [user_id], "title": title,
            "message": "Automated end-to-end check of the alert loop. Safe to ignore.",
            "notification_type": "ENERGY_ALERT", "severity": "WARNING",
            "requires_user_action": True, "action_hint": "Switch off anything on standby",
            "action_button_text": "I switched it off",
        }
        r = c.post("/api/admin/notifications/send", json=payload, headers=admin)
        check("send returns 200", r.status_code == 200, r.text[:200])
        sent = r.json()
        campaign_id = sent.get("campaign_id")
        check("a campaign was recorded", bool(campaign_id))
        check("exactly one alert created", sent.get("notifications_created") == 1, str(sent))

        print("2. A second identical send must also arrive (no silent dedup)")
        r2 = c.post("/api/admin/notifications/send", json=payload, headers=admin)
        check("second send created an alert", r2.json().get("notifications_created") == 1, r2.text[:200])
        second_campaign = r2.json().get("campaign_id")

        print("3. User lists alerts")
        r = c.get("/api/notifications/?limit=50&filter=action_required", headers=user)
        check("list returns 200", r.status_code == 200, r.text[:200])
        mine = [n for n in r.json() if n.get("title") == title]
        check("both alerts are waiting for a response", len(mine) == 2, f"found {len(mine)}")
        if not mine:
            return 1
        notif = next(n for n in mine if n["metadata_json"].get("campaign_id") == campaign_id)
        nid = notif["id"]
        check("alert is from ADMIN", notif.get("source") == "ADMIN")
        check("alert has its action button text", notif.get("action_button_text") == "I switched it off")
        check("alert is undecided and unopened", notif.get("decision") is None and notif.get("opened_at") is None)

        print("4. User opens the alert")
        r = c.post(f"/api/notifications/{nid}/open", headers=user)
        opened_at = r.json().get("opened_at")
        check("open recorded", r.status_code == 200 and bool(opened_at), r.text[:200])
        r = c.post(f"/api/notifications/{nid}/open", headers=user)
        check("opening again keeps the first timestamp", r.json().get("opened_at") == opened_at)

        print("5. User answers 'Later'")
        r = c.post("/api/decisions/", json={"notification_id": nid, "decision_type": "DEFERRED",
                                             "remind_in_minutes": 60}, headers=user)
        check("decision recorded (201)", r.status_code == 201, r.text[:200])
        decision = r.json()
        did = decision.get("id")
        check("reminder time set", bool(decision.get("remind_at")))
        r = c.post("/api/decisions/", json={"notification_id": nid, "decision_type": "ACCEPTED"}, headers=user)
        check("a second POST is refused (409), not duplicated", r.status_code == 409)
        r = c.get("/api/notifications/?limit=50", headers=user)
        listed = next((n for n in r.json() if n["id"] == nid), {})
        check("the list now carries the decision", (listed.get("decision") or {}).get("decision_type") == "DEFERRED")
        r = c.get("/api/notifications/?limit=50&filter=action_required", headers=user)
        check("answered alert left the action-required list", all(n["id"] != nid for n in r.json()))

        print("6. User completes it: what they did, feedback, rating")
        r = c.patch(f"/api/decisions/{did}", json={
            "decision_type": "ACCEPTED", "action_taken": "Switched off the TV and games console at the wall",
            "user_feedback_text": "Easy to do, the reminder helped", "user_satisfaction": 5,
        }, headers=user)
        check("update accepted", r.status_code == 200, r.text[:200])
        updated = r.json()
        check("now ACCEPTED", updated.get("decision_type") == "ACCEPTED")
        check("action and rating stored", updated.get("action_taken", "").startswith("Switched off")
              and updated.get("user_satisfaction") == 5)
        check("reminder cleared", updated.get("remind_at") is None)
        check("history shows the alert title", updated.get("notification_title") == title)

        print("7. Another user's decision cannot be touched; client events are accepted")
        r = c.patch(f"/api/decisions/{did}", json={"user_satisfaction": 1}, headers=admin)
        check("other accounts get 404", r.status_code == 404)
        r = c.post("/api/interactions/", json={"interaction_type": "VIEW_DASHBOARD", "screen_name": "home",
                                                "session_id": f"e2e-{stamp}"}, headers=user)
        check("interaction event recorded", r.status_code == 201, r.text[:200])
        r = c.post("/api/interactions/", json={"interaction_type": "DROP_TABLE"}, headers=user)
        check("unknown interaction types are rejected", r.status_code == 422)

        print("8. Admin sees the whole story")
        r = c.get(f"/api/admin/decisions?cohort=all&campaign_id={campaign_id}", headers=admin)
        check("decisions explorer returns 200", r.status_code == 200, r.text[:200])
        items = r.json().get("items", [])
        row = items[0] if items else {}
        check("explorer has the decision", len(items) == 1 and row.get("decision_id") == did)
        check("explorer shows who/what/when", row.get("user_id") == user_id and row.get("alert_title") == title
              and row.get("decision_type") == "ACCEPTED" and bool(row.get("alert_opened_at")))
        check("explorer shows the reported action + feedback", "TV" in (row.get("action_taken") or "")
              and row.get("user_satisfaction") == 5)
        check("row is not flagged simulated", row.get("is_simulated") is False)

        r = c.get(f"/api/admin/campaigns/{campaign_id}?cohort=all", headers=admin)
        detail = r.json()
        rec = (detail.get("recipients") or [{}])[0]
        check("campaign drill-down shows the recipient as decided", rec.get("status") == "decided"
              and (rec.get("decision") or {}).get("decision_type") == "ACCEPTED", r.text[:200])
        r = c.get(f"/api/admin/campaigns/{second_campaign}?cohort=all", headers=admin)
        rec2 = (r.json().get("recipients") or [{}])[0]
        check("the unanswered send shows as not decided", rec2.get("status") in ("delivered", "seen", "opened"))

        r = c.get("/api/admin/campaigns?cohort=all&limit=5", headers=admin)
        funnel = next((x["funnel"] for x in r.json().get("campaigns", []) if x["id"] == campaign_id), None) or {}
        check("campaign funnel: 1 sent, 1 opened, 1 decided", (funnel.get("sent"), funnel.get("opened"),
              funnel.get("decided")) == (1, 1, 1), str(funnel))

        r = c.get("/api/admin/notifications/funnel?cohort=all&days=1&source=ADMIN", headers=admin)
        overall = r.json().get("overall", {})
        check("funnel endpoint counts the sends", r.status_code == 200 and overall.get("sent", 0) >= 2, r.text[:200])
        check("funnel reports non-response", overall.get("no_response", 0) >= 1)

        r = c.get(f"/api/admin/decisions?cohort=all&campaign_id={campaign_id}&format=csv", headers=admin)
        check("CSV export contains the decision", r.status_code == 200 and str(did) in r.text and "is_simulated" in r.text)

        r = c.get(f"/api/admin/users/{user_id}/details", headers=admin)
        recent = r.json().get("recent_notifications", [])
        mine = next((n for n in recent if n["id"] == nid), {})
        check("user panel shows the alert with its decision", (mine.get("decision") or {}).get("decision_type") == "ACCEPTED")

        r = c.get("/api/admin/decisions", headers=user)
        check("non-admins cannot read the explorer", r.status_code == 403)

        # These sends and answers were made by this script, not by a person. Flag them so
        # they stay out of rankings and personas (they remain visible, marked "simulated").
        flagged = 0
        for cid in (campaign_id, second_campaign):
            r = c.post(f"/api/admin/campaigns/{cid}/mark-test", headers=admin)
            if r.status_code == 200:
                flagged += r.json().get("decisions_flagged", 0)
        r = c.get(f"/api/admin/decisions?cohort=all&campaign_id={campaign_id}", headers=admin)
        rows = r.json().get("items", [])
        check("the test's own answers are flagged as generated", flagged >= 1 and rows and all(d["is_simulated"] for d in rows),
              f"flagged={flagged} rows={[(d['decision_id'], d['is_simulated']) for d in rows]}")

    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}): " + "; ".join(FAILED))
        return 1
    print("All end-to-end loop checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
