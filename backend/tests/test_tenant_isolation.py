"""Cross-business isolation tests.

Each attack is sent from a legitimate session with a valid workspace, but targets
another business's records. Requests must be refused without changing any data,
and responses must not contain the other business's private values."""
import sqlite3
import uuid
from contextlib import closing

import pytest

from conftest import BRAVO_MARK, BRAVO_STOCK, headers, ok
from migration_check import table_checksum

REFUSED = {403, 404, 409, 422}


def database_fingerprint(client):
    with closing(sqlite3.connect(f"file:{client.database_path}?mode=ro", uri=True)) as db:
        tables = [row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        return {table: table_checksum(db, table) for table in tables}


def foreign_record_requests(b):
    """Requests that reference Bravo's records by ID from inside another workspace."""
    product, customer, order = b["product"]["id"], b["customer"]["id"], b["order"]["id"]
    pending, site, inquiry = b["pending"]["id"], b["site"]["id"], b["inquiry"]["id"]
    product_body = {"name": "Hijacked", "price": 1, "stock": 1}
    design = {"name": "x", "headline": "x", "accent_color": "#000000"}
    return [
        ("PUT", f"/api/products/{product}", product_body),
        ("DELETE", f"/api/products/{product}", None),
        ("GET", f"/api/inventory/{product}/movements", None),
        ("POST", f"/api/inventory/{product}/adjust", {"request_id": str(uuid.uuid4()), "delta": -1, "reason": "x"}),
        ("PUT", f"/api/customers/{customer}", {"name": "Hijacked"}),
        ("DELETE", f"/api/customers/{customer}", None),
        ("PUT", f"/api/orders/{pending}/paid", None),
        ("PUT", f"/api/orders/{pending}/cancel", None),
        ("PUT", f"/api/orders/{order}/refund", {"restock": True}),
        # Own-workspace order that points at another business's customer, product, or enquiry.
        ("POST", "/api/orders", {"request_id": str(uuid.uuid4()), "customer_id": customer,
                                 "items": [{"product_id": product, "quantity": 1}]}),
        ("POST", "/api/orders", {"request_id": str(uuid.uuid4()), "customer_id": "OWN_CUSTOMER",
                                 "items": [{"product_id": product, "quantity": 1}]}),
        ("POST", "/api/orders", {"request_id": str(uuid.uuid4()), "customer_id": "OWN_CUSTOMER",
                                 "items": [{"product_id": "OWN_PRODUCT", "quantity": 1}],
                                 "source_inquiry_id": inquiry}),
        ("PUT", f"/api/purchasing/suppliers/{b['supplier']['id']}", {"name": "Hijacked"}),
        ("POST", "/api/purchasing/orders", {"request_id": str(uuid.uuid4()), "supplier_id": b["supplier"]["id"],
                                            "items": [{"product_id": "OWN_PRODUCT", "quantity": 1}]}),
        ("POST", "/api/purchasing/orders", {"request_id": str(uuid.uuid4()), "supplier_id": "OWN_SUPPLIER",
                                            "items": [{"product_id": product, "quantity": 1}]}),
        ("PUT", f"/api/purchasing/orders/{b['purchase']['id']}/status", {"status": "received"}),
        ("GET", f"/api/storefront?site_id={site}", None),
        ("PUT", f"/api/storefront?site_id={site}", design),
        ("PUT", "/api/storefront?site_id=OWN_SITE", {**design, "product_ids": [product]}),
        ("GET", f"/api/storefront/publication?site_id={site}", None),
        ("PUT", f"/api/storefront/publication?site_id={site}", None),
        ("DELETE", f"/api/storefront/publication?site_id={site}", None),
        ("PATCH", f"/api/storefront/sites/{site}", {"label": "Hijacked"}),
        ("POST", f"/api/storefront/sites/{site}/duplicate", {"label": "Stolen copy"}),
        ("PUT", f"/api/storefront/sites/{site}/archive", {"archived": True}),
        ("GET", f"/api/reports/sales?website_id={site}", None),
        ("PUT", f"/api/storefront/inquiries/{inquiry}/status", {"status": "resolved"}),
        ("PUT", f"/api/storefront/inquiries/{inquiry}/notes", {"notes": "Hijacked"}),
        ("PUT", f"/api/storefront/inquiries/{inquiry}/customer", {"customer_id": None}),
        ("PUT", "/api/storefront/inquiries/OWN_INQUIRY/customer", {"customer_id": customer}),
        ("POST", f"/api/storefront/inquiries/{inquiry}/customer", None),
        ("DELETE", f"/api/workspaces/invitations/{b['invitation']['id']}", None),
    ]


def resolve(value, own):
    """Fill OWN_* placeholders with the attacker's own record IDs."""
    if isinstance(value, str):
        for key, replacement in own.items():
            value = value.replace(key, str(replacement))
        return int(value) if value.isdigit() else value
    if isinstance(value, list):
        return [resolve(item, own) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, own) for key, item in value.items()}
    return value


def own_ids(a):
    return {"OWN_CUSTOMER": a["customer"]["id"], "OWN_PRODUCT": a["product"]["id"],
            "OWN_SUPPLIER": a["supplier"]["id"], "OWN_SITE": a["site"]["id"], "OWN_INQUIRY": a["inquiry"]["id"]}


@pytest.mark.parametrize("attacker", ["alpha", "agent"])
def test_foreign_ids_are_refused_without_changes(client, world, attacker):
    """Alpha's owner, and an agency manager of both businesses working in Alpha,
    cannot read or change Bravo's records by ID."""
    token = world[attacker]["token"]
    a = world["a"]
    before = database_fingerprint(client)
    failures = []
    for method, path, body in foreign_record_requests(world["b"]):
        path, body = resolve(path, own_ids(a)), resolve(body, own_ids(a))
        response = client.request(method, path, headers=headers(token, a["business_id"]), json=body)
        if response.status_code not in REFUSED or BRAVO_MARK in response.text:
            failures.append((method, path, response.status_code, response.text[:200]))
    assert not failures
    assert database_fingerprint(client) == before


BUSINESS_READS = [
    "/api/products", "/api/customers", "/api/orders", "/api/purchasing/suppliers", "/api/purchasing/orders",
    "/api/storefront/catalog", "/api/storefront/sites?include_archived=true", "/api/storefront/inquiries",
    "/api/storefront/requests", "/api/reports/sales?period=this%20month", "/api/assistant/history",
    "/api/workspaces/members", "/api/workspaces/activity", "/api/workspaces/invitations",
]


OWNER_ONLY_READS = {"/api/workspaces/members", "/api/workspaces/activity", "/api/workspaces/invitations"}


@pytest.mark.parametrize("path", BUSINESS_READS)
def test_non_member_cannot_select_other_business(client, world, path):
    response = client.get(path, headers=headers(world["alpha"]["token"], world["b"]["business_id"]))
    assert response.status_code == 403
    assert BRAVO_MARK not in response.text


@pytest.mark.parametrize("path", BUSINESS_READS)
@pytest.mark.parametrize("attacker", ["alpha", "agent"])
def test_own_workspace_lists_exclude_other_business(client, world, attacker, path):
    response = client.get(path, headers=headers(world[attacker]["token"], world["a"]["business_id"]))
    # The agency account is a manager, so owner-only team pages are refused outright.
    expected = 403 if attacker == "agent" and path in OWNER_ONLY_READS else 200
    assert response.status_code == expected, response.text
    assert BRAVO_MARK not in response.text


def test_agency_positive_control_can_read_each_client_in_its_own_workspace(client, world):
    """Guards against the tests above passing only because the endpoints are broken."""
    b = world["b"]
    h = headers(world["agent"]["token"], b["business_id"])
    assert BRAVO_MARK in client.get("/api/products", headers=h).text
    assert BRAVO_MARK in client.get("/api/storefront/inquiries", headers=h).text
    ok(client.get(f"/api/inventory/{b['product']['id']}/movements", headers=h))
    ok(client.get(f"/api/reports/sales?website_id={b['site']['id']}", headers=h))
    assert ok(client.get(f"/api/storefront?site_id={b['site']['id']}", headers=h))["name"] == f"{BRAVO_MARK} Store"


def test_sales_report_totals_do_not_include_other_business(client, world):
    a, b = world["a"], world["b"]
    alpha = ok(client.get("/api/reports/sales?period=this%20month",
                          headers=headers(world["alpha"]["token"], a["business_id"])))
    bravo = ok(client.get("/api/reports/sales?period=this%20month",
                          headers=headers(world["bravo"]["token"], b["business_id"])))
    assert alpha["payments_paise"] == a["order"]["amount_paise"]
    assert bravo["payments_paise"] == b["order"]["amount_paise"]
    assert alpha["enquiries"]["received"] == bravo["enquiries"]["received"] == 1


@pytest.mark.parametrize("question", [
    f"Stock for {BRAVO_MARK} Saree", "ORDER_LOOKUP", "Inventory summary", "Low stock",
    "Recent orders", "Customer count", "Sales summary",
    f"{BRAVO_MARK} Saree का स्टॉक", f"{BRAVO_MARK} Saree స్టాక్ ఎంత",
])
def test_assistant_answers_only_from_current_business(client, world, question):
    question = question.replace("ORDER_LOOKUP", f"Order #ORD-{world['b']['order']['id']}")
    reply = ok(client.post("/api/assistant/ask", headers=headers(world["agent"]["token"], world["a"]["business_id"]),
                           json={"question": question, "request_id": str(uuid.uuid4())}))
    answer = reply["answer"].replace(f"{BRAVO_MARK} Saree", "")  # The question text may be echoed.
    assert BRAVO_MARK not in answer
    assert str(BRAVO_STOCK) not in answer and f"{BRAVO_STOCK:,}" not in answer
    assert "8,642" not in answer  # Bravo's paid order total.


def test_public_storefront_shows_only_its_own_business(client, world):
    a, b = world["a"], world["b"]
    alpha_site = client.get(f"/api/storefront/public/{a['slug']}").text
    bravo_site = client.get(f"/api/storefront/public/{b['slug']}").text
    assert BRAVO_MARK not in alpha_site and "ALPHA" not in bravo_site
    assert BRAVO_MARK in bravo_site


def test_public_enquiry_is_delivered_only_to_site_owner(client, world):
    a, b = world["a"], world["b"]
    ok(client.post(f"/api/storefront/public/{b['slug']}/inquiries", json={
        "request_id": str(uuid.uuid4()), "name": "Routing check", "phone": "+91 90000 11111", "message": "Routing check message",
    }), 204)
    assert "Routing check" in client.get(
        "/api/storefront/inquiries", headers=headers(world["bravo"]["token"], b["business_id"])).text
    assert "Routing check" not in client.get(
        "/api/storefront/inquiries", headers=headers(world["alpha"]["token"], a["business_id"])).text


def test_website_editor_is_limited_to_assigned_website(client, world):
    b = world["b"]
    h = headers(world["editor"]["token"], b["business_id"])
    ok(client.get(f"/api/storefront?site_id={b['site']['id']}", headers=h))
    assert client.get(f"/api/storefront?site_id={b['second_site']['id']}", headers=h).status_code in REFUSED
    assert client.get(f"/api/storefront?site_id={world['a']['site']['id']}", headers=h).status_code in REFUSED
    for path in ("/api/customers", "/api/orders", "/api/reports/sales", "/api/storefront/inquiries",
                 f"/api/inventory/{b['product']['id']}/movements"):
        assert client.get(path, headers=h).status_code == 403, path


def test_sales_staff_cannot_use_manager_endpoints(client, world):
    b = world["b"]
    h = headers(world["sales"]["token"], b["business_id"])
    ok(client.get("/api/customers", headers=h))
    for method, path in (("GET", "/api/reports/sales"), ("GET", "/api/workspaces/members"),
                         ("GET", "/api/workspaces/activity"), ("DELETE", f"/api/customers/{b['customer']['id']}"),
                         ("PUT", f"/api/orders/{b['order']['id']}/refund")):
        response = client.request(method, path, headers=h, json={"restock": False} if "refund" in path else None)
        assert response.status_code == 403, (method, path, response.status_code)


def test_platform_admin_directory_does_not_grant_business_records(client, world):
    alpha = world["alpha"]
    with closing(sqlite3.connect(client.database_path)) as db, db:
        db.execute("INSERT INTO platform_admins (user_id) SELECT id FROM users WHERE email = ?",
                   ("alpha-owner@example.test",))
    try:
        ok(client.get("/api/platform/businesses", headers=headers(alpha["token"])))
        for path in BUSINESS_READS:
            assert client.get(path, headers=headers(alpha["token"], world["b"]["business_id"])).status_code == 403
    finally:
        with closing(sqlite3.connect(client.database_path)) as db, db:
            db.execute("DELETE FROM platform_admins")


def test_platform_endpoints_require_platform_admin(client, world):
    h = headers(world["bravo"]["token"], world["b"]["business_id"])
    assert client.get("/api/platform/businesses", headers=h).status_code == 403
    assert client.get("/api/platform/website-requests", headers=h).status_code == 403


def test_missing_invalid_or_logged_out_sessions_are_rejected(client, world):
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/products", headers=headers("not-a-real-token")).status_code == 401
    assert client.get("/api/products", headers=headers(world["alpha"]["token"], 999999)).status_code == 403
    session = ok(client.post("/api/auth/login", json={"email": "bravo-sales@example.test",
                                                      "password": "correct-horse-battery"}))
    assert client.get("/api/customers", headers=headers(session["token"], world["b"]["business_id"])).status_code == 200
    client.post("/api/auth/logout", headers=headers(session["token"]))
    assert client.get("/api/customers", headers=headers(session["token"], world["b"]["business_id"])).status_code == 401


def test_revoked_agency_access_takes_effect_immediately(client, world):
    """Runs last in this module: removes the agency's Bravo membership."""
    b = world["b"]
    agent_h = headers(world["agent"]["token"], b["business_id"])
    ok(client.get("/api/products", headers=agent_h))
    members = ok(client.get("/api/workspaces/members", headers=headers(world["bravo"]["token"], b["business_id"])))
    agent_id = next(m["id"] for m in members if m["email"] == "agency@example.test")
    ok(client.delete(f"/api/workspaces/members/{agent_id}",
                     headers=headers(world["bravo"]["token"], b["business_id"])), 204)
    assert client.get("/api/products", headers=agent_h).status_code == 403
    assert all(w["id"] != b["business_id"] for w in ok(client.get("/api/workspaces", headers=agent_h)))
