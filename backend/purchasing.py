from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth import ManagerAccount, normalize_email
from database import get_db
from inventory import MAX_STOCK, get_inventory_product, record_movement

router = APIRouter(prefix="/api/purchasing", tags=["Purchasing"])


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)


class PurchaseItem(BaseModel):
    product_id: int = Field(gt=0, le=MAX_STOCK)
    quantity: int = Field(gt=0, le=2**53 - 1, strict=True)


class PurchaseCreate(BaseModel):
    request_id: UUID
    supplier_id: int = Field(gt=0, le=MAX_STOCK)
    items: list[PurchaseItem] = Field(min_length=1, max_length=50)


class PurchaseDecision(BaseModel):
    status: Literal["received", "cancelled"]


def initialize_purchasing():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                name TEXT NOT NULL COLLATE NOCASE,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                UNIQUE(business_id, name)
            );
            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
                supplier_name TEXT NOT NULL,
                request_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ordered' CHECK(status IN ('ordered', 'received', 'cancelled')),
                created_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(business_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS purchase_items (
                purchase_id INTEGER NOT NULL REFERENCES purchase_orders(id),
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                PRIMARY KEY(purchase_id, product_id)
            );
            CREATE INDEX IF NOT EXISTS purchase_items_product ON purchase_items(product_id, purchase_id);
        """)


def supplier_values(body):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a supplier name")
    return name, normalize_email(body.email) if body.email.strip() else "", body.phone.strip()


@router.get("/suppliers")
def list_suppliers(account: ManagerAccount):
    with get_db() as db:
        rows = db.execute("""
            SELECT id, name, email, phone FROM suppliers WHERE business_id = ? ORDER BY name, id
        """, (account.business_id,)).fetchall()
    return [dict(row) for row in rows]


@router.post("/suppliers", status_code=201)
def create_supplier(body: SupplierCreate, account: ManagerAccount):
    with get_db() as db:
        row = db.execute("""
            INSERT INTO suppliers (business_id, name, email, phone)
            VALUES (?, ?, ?, ?) ON CONFLICT (business_id, name) DO NOTHING
            RETURNING id, name, email, phone
        """, (account.business_id, *supplier_values(body))).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="A supplier already uses that name")
    return dict(row)


@router.put("/suppliers/{supplier_id}")
def update_supplier(supplier_id: int, body: SupplierCreate, account: ManagerAccount):
    if not 1 <= supplier_id <= MAX_STOCK:
        raise HTTPException(status_code=404, detail="Supplier not found")
    values = supplier_values(body)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("""
            SELECT 1 FROM suppliers WHERE business_id = ? AND name = ? AND id != ?
        """, (account.business_id, values[0], supplier_id)).fetchone():
            raise HTTPException(status_code=409, detail="A supplier already uses that name")
        row = db.execute("""
            UPDATE suppliers SET name = ?, email = ?, phone = ?
            WHERE business_id = ? AND id = ? RETURNING id, name, email, phone
        """, (*values, account.business_id, supplier_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Supplier not found")
    return dict(row)


PURCHASE_COLUMNS = "id, supplier_id, supplier_name, status, created_at, completed_at"


def purchase_details(db, row):
    return {
        **dict(row),
        "items": [dict(item) for item in db.execute("""
            SELECT product_id, product_name, quantity FROM purchase_items
            WHERE purchase_id = ? ORDER BY product_id
        """, (row["id"],))],
    }


@router.get("/orders")
def list_purchases(account: ManagerAccount):
    with get_db() as db:
        rows = db.execute(
            f"SELECT {PURCHASE_COLUMNS} FROM purchase_orders WHERE business_id = ? ORDER BY id DESC",
            (account.business_id,),
        ).fetchall()
        return [purchase_details(db, row) for row in rows]


@router.post("/orders", status_code=201)
def create_purchase(body: PurchaseCreate, account: ManagerAccount):
    if len({item.product_id for item in body.items}) != len(body.items):
        raise HTTPException(status_code=422, detail="Choose each product once")
    request_id = str(body.request_id)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            f"SELECT {PURCHASE_COLUMNS} FROM purchase_orders WHERE business_id = ? AND request_id = ?",
            (account.business_id, request_id),
        ).fetchone()
        if previous:
            return purchase_details(db, previous)
        supplier = db.execute("""
            SELECT name FROM suppliers WHERE business_id = ? AND id = ?
        """, (account.business_id, body.supplier_id)).fetchone()
        if supplier is None:
            raise HTTPException(status_code=404, detail="Supplier not found")
        items = []
        for item in body.items:
            product = get_inventory_product(db, account.business_id, item.product_id)
            items.append((item.product_id, product["name"], item.quantity))
        row = db.execute(f"""
            INSERT INTO purchase_orders (business_id, supplier_id, supplier_name, request_id, created_at)
            VALUES (?, ?, ?, ?, ?) RETURNING {PURCHASE_COLUMNS}
        """, (account.business_id, body.supplier_id, supplier["name"], request_id,
              datetime.now(timezone.utc).isoformat())).fetchone()
        db.executemany("""
            INSERT INTO purchase_items (purchase_id, product_id, product_name, quantity)
            VALUES (?, ?, ?, ?)
        """, [(row["id"], *item) for item in items])
        return purchase_details(db, row)


@router.put("/orders/{purchase_id}/status")
def complete_purchase(purchase_id: int, body: PurchaseDecision, account: ManagerAccount):
    if not 1 <= purchase_id <= MAX_STOCK:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT {PURCHASE_COLUMNS} FROM purchase_orders WHERE business_id = ? AND id = ?",
            (account.business_id, purchase_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Purchase order not found")
        purchase = purchase_details(db, row)
        if purchase["status"] == body.status:
            return purchase
        if purchase["status"] != "ordered":
            raise HTTPException(status_code=409, detail="This purchase order is already closed")
        if body.status == "received":
            for item in purchase["items"]:
                stock = db.execute("""
                    UPDATE products SET stock = stock + ?
                    WHERE id = ? AND business_id = ? AND stock <= ? RETURNING stock
                """, (item["quantity"], item["product_id"], account.business_id, MAX_STOCK - item["quantity"])).fetchone()
                if stock is None:
                    raise HTTPException(status_code=409, detail=f"Cannot receive {item['product_name']}: product missing or stock limit exceeded")
                record_movement(db, account, item["product_id"], item["quantity"], stock["stock"],
                                "Purchase received", reason=f"#PO-{purchase_id}")
        completed_at = datetime.now(timezone.utc).isoformat()
        db.execute("""
            UPDATE purchase_orders SET status = ?, completed_at = ? WHERE business_id = ? AND id = ?
        """, (body.status, completed_at, account.business_id, purchase_id))
        return {**purchase, "status": body.status, "completed_at": completed_at}
