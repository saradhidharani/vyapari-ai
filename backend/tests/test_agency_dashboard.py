"""Agency dashboard: client list, website counts, and per-client sales totals.

Scenario (paid orders are 2 units, so amounts are 2 × price):
- Client M1 grants manager, paid 2 × ₹100 three days ago.
- Client M2 grants manager, paid 2 × ₹300 three days ago and refunded today.
- Client E grants website editor for one of its two websites.
- Client S grants sales. The agency admin is also a direct manager of S.
- Client X grants only a second agency run by the same admin. Agency staff are direct members of X.
Tests in this module run in file order. Revocation tests come last."""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from conftest import build_business, headers, ok, register

IST = timezone(timedelta(hours=5, minutes=30))
M1_PAISE, M2_PAISE = 20000, 60000


@pytest.fixture(scope="module")
def dash(client):
    users = {name: register(client, f"{name}@dashboard-test.example", f"{name} home") for name in (
        "m1_owner", "m2_owner", "e_owner", "s_owner", "x_owner",
        "admin", "manager_staff", "unassigned_staff", "editor_staff", "outsider",
    )}
    prices = {"m1": 100.0, "m2": 300.0, "e": 500.0, "s": 700.0, "x": 900.0}
    clients = {key: build_business(client, users[f"{key}_owner"]["token"], users[f"{key}_owner"]["business_id"],
                                   f"DASH-{key.upper()}", price, 50) for key, price in prices.items()}

    def owner(key):
        return headers(users[f"{key}_owner"]["token"], clients[key]["business_id"])

    # An archived website is not counted.
    archived = ok(client.post("/api/storefront/sites", headers=owner("m1"), json={"label": "Old site"}), 201)
    ok(client.put(f"/api/storefront/sites/{archived['id']}/archive", headers=owner("m1"), json={"archived": True}))

    agency = ok(client.post("/api/agencies", headers=headers(users["admin"]["token"]), json={"name": "Dash Agency"}), 201)
    admin = headers(users["admin"]["token"])
    for name in ("manager_staff", "unassigned_staff", "editor_staff"):
        ok(client.post(f"/api/agencies/{agency['id']}/members", headers=admin,
                       json={"email": f"{name}@dashboard-test.example", "role": "staff"}), 201)
    code = agency["access_code"]
    for key, body in (("m1", {"role": "manager"}), ("m2", {"role": "manager"}), ("s", {"role": "sales"}),
                      ("e", {"role": "website_editor", "website_ids": [clients["e"]["site"]["id"]]})):
        ok(client.post("/api/workspaces/agencies", headers=owner(key), json={"access_code": code, **body}), 201)

    members = ok(client.get(f"/api/agencies/{agency['id']}/members", headers=admin))
    ids = {m["email"].split("@")[0]: m["id"] for m in members}
    for name, key, role in (("manager_staff", "m1", "manager"), ("editor_staff", "e", "website_editor")):
        ok(client.put(f"/api/agencies/{agency['id']}/clients/{clients[key]['business_id']}/assignments/{ids[name]}",
                      headers=admin, json={"role": role}))

    # Unrelated direct memberships that must not appear in the agency dashboard.
    for email, role in (("manager_staff", "manager"), ("unassigned_staff", "manager"), ("editor_staff", "manager")):
        ok(client.post("/api/workspaces/members", headers=owner("x"),
                       json={"email": f"{email}@dashboard-test.example", "role": role}), 201)
    ok(client.post("/api/workspaces/members", headers=owner("s"),
                   json={"email": "admin@dashboard-test.example", "role": "manager"}), 201)
    # X grants a different agency run by the same admin. It must stay out of Dash Agency's dashboard.
    other = ok(client.post("/api/agencies", headers=admin, json={"name": "Other Agency"}), 201)
    ok(client.post("/api/workspaces/agencies", headers=owner("x"),
                   json={"access_code": other["access_code"], "role": "manager"}), 201)

    # Move M1 and M2 payments to three days ago (IST), then refund M2 today.
    three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    with closing(sqlite3.connect(client.database_path)) as db, db:
        db.execute("UPDATE orders SET paid_at = ? WHERE id IN (?, ?)",
                   (three_days_ago, clients["m1"]["order"]["id"], clients["m2"]["order"]["id"]))
    ok(client.put(f"/api/orders/{clients['m2']['order']['id']}/refund", headers=owner("m2"), json={"restock": False}))
    assert clients["m1"]["order"]["amount_paise"] == M1_PAISE and clients["m2"]["order"]["amount_paise"] == M2_PAISE
    return {"users": users, "clients": clients, "agency": agency, "owner": owner}


def dashboard(client, dash, user, period=None, status=200):
    query = f"?period={period.replace(' ', '%20')}" if period else ""
    response = client.get(f"/api/agencies/{dash['agency']['id']}/dashboard{query}",
                          headers=headers(dash["users"][user]["token"]))
    assert response.status_code == status, response.text
    return response.json()


def test_admin_sees_granted_clients_with_totals_from_report_clients_only(client, dash):
    result = dashboard(client, dash, "admin", "last 7 days")
    names ={dash["clients"][key]["business_id"]: key for key in dash["clients"]}
    seen = {names[c["business_id"]]: c for c in result["clients"]}
    # X (granted to another agency) and the admin's home business are absent.
    assert set(seen) == {"m1", "m2", "e", "s"}

    assert (seen["m1"]["role"], seen["m1"]["website_count"], seen["m1"]["report_access"]) == ("manager", 2, True)
    assert seen["m1"]["sales"]["net_paise"] == M1_PAISE
    assert seen["m2"]["sales"] == {"payments_paise": M2_PAISE, "refunds_paise": M2_PAISE, "net_paise": 0,
                                   "payment_count": 1, "refund_count": 1}
    assert (seen["e"]["role"], seen["e"]["website_count"], seen["e"]["report_access"], seen["e"]["sales"]) == (
        "website_editor", 1, False, None)
    # The admin is a direct manager of S, but the agency granted sales only.
    assert (seen["s"]["role"], seen["s"]["website_count"], seen["s"]["report_access"], seen["s"]["sales"]) == (
        "sales", None, False, None)

    assert result["combined"] == {"payments_paise": M1_PAISE + M2_PAISE, "refunds_paise": M2_PAISE,
                                  "net_paise": M1_PAISE, "payment_count": 2, "refund_count": 1}
    assert (result["reported_clients"], result["clients_without_report_access"]) == (2, 2)
    assert (result["agency_name"], result["agency_role"], result["period"]) == ("Dash Agency", "admin", "last 7 days")


def test_date_filter_applies_payments_and_refunds_on_their_own_dates(client, dash):
    today = datetime.now(IST).date().isoformat()
    result = dashboard(client, dash, "admin", "today")
    assert (result["start_date"], result["end_date"]) == (today, today)
    seen = {c["business_id"]: c for c in result["clients"]}
    assert seen[dash["clients"]["m1"]["business_id"]]["sales"]["net_paise"] == 0
    assert seen[dash["clients"]["m2"]["business_id"]]["sales"] == {
        "payments_paise": 0, "refunds_paise": M2_PAISE, "net_paise": -M2_PAISE, "payment_count": 0, "refund_count": 1}
    assert result["combined"]["net_paise"] == -M2_PAISE
    # The default range is the last 7 days, matching Analytics.
    assert dashboard(client, dash, "admin")["combined"]["net_paise"] == M1_PAISE
    assert dashboard(client, dash, "admin", "last month", 200)["period"] == "last month"
    dashboard(client, dash, "admin", "all time", 422)


def test_assigned_staff_see_only_assigned_clients(client, dash):
    result = dashboard(client, dash, "manager_staff", "last 7 days")
    assert [c["business_id"] for c in result["clients"]] == [dash["clients"]["m1"]["business_id"]]
    assert result["combined"]["net_paise"] == M1_PAISE
    assert result["agency_role"] == "staff"


def test_unassigned_staff_see_no_clients_or_sales(client, dash):
    result = dashboard(client, dash, "unassigned_staff", "last 7 days")
    assert result["clients"] == []
    assert result["combined"] == {"payments_paise": 0, "refunds_paise": 0, "net_paise": 0, "payment_count": 0, "refund_count": 0}
    assert (result["reported_clients"], result["clients_without_report_access"]) == (0, 0)


def test_website_editor_counts_only_assigned_sites_without_sales(client, dash):
    result = dashboard(client, dash, "editor_staff", "last 7 days")
    assert [(c["business_id"], c["role"], c["website_count"], c["report_access"], c["sales"]) for c in result["clients"]] == [
        (dash["clients"]["e"]["business_id"], "website_editor", 1, False, None)]
    assert result["combined"]["net_paise"] == 0
    # The same count is what the editor sees in Website Builder.
    sites = ok(client.get("/api/storefront/sites", headers=headers(
        dash["users"]["editor_staff"]["token"], dash["clients"]["e"]["business_id"])))
    assert [site["id"] for site in sites] == [dash["clients"]["e"]["site"]["id"]]


def test_non_members_cannot_load_agency_dashboard(client, dash):
    dashboard(client, dash, "outsider", status=404)
    dashboard(client, dash, "m1_owner", status=404)  # Clients do not see the agency's dashboard.
    assert client.get(f"/api/agencies/{dash['agency']['id']}/dashboard").status_code == 401


def test_unassignment_takes_effect_on_next_request(client, dash):
    assert dashboard(client, dash, "manager_staff")["clients"]
    members = ok(client.get(f"/api/agencies/{dash['agency']['id']}/members", headers=headers(dash["users"]["admin"]["token"])))
    staff_id = next(m["id"] for m in members if m["email"] == "manager_staff@dashboard-test.example")
    ok(client.delete(f"/api/agencies/{dash['agency']['id']}/clients/{dash['clients']['m1']['business_id']}/assignments/{staff_id}",
                     headers=headers(dash["users"]["admin"]["token"])), 204)
    result = dashboard(client, dash, "manager_staff", "last 7 days")
    assert result["clients"] == [] and result["combined"]["net_paise"] == 0


def test_revocation_removes_client_and_its_sales_on_next_request(client, dash):
    before = dashboard(client, dash, "admin", "last 7 days")
    assert before["combined"]["net_paise"] == M1_PAISE
    ok(client.delete(f"/api/workspaces/agencies/{dash['agency']['id']}", headers=dash["owner"]("m1")), 204)
    after = dashboard(client, dash, "admin", "last 7 days")  # Same session token as before.
    assert dash["clients"]["m1"]["business_id"] not in [c["business_id"] for c in after["clients"]]
    assert after["combined"] == {"payments_paise": M2_PAISE, "refunds_paise": M2_PAISE, "net_paise": 0,
                                 "payment_count": 1, "refund_count": 1}
    assert (after["reported_clients"], after["clients_without_report_access"]) == (1, 2)
