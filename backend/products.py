
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth import ManagerAccount, OperationsAccount
from database import get_db
from inventory import MAX_STOCK, PRODUCT_COLUMNS, get_inventory_product, record_movement


router = APIRouter(prefix="/api/products", tags=["Products"])


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=100)
    price: float = Field(ge=0, allow_inf_nan=False)
    stock: int = Field(ge=0, le=MAX_STOCK)
    low_stock_threshold: int = Field(default=10, ge=0, le=MAX_STOCK)
    restock_target: int | None = Field(default=None, ge=0, le=MAX_STOCK)


class ProductUpdate(ProductCreate):
    expected_stock: int | None = Field(default=None, ge=0, le=MAX_STOCK)


class Product(ProductCreate):
    id: int


def initialize_database():
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                price REAL NOT NULL CHECK(price >= 0),
                stock INTEGER NOT NULL CHECK(stock >= 0),
                low_stock_threshold INTEGER NOT NULL DEFAULT 10 CHECK(low_stock_threshold >= 0),
                restock_target INTEGER CHECK(restock_target >= 0),
                business_id INTEGER REFERENCES businesses(id)
            )
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(products)")}
        if "business_id" not in columns:
            db.execute("ALTER TABLE products ADD COLUMN business_id INTEGER REFERENCES businesses(id)")
        if "low_stock_threshold" not in columns:
            db.execute("""
                ALTER TABLE products ADD COLUMN low_stock_threshold INTEGER NOT NULL DEFAULT 10
                CHECK(low_stock_threshold >= 0)
            """)
        if "restock_target" not in columns:
            db.execute("ALTER TABLE products ADD COLUMN restock_target INTEGER CHECK(restock_target >= 0)")
        db.execute("CREATE INDEX IF NOT EXISTS products_business_id ON products (business_id, id)")


@router.get("", response_model=list[Product])
def list_products(account: OperationsAccount):
    with get_db() as db:
        rows = db.execute(
            f"""
            SELECT {PRODUCT_COLUMNS}
            FROM products
            WHERE business_id = ?
            ORDER BY id DESC
            """,
            (account.business_id,),
        ).fetchall()

    return [dict(row) for row in rows]


def product_values(product: ProductCreate):
    name = product.name.strip()

    if not name:
        raise HTTPException(
            status_code=422,
            detail="Product name cannot be empty",
        )

    return name, product.category.strip(), product.price


def validate_restock_target(threshold, target):
    if target is not None and target < threshold:
        raise HTTPException(status_code=422, detail="Target stock must be at least the low-stock threshold")


@router.post("", response_model=Product, status_code=201)
def create_product(product: ProductCreate, account: ManagerAccount):
    validate_restock_target(product.low_stock_threshold, product.restock_target)
    with get_db() as db:
        row = db.execute(f"""
            INSERT INTO products (name, category, price, stock, business_id, low_stock_threshold, restock_target)
            VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING {PRODUCT_COLUMNS}
        """, (*product_values(product), product.stock, account.business_id,
              product.low_stock_threshold, product.restock_target)).fetchone()
        record_movement(db, account, row["id"], row["stock"], row["stock"], "Opening stock")
    return dict(row)


@router.put("/{product_id}", response_model=Product)
def update_product(product_id: int, product: ProductUpdate, account: ManagerAccount):
    if not 1 <= product_id <= MAX_STOCK:
        raise HTTPException(status_code=404, detail="Product not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = get_inventory_product(db, account.business_id, product_id)
        old_stock = previous["stock"]
        expected_stock = getattr(product, "expected_stock", None)
        stock = product.stock
        if expected_stock is not None and old_stock != expected_stock:
            if stock == expected_stock:
                stock = old_stock
            elif stock != old_stock:
                raise HTTPException(status_code=409, detail="Stock changed. Reopen the product to review the current count")
        threshold = (
            product.low_stock_threshold if "low_stock_threshold" in product.model_fields_set
            else previous["low_stock_threshold"]
        )
        target = product.restock_target if "restock_target" in product.model_fields_set else previous["restock_target"]
        validate_restock_target(threshold, target)
        row = db.execute(f"""
            UPDATE products SET name = ?, category = ?, price = ?, stock = ?,
                                low_stock_threshold = ?, restock_target = ?
            WHERE id = ? AND business_id = ? RETURNING {PRODUCT_COLUMNS}
        """, (*product_values(product), stock, threshold, target, product_id, account.business_id)).fetchone()
        record_movement(db, account, product_id, stock - old_stock, stock, "Stock edited")
    return dict(row)


@router.delete("/{product_id}")
def delete_product(product_id: int, account: ManagerAccount):
    if not 1 <= product_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Product not found")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        pending_order = db.execute("""
            SELECT 1 FROM order_items
            JOIN orders ON orders.id = order_items.order_id
            WHERE order_items.product_id = ? AND orders.business_id = ?
              AND orders.paid_at IS NULL AND orders.cancelled_at IS NULL
            LIMIT 1
        """, (product_id, account.business_id)).fetchone()
        if pending_order:
            raise HTTPException(
                status_code=409,
                detail="This product is in a pending order. Resolve the order before deleting the product.",
            )
        if db.execute("""
            SELECT 1 FROM purchase_items
            JOIN purchase_orders ON purchase_orders.id = purchase_items.purchase_id
            WHERE purchase_items.product_id = ? AND purchase_orders.business_id = ?
              AND purchase_orders.status = 'ordered' LIMIT 1
        """, (product_id, account.business_id)).fetchone():
            raise HTTPException(status_code=409, detail="Close the open purchase order before deleting this product")
        cursor = db.execute(
            "DELETE FROM products WHERE id = ? AND business_id = ?",
            (product_id, account.business_id),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Product not found",
            )

    return {"message": "Product deleted successfully"}
