"""Seed a judge demo account with fictional data on a running Vyapari backend.

Run it on the backend host, next to its database, while the API is running:

    VYAPARI_DEMO_PASSWORD=... python -m demo_seed --api http://127.0.0.1:8000

Judges sign in without waiting for an email code, so the demo accounts are created
directly in the database as verified accounts. Client owners get random passwords
that are never shown. Everything else (agency, access grants, products, suppliers,
purchase orders, customers, orders, storefronts, and enquiries) is created through
the running API, so it follows the same validation, stock rules, and permissions
as real use. The script refuses to run if the judge account already exists. It
never prints the password.
"""
import argparse
import json
import os
import secrets
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from auth import create_session, normalize_email, password_hash
from database import DATABASE_PATH, get_db


JUDGE_EMAIL = "judge@vyapari-demo.example"
CLIENTS = (
    {
        "name": "Asha Textiles", "owner": "asha.owner@vyapari-demo.example",
        "products": [("Handloom Cotton Saree", "Sarees", 1500, 40, 10), ("Kanchipuram Silk Saree", "Sarees", 8500, 6, 8),
                     ("Block Print Dupatta", "Accessories", 650, 25, 5), ("Ikat Table Runner", "Home", 900, 3, 5)],
        "customers": [("Lakshmi Narayanan", "+91 98450 11223"), ("Fatima Sheikh", "+91 99001 22334"),
                      ("Kiran Reddy", "+91 90080 33445")],
        "supplier": ("Pochampally Weavers Cooperative", "+91 94400 55667"),
        "sites": [("Main storefront", "Handwoven sarees from Pochampally and Kanchipuram"),
                  ("Festival collection", "Festive silks for Diwali and weddings")],
    },
    {
        "name": "Ravi Home Goods", "owner": "ravi.owner@vyapari-demo.example",
        "products": [("Ceramic Serving Bowl", "Kitchen", 600, 50, 10), ("Brass Diya Set", "Pooja", 1200, 4, 6),
                     ("Steel Tiffin Carrier", "Kitchen", 850, 30, 8), ("Cotton Bedsheet", "Bedding", 1100, 18, 5)],
        "customers": [("Suresh Kumar", "+91 98860 44556"), ("Anjali Gupta", "+91 97400 55667"),
                      ("Mohammed Irfan", "+91 96320 66778")],
        "supplier": ("Moradabad Brass Works", "+91 91234 77889"),
        "sites": [("Main storefront", "Everyday homeware delivered across Hyderabad")],
    },
)


def create_verified_account(db, email, password, business_name):
    email = normalize_email(email)
    if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
        raise SystemExit(f"{email} already exists. Seed a fresh demo database instead.")
    salt = secrets.token_bytes(16)
    business_id = db.execute("INSERT INTO businesses (name) VALUES (?)", (business_name,)).lastrowid
    user_id = db.execute("""
        INSERT INTO users (email, password_hash, salt, business_id, email_verified_at) VALUES (?, ?, ?, ?, ?)
    """, (email, password_hash(password, salt), salt, business_id, int(time.time()))).lastrowid
    db.execute("INSERT INTO business_memberships (business_id, user_id, role) VALUES (?, ?, 'owner')",
               (business_id, user_id))
    return {"token": create_session(db, user_id), "business_id": business_id, "email": email}


def main():
    parser = argparse.ArgumentParser(description="Seed a judge demo account with fictional data.")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Origin of the running backend")
    parser.add_argument("--judge-email", default=JUDGE_EMAIL)
    args = parser.parse_args()
    origin = args.api.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
        parser.error("Use HTTPS for a remote backend")
    password = os.environ.get("VYAPARI_DEMO_PASSWORD", "")
    if len(password) < 16:
        parser.error("Set VYAPARI_DEMO_PASSWORD to a unique password of at least 16 characters")

    def api(path, method="GET", body=None, account=None, business_id=None):
        headers = {"Content-Type": "application/json"}
        if account:
            headers["Authorization"] = f"Bearer {account['token']}"
            headers["X-Business-Id"] = str(business_id or account["business_id"])
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urlopen(Request(origin + path, data=data, headers=headers, method=method), timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as error:
            raise SystemExit(f"{method} {path} returned HTTP {error.code}: {error.read()[:200]!r}") from None

    api("/health")  # Fail early if the API is not running.
    print(f"Seeding database: {DATABASE_PATH}")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        judge = create_verified_account(db, args.judge_email, password, "Vyapari Demo Studio")
        owners = [create_verified_account(db, client["owner"], secrets.token_urlsafe(24), client["name"])
                  for client in CLIENTS]

    for name, price, stock in (("Sample Gift Hamper", 999, 12), ("Festive Greeting Cards", 150, 80)):
        api("/api/products", "POST", {"name": name, "category": "Samples", "price": price, "stock": stock}, judge)
    agency = api("/api/agencies", "POST", {"name": "Vyapari Demo Agency"}, judge)

    storefronts = []
    for client, owner in zip(CLIENTS, owners):
        api("/api/workspaces/agencies", "POST", {"access_code": agency["access_code"], "role": "manager"}, owner)
        products = [api("/api/products", "POST", {
            "name": name, "category": category, "price": price, "stock": stock,
            "low_stock_threshold": threshold, "restock_target": threshold * 4,
        }, owner) for name, category, price, stock, threshold in client["products"]]
        customers = [api("/api/customers", "POST", {
            "name": name, "phone": phone, "email": f"{name.split()[0].lower()}@customer-demo.example",
        }, owner) for name, phone in client["customers"]]
        supplier = api("/api/purchasing/suppliers", "POST", {
            "name": client["supplier"][0], "phone": client["supplier"][1]}, owner)
        api("/api/purchasing/orders", "POST", {
            "request_id": str(uuid4()), "supplier_id": supplier["id"],
            "items": [{"product_id": products[-1]["id"], "quantity": 12}],
        }, owner)

        def order(customer, items, status="Paid"):
            return api("/api/orders", "POST", {
                "request_id": str(uuid4()), "customer_id": customer["id"], "status": status,
                "items": [{"product_id": product["id"], "quantity": quantity} for product, quantity in items],
            }, owner)

        order(customers[0], [(products[0], 2), (products[2], 1)])
        order(customers[1], [(products[1], 1)])
        refunded = order(customers[2], [(products[0], 1)])
        api(f"/api/orders/{refunded['id']}/refund", "PUT", {"restock": True}, owner)
        order(customers[0], [(products[2], 2)], status="Pending")

        for index, (label, headline) in enumerate(client["sites"]):
            site = api("/api/storefront/sites", "POST", {"label": label}, owner)
            api(f"/api/storefront?site_id={site['id']}", "PUT", {
                "name": client["name"], "headline": headline, "accent_color": "#7158db",
                "accept_inquiries": True,
                "product_ids": [p["id"] for p in (products if index == 0 else products[:2])],
            }, owner)
            published = api(f"/api/storefront/publication?site_id={site['id']}", "PUT", account=owner)
            storefronts.append((client["name"], label, published["slug"]))
            api(f"/api/storefront/public/{published['slug']}/inquiries", "POST", {
                "request_id": str(uuid4()), "name": "Meena Joshi", "phone": "+91 98765 43210",
                "message": f"Is the {products[0]['name']} available for delivery this week?",
            })

    print("Demo data created with fictional businesses and contacts.")
    print(f"Judge sign-in email: {judge['email']} (password: the VYAPARI_DEMO_PASSWORD you set)")
    print(f"Agency: {agency['name']} with clients {', '.join(client['name'] for client in CLIENTS)}")
    for business, label, slug in storefronts:
        print(f"Storefront: {business} / {label}: /store/{slug}")


if __name__ == "__main__":
    sys.exit(main())
