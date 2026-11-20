from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from activity import record_activity
from auth import ManagerAccount, OperationsAccount, require_manager
from database import get_db
from inventory import MAX_STOCK, record_movement


router = APIRouter(prefix="/api/orders", tags=["Orders"])


class OrderItem(BaseModel):
    product_id: int = Field(gt=0, le=2**63 - 1)
    quantity: int = Field(gt=0, le=2**53 - 1)


class OrderCreate(BaseModel):
    request_id: UUID
    customer_id: int = Field(gt=0, le=2**63 - 1)
    items: list[OrderItem] = Field(min_length=1, max_length=50)
    status: Literal["Pending", "Paid"] = "Pending"
    source_inquiry_id: int | None = Field(default=None, gt=0, le=2**63 - 1)


class OrderRefund(BaseModel):
    restock: bool = Field(strict=True)


def initialize_orders():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                request_id TEXT NOT NULL,
                customer_id INTEGER NOT NULL,
                customer TEXT NOT NULL,
                date TEXT NOT NULL,
                paid_at TEXT,
                cancelled_at TEXT,
                refunded_at TEXT,
                refund_restocked INTEGER NOT NULL DEFAULT 0 CHECK(refund_restocked IN (0, 1)),
                source_inquiry_id INTEGER,
                source_website_id INTEGER,
                source_website_label TEXT,
                amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
                UNIQUE (business_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS orders_business_id ON orders (business_id, id);
            CREATE TABLE IF NOT EXISTS order_items (
                order_id INTEGER NOT NULL REFERENCES orders(id),
                product_id INTEGER NOT NULL,
                product TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK(quantity > 0),
                unit_price_paise INTEGER NOT NULL CHECK(unit_price_paise >= 0),
                PRIMARY KEY (order_id, product_id)
            );
            CREATE INDEX IF NOT EXISTS order_items_product_id ON order_items (product_id, order_id);
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(orders)")}
        if "cancelled_at" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN cancelled_at TEXT")
        if "refunded_at" not in columns:
            db.execute("ALTER TABLE orders ADD COLUMN refunded_at TEXT")
        if "refund_restocked" not in columns:
            db.execute("""
                ALTER TABLE orders ADD COLUMN refund_restocked INTEGER NOT NULL DEFAULT 0
                CHECK(refund_restocked IN (0, 1))
            """)
        for column, column_type in (
            ("source_inquiry_id", "INTEGER"), ("source_website_id", "INTEGER"), ("source_website_label", "TEXT"),
        ):
            if column not in columns:
                db.execute(f"ALTER TABLE orders ADD COLUMN {column} {column_type}")
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS orders_source_inquiry
            ON orders (business_id, source_inquiry_id) WHERE source_inquiry_id IS NOT NULL
        """)


def serialize_order(db, row):
    order = dict(row)
    order["refund_restocked"] = bool(order["refund_restocked"])
    if order["refunded_at"]:
        order["status"] = "Refunded"
    elif order["cancelled_at"]:
        order["status"] = "Cancelled"
    else:
        order["status"] = "Paid" if order["paid_at"] else "Pending"
    order["items"] = [dict(item) for item in db.execute("""
        SELECT product_id, product, quantity, unit_price_paise
        FROM order_items WHERE order_id = ? ORDER BY product_id
    """, (order["id"],))]
    return order


ORDER_COLUMNS = (
    "id, customer_id, customer, date, paid_at, cancelled_at, "
    "refunded_at, refund_restocked, amount_paise, source_inquiry_id, source_website_id, source_website_label"
)


def restore_stock(db, items, account, order_id, action):
    for item in items:
        quantity = item["quantity"]
        result = db.execute("""
            UPDATE products SET stock = stock + ?
            WHERE id = ? AND business_id = ? AND stock <= ?
            RETURNING stock
        """, (quantity, item["product_id"], account.business_id, MAX_STOCK - quantity)).fetchone()
        if result is None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot restore stock for {item['product']}. The product is missing or its stock limit would be exceeded.",
            )
        record_movement(db, account, item["product_id"], quantity, result["stock"], action, order_id=order_id)


@router.get("")
def list_orders(account: OperationsAccount):
    with get_db() as db:
        rows = db.execute(
            f"SELECT {ORDER_COLUMNS} FROM orders WHERE business_id = ? ORDER BY id DESC",
            (account.business_id,),
        ).fetchall()
        return [serialize_order(db, row) for row in rows]


@router.post("", status_code=201)
def create_order(order: OrderCreate, account: OperationsAccount):
    business_id = account.business_id
    request_id = str(order.request_id)
    if order.source_inquiry_id is not None:
        require_manager(account)
    quantities = {item.product_id: item.quantity for item in order.items}
    if len(quantities) != len(order.items):
        raise HTTPException(status_code=422, detail="Select each product once")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute(
            f"SELECT {ORDER_COLUMNS} FROM orders WHERE business_id = ? AND request_id = ?",
            (business_id, request_id),
        ).fetchone()
        if previous:
            return serialize_order(db, previous)

        source_site_id = source_site_label = None
        if order.source_inquiry_id is not None:
            inquiry = db.execute("""
                SELECT i.customer_id, i.website_id, s.label
                FROM website_inquiries AS i JOIN storefront_websites AS s ON s.id = i.website_id
                WHERE i.id = ? AND i.business_id = ? AND s.business_id = i.business_id
            """, (order.source_inquiry_id, business_id)).fetchone()
            if inquiry is None:
                raise HTTPException(status_code=404, detail="Enquiry not found")
            if inquiry["customer_id"] != order.customer_id:
                raise HTTPException(status_code=409, detail="Use the customer currently linked to this enquiry")
            if db.execute("""
                SELECT 1 FROM orders WHERE business_id = ? AND source_inquiry_id = ?
            """, (business_id, order.source_inquiry_id)).fetchone():
                raise HTTPException(status_code=409, detail="An order already exists for this enquiry")
            source_site_id, source_site_label = inquiry["website_id"], inquiry["label"]

        customer = db.execute(
            "SELECT name FROM customers WHERE id = ? AND business_id = ?",
            (order.customer_id, business_id),
        ).fetchone()
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        items = []
        stock_changes = []
        amount = 0
        for product_id, quantity in quantities.items():
            product = db.execute("""
                SELECT name, price, stock FROM products WHERE id = ? AND business_id = ?
            """, (product_id, business_id)).fetchone()
            if not product:
                raise HTTPException(status_code=404, detail="Product not found")
            if product["stock"] < quantity:
                raise HTTPException(status_code=409, detail=f"Insufficient stock for {product['name']}")
            unit_price = int((Decimal(str(product["price"])) * 100).to_integral_value(rounding=ROUND_HALF_UP))
            amount += unit_price * quantity
            if amount > 2**53 - 1:
                raise HTTPException(status_code=422, detail="Order total is too large")
            items.append((product_id, product["name"], quantity, unit_price))
            stock_changes.append((product_id, -quantity, product["stock"] - quantity))
            db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ? AND business_id = ?",
                (quantity, product_id, business_id),
            )

        now = datetime.now(timezone.utc).isoformat()
        row = db.execute(f"""
            INSERT INTO orders (business_id, request_id, customer_id, customer, date, paid_at, amount_paise,
                                source_inquiry_id, source_website_id, source_website_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING {ORDER_COLUMNS}
        """, (business_id, request_id, order.customer_id, customer["name"], now,
              now if order.status == "Paid" else None, amount, order.source_inquiry_id,
              source_site_id, source_site_label)).fetchone()
        db.executemany("""
            INSERT INTO order_items (order_id, product_id, product, quantity, unit_price_paise)
            VALUES (?, ?, ?, ?, ?)
        """, [(row["id"], *item) for item in items])
        for product_id, delta, stock_after in stock_changes:
            record_movement(db, account, product_id, delta, stock_after, "Order recorded", order_id=row["id"])
        if order.status == "Paid":
            record_activity(db, business_id, account.email, "Paid order recorded", f"#ORD-{row['id']}")
        return serialize_order(db, row)


@router.put("/{order_id}/paid")
def mark_order_paid(order_id: int, account: OperationsAccount):
    if not 1 <= order_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Order not found")
    with get_db() as db:
        row = db.execute(f"""
            UPDATE orders SET paid_at = ?
            WHERE id = ? AND business_id = ? AND cancelled_at IS NULL AND refunded_at IS NULL
              AND paid_at IS NULL
            RETURNING {ORDER_COLUMNS}
        """, (datetime.now(timezone.utc).isoformat(), order_id, account.business_id)).fetchone()
        if not row:
            existing = db.execute(
                f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = ? AND business_id = ?",
                (order_id, account.business_id),
            ).fetchone()
            if existing is None:
                raise HTTPException(status_code=404, detail="Order not found")
            order = serialize_order(db, existing)
            if order["status"] == "Paid":
                return order
            raise HTTPException(status_code=409, detail=f"{order['status']} orders cannot be marked paid")
        record_activity(db, account.business_id, account.email, "Payment recorded", f"#ORD-{order_id}")
        return serialize_order(db, row)


@router.put("/{order_id}/cancel")
def cancel_order(order_id: int, account: OperationsAccount):
    if not 1 <= order_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Order not found")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = ? AND business_id = ?",
            (order_id, account.business_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        order = serialize_order(db, row)
        if order["cancelled_at"]:
            return order
        if order["paid_at"]:
            raise HTTPException(status_code=409, detail="Only pending orders can be cancelled")

        restore_stock(db, order["items"], account, order_id, "Order cancelled")
        cancelled_at = datetime.now(timezone.utc).isoformat()
        db.execute(
            "UPDATE orders SET cancelled_at = ? WHERE id = ? AND business_id = ?",
            (cancelled_at, order_id, account.business_id),
        )
        record_activity(db, account.business_id, account.email, "Order cancelled", f"#ORD-{order_id}")
        return {**order, "cancelled_at": cancelled_at, "status": "Cancelled"}


@router.put("/{order_id}/refund")
def refund_order(order_id: int, refund: OrderRefund, account: ManagerAccount):
    if not 1 <= order_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Order not found")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            f"SELECT {ORDER_COLUMNS} FROM orders WHERE id = ? AND business_id = ?",
            (order_id, account.business_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Order not found")
        order = serialize_order(db, row)
        if order["refunded_at"]:
            if order["refund_restocked"] != refund.restock:
                raise HTTPException(status_code=409, detail="Refund already recorded with a different stock choice")
            return order
        if order["status"] != "Paid":
            raise HTTPException(status_code=409, detail="Only paid orders can be refunded")
        if refund.restock:
            restore_stock(db, order["items"], account, order_id, "Refund restock")

        refunded_at = datetime.now(timezone.utc).isoformat()
        db.execute("""
            UPDATE orders SET refunded_at = ?, refund_restocked = ?
            WHERE id = ? AND business_id = ?
        """, (refunded_at, refund.restock, order_id, account.business_id))
        stock = "Items returned to stock" if refund.restock else "Stock unchanged"
        record_activity(db, account.business_id, account.email, "Refund recorded", f"#ORD-{order_id} · {stock}")
        return {**order, "refunded_at": refunded_at, "refund_restocked": refund.restock, "status": "Refunded"}
