from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field, StringConstraints

from auth import ManagerAccount
from database import get_db


router = APIRouter(prefix="/api/inventory", tags=["Inventory"])
MAX_STOCK = 2**63 - 1
PAGE_SIZE = 50
ProductId = Annotated[int, Path(gt=0, le=MAX_STOCK)]
PRODUCT_COLUMNS = "id, name, category, price, stock, low_stock_threshold, restock_target"


class StockAdjustment(BaseModel):
    request_id: UUID
    delta: int = Field(ge=-MAX_STOCK, le=MAX_STOCK, strict=True)
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class StockMovement(BaseModel):
    id: int
    delta: int
    stock_after: int
    action: str
    reason: str
    order_id: int | None
    actor: str
    created_at: str


class StockHistory(BaseModel):
    movements: list[StockMovement]
    older_before: int | None


def initialize_inventory():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS inventory_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                product_id INTEGER NOT NULL,
                delta INTEGER NOT NULL CHECK(delta != 0),
                stock_after INTEGER NOT NULL CHECK(stock_after >= 0),
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                order_id INTEGER,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL,
                request_id TEXT,
                UNIQUE (business_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS inventory_movements_product
            ON inventory_movements (business_id, product_id, id);
        """)


def record_movement(db, account, product_id, delta, stock_after, action, *, reason="", order_id=None, request_id=None):
    if delta:
        db.execute("""
            INSERT INTO inventory_movements
                (business_id, product_id, delta, stock_after, action, reason, order_id, actor, created_at, request_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (account.business_id, product_id, delta, stock_after, action, reason,
              order_id, account.email, datetime.now(timezone.utc).isoformat(), request_id))


def get_inventory_product(db, business_id, product_id):
    row = db.execute(
        f"SELECT {PRODUCT_COLUMNS} FROM products WHERE business_id = ? AND id = ?",
        (business_id, product_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return row


@router.get("/{product_id}/movements", response_model=StockHistory)
def stock_history(
    product_id: ProductId, account: ManagerAccount,
    before: Annotated[int | None, Query(gt=0, le=MAX_STOCK)] = None,
):
    with get_db() as db:
        get_inventory_product(db, account.business_id, product_id)
        rows = db.execute("""
            SELECT id, delta, stock_after, action, reason, order_id, actor, created_at
            FROM inventory_movements WHERE business_id = ? AND product_id = ? AND (? IS NULL OR id < ?)
            ORDER BY id DESC LIMIT ?
        """, (account.business_id, product_id, before, before, PAGE_SIZE + 1)).fetchall()
    return {
        "movements": [dict(row) for row in rows[:PAGE_SIZE]],
        "older_before": rows[PAGE_SIZE - 1]["id"] if len(rows) > PAGE_SIZE else None,
    }


@router.post("/{product_id}/adjust")
def adjust_stock(product_id: ProductId, body: StockAdjustment, account: ManagerAccount):
    if body.delta == 0:
        raise HTTPException(status_code=422, detail="Enter a stock change other than zero")
    request_id = str(body.request_id)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        product = get_inventory_product(db, account.business_id, product_id)
        prior = db.execute("""
            SELECT product_id, delta, reason FROM inventory_movements WHERE business_id = ? AND request_id = ?
        """, (account.business_id, request_id)).fetchone()
        if prior is not None:
            if tuple(prior) != (product_id, body.delta, body.reason):
                raise HTTPException(status_code=409, detail="This request ID already belongs to a different adjustment")
            return dict(product)
        result = product["stock"] + body.delta
        if not 0 <= result <= MAX_STOCK:
            raise HTTPException(status_code=409, detail="This adjustment would put stock outside its allowed range")
        updated = db.execute(f"""
            UPDATE products SET stock = ? WHERE business_id = ? AND id = ?
            RETURNING {PRODUCT_COLUMNS}
        """, (result, account.business_id, product_id)).fetchone()
        record_movement(db, account, product_id, body.delta, result, "Stock adjustment",
                        reason=body.reason, request_id=request_id)
    return dict(updated)
