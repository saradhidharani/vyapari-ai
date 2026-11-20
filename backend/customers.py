from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, field_validator

from auth import ManagerAccount, OperationsAccount
from database import get_db


router = APIRouter(prefix="/api/customers", tags=["Customers"])


class CustomerDetails(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)

    @field_validator("name", "email", "phone", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str):
        if value and (
            value.count("@") != 1
            or not all(value.split("@"))
            or any(character.isspace() for character in value)
        ):
            raise ValueError("Enter a valid email address")
        return value


class Customer(CustomerDetails):
    id: int


def initialize_customers():
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                name TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT ''
            )
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(customers)")}
        if "phone" not in columns:
            db.execute("ALTER TABLE customers ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS customers_business_id ON customers (business_id, id)")


@router.get("", response_model=list[Customer])
def list_customers(account: OperationsAccount):
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, email, phone FROM customers WHERE business_id = ? ORDER BY id DESC",
            (account.business_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("", response_model=Customer, status_code=201)
def create_customer(customer: CustomerDetails, account: OperationsAccount):
    with get_db() as db:
        return insert_customer(db, account.business_id, customer)


def insert_customer(db, business_id, customer):
    row = db.execute("""
        INSERT INTO customers (business_id, name, email, phone)
        VALUES (?, ?, ?, ?) RETURNING id, name, email, phone
    """, (business_id, customer.name, customer.email, customer.phone)).fetchone()
    return dict(row)


@router.put("/{customer_id}", response_model=Customer)
def update_customer(customer_id: int, customer: CustomerDetails, account: OperationsAccount):
    if not 1 <= customer_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Customer not found")
    phone = customer.phone if "phone" in customer.model_fields_set else None
    with get_db() as db:
        row = db.execute(
            """
            UPDATE customers SET name = ?, email = ?, phone = COALESCE(?, phone)
            WHERE id = ? AND business_id = ? RETURNING id, name, email, phone
            """,
            (customer.name, customer.email, phone, customer_id, account.business_id),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Customer not found")
    return dict(row)


@router.delete("/{customer_id}", status_code=204)
def delete_customer(customer_id: int, account: ManagerAccount):
    if not 1 <= customer_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Customer not found")
    with get_db() as db:
        result = db.execute(
            "DELETE FROM customers WHERE id = ? AND business_id = ?",
            (customer_id, account.business_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Customer not found")
    return Response(status_code=204)
