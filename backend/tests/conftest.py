import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
# `database` reads this path on first import, which can happen while test modules
# are collected. Set it before anything imports backend modules so tests never
# touch backend/vyapari.db.
TEST_DIRECTORY = tempfile.TemporaryDirectory(prefix="vyapari-isolation-", ignore_cleanup_errors=True)
TEST_DATABASE = Path(TEST_DIRECTORY.name) / "isolation.db"
os.environ["VYAPARI_DATABASE_PATH"] = str(TEST_DATABASE)
# Tests deliver codes through the in-memory fake provider. Never real email.
os.environ["VYAPARI_EMAIL_PROVIDER"] = "fake"
os.environ["VYAPARI_SECRET_KEY"] = "test-only-secret-key-not-for-production-use"
os.environ.pop("VYAPARI_ENV", None)

PASSWORD = "correct-horse-battery"
# Distinctive values that must never appear in another business's responses.
BRAVO_MARK = "BRAVO-PRIVATE"
BRAVO_PRICE = 4321.0
BRAVO_STOCK = 9876


def headers(token, business_id=None):
    result = {"Authorization": f"Bearer {token}"}
    if business_id is not None:
        result["X-Business-Id"] = str(business_id)
    return result


def ok(response, status=200):
    assert response.status_code == status, (response.status_code, response.text)
    return response.json() if response.content else None


@pytest.fixture(scope="session")
def client():
    database = TEST_DATABASE
    from fastapi.testclient import TestClient
    import database as database_module
    assert database_module.DATABASE_PATH == database.resolve()
    from main import app
    import verification
    # Every test request comes from one client address. Per-IP limits are raised
    # here and tested separately in test_authentication.py.
    for name in ("code_ip", "verify_ip", "login_ip"):
        verification.LIMITS[name] = (100_000, verification.LIMITS[name][1])
    with TestClient(app) as test_client:
        test_client.database_path = database
        yield test_client


def latest_code(email):
    """The most recent code emailed to an address through the fake provider."""
    from notifications import FAKE_EMAIL
    for message in reversed(FAKE_EMAIL.messages):
        if message["to"] == email:
            match = re.search(r"Your code is ([0-9]{6})", message["body"])
            if match:
                return match.group(1)
    raise AssertionError(f"No code was emailed to {email}")


def register(client, email, business, password=PASSWORD):
    """Sign up through the verified email flow."""
    ok(client.post("/api/auth/signup/start", json={"email": email}), 202)
    ticket = ok(client.post("/api/auth/signup/verify", json={"email": email, "code": latest_code(email)}))["ticket"]
    return ok(client.post("/api/auth/signup/complete", json={
        "ticket": ticket, "password": password, "business_name": business,
    }), 201)


def build_business(client, token, business_id, mark, price, stock):
    h = headers(token, business_id)
    product = ok(client.post("/api/products", headers=h, json={
        "name": f"{mark} Saree", "category": mark, "price": price, "stock": stock,
    }), 201)
    customer = ok(client.post("/api/customers", headers=h, json={
        "name": f"{mark} Customer", "email": f"{mark.lower()}@example.test", "phone": "+91 90000 00000",
    }), 201)
    order = ok(client.post("/api/orders", headers=h, json={
        "request_id": str(uuid.uuid4()), "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 2}], "status": "Paid",
    }), 201)
    pending = ok(client.post("/api/orders", headers=h, json={
        "request_id": str(uuid.uuid4()), "customer_id": customer["id"],
        "items": [{"product_id": product["id"], "quantity": 1}],
    }), 201)
    supplier = ok(client.post("/api/purchasing/suppliers", headers=h, json={"name": f"{mark} Supplier"}), 201)
    purchase = ok(client.post("/api/purchasing/orders", headers=h, json={
        "request_id": str(uuid.uuid4()), "supplier_id": supplier["id"],
        "items": [{"product_id": product["id"], "quantity": 5}],
    }), 201)
    site = ok(client.post("/api/storefront/sites", headers=h, json={"label": f"{mark} Shop"}), 201)
    second_site = ok(client.post("/api/storefront/sites", headers=h, json={"label": f"{mark} Outlet"}), 201)
    ok(client.put(f"/api/storefront?site_id={site['id']}", headers=h, json={
        "name": f"{mark} Store", "headline": mark, "accent_color": "#123456",
        "accept_inquiries": True, "product_ids": [product["id"]],
    }))
    publication = ok(client.put(f"/api/storefront/publication?site_id={site['id']}", headers=h))
    ok(client.post(f"/api/storefront/public/{publication['slug']}/inquiries", json={
        "request_id": str(uuid.uuid4()), "name": f"{mark} Visitor",
        "email": "visitor@example.test", "message": f"{mark} enquiry",
    }), 204)
    inquiry = ok(client.get("/api/storefront/inquiries", headers=h))[0]
    ok(client.post("/api/assistant/ask", headers=h, json={
        "question": "Sales summary", "request_id": str(uuid.uuid4()),
    }))
    return {
        "business_id": business_id, "product": product, "customer": customer, "order": order,
        "pending": pending, "supplier": supplier, "purchase": purchase, "site": site,
        "second_site": second_site, "slug": publication["slug"], "inquiry": inquiry,
    }


@pytest.fixture(scope="session")
def world(client):
    alpha = register(client, "alpha-owner@example.test", "Alpha Traders")
    bravo = register(client, "bravo-owner@example.test", "Bravo Boutique")
    agent = register(client, "agency@example.test", "Agency Home")
    editor = register(client, "bravo-editor@example.test", "Editor Home")
    sales = register(client, "bravo-sales@example.test", "Sales Home")

    a = build_business(client, alpha["token"], alpha["business_id"], "ALPHA", 100.0, 50)
    b = build_business(client, bravo["token"], bravo["business_id"], BRAVO_MARK, BRAVO_PRICE, BRAVO_STOCK)

    for owner, business in ((alpha, a), (bravo, b)):
        ok(client.post("/api/workspaces/members", headers=headers(owner["token"], business["business_id"]),
                       json={"email": "agency@example.test", "role": "manager"}), 201)
    bh = headers(bravo["token"], b["business_id"])
    ok(client.post("/api/workspaces/members", headers=bh,
                   json={"email": "bravo-editor@example.test", "role": "website_editor"}), 201)
    ok(client.put(f"/api/workspaces/members/{editor_id(client, bravo, b)}/websites", headers=bh,
                  json={"website_ids": [b["site"]["id"]]}))
    ok(client.post("/api/workspaces/members", headers=bh,
                   json={"email": "bravo-sales@example.test", "role": "sales"}), 201)
    b["invitation"] = ok(client.post("/api/workspaces/invitations", headers=bh,
                                     json={"email": "future@example.test", "role": "sales"}), 201)
    return {"alpha": alpha, "bravo": bravo, "agent": agent, "editor": editor, "sales": sales, "a": a, "b": b}


def editor_id(client, owner, business):
    members = ok(client.get("/api/workspaces/members", headers=headers(owner["token"], business["business_id"])))
    return next(m["id"] for m in members if m["email"] == "bravo-editor@example.test")
