import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, Field, StringConstraints

from auth import ManagerAccount, normalize_email
from customers import Customer, CustomerDetails, insert_customer
from database import get_db


router = APIRouter(prefix="/api/storefront", tags=["Website inquiries"])
InquiryStatus = Literal["new", "in_progress", "resolved"]
InquiryId = Annotated[int, Path(gt=0, le=2**63 - 1)]


class InquiryCreate(BaseModel):
    request_id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] = ""
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] = ""
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class InquiryUpdate(BaseModel):
    status: InquiryStatus


class InquiryNotes(BaseModel):
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class CustomerLink(BaseModel):
    customer_id: int | None = Field(gt=0, le=2**63 - 1)


class Inquiry(BaseModel):
    id: int
    website_id: int
    website_label: str
    name: str
    email: str
    phone: str
    message: str
    status: InquiryStatus
    created_at: str
    updated_at: str | None
    updated_by: str | None
    customer_id: int | None
    customer_name: str | None
    notes: str
    notes_updated_at: str | None
    notes_updated_by: str | None
    order_id: int | None


class InquiryCustomerCreated(BaseModel):
    inquiry: Inquiry
    customer: Customer


INQUIRY_QUERY = """
    SELECT i.id, i.website_id, s.label AS website_label, i.name, i.email, i.phone, i.message,
           i.status, i.created_at, i.updated_at, i.updated_by, i.customer_id,
           c.name AS customer_name, i.notes, i.notes_updated_at, i.notes_updated_by, o.id AS order_id
    FROM website_inquiries AS i JOIN storefront_websites AS s ON s.id = i.website_id
    LEFT JOIN customers AS c ON c.id = i.customer_id AND c.business_id = i.business_id
    LEFT JOIN orders AS o ON o.source_inquiry_id = i.id AND o.business_id = i.business_id
    WHERE i.business_id = ? AND s.business_id = i.business_id
"""


def initialize_inquiries():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS website_inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                website_id INTEGER NOT NULL REFERENCES storefront_websites(id),
                request_id TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new', 'in_progress', 'resolved')),
                created_at TEXT NOT NULL,
                updated_at TEXT,
                updated_by TEXT,
                customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
                notes TEXT NOT NULL DEFAULT '',
                notes_updated_at TEXT,
                notes_updated_by TEXT,
                UNIQUE(website_id, request_id)
            );
            CREATE INDEX IF NOT EXISTS website_inquiries_business_id ON website_inquiries(business_id, id);
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(website_inquiries)")}
        for column, definition in (
            ("customer_id", "INTEGER REFERENCES customers(id) ON DELETE SET NULL"),
            ("notes", "TEXT NOT NULL DEFAULT ''"),
            ("notes_updated_at", "TEXT"),
            ("notes_updated_by", "TEXT"),
        ):
            if column not in columns:
                db.execute(f"ALTER TABLE website_inquiries ADD COLUMN {column} {definition}")


def get_inquiry(db, business_id, inquiry_id):
    row = db.execute(INQUIRY_QUERY + " AND i.id = ?", (business_id, inquiry_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    return dict(row)


@router.post("/public/{slug}/inquiries", status_code=204)
def send_inquiry(slug: str, body: InquiryCreate):
    if not body.email and not body.phone:
        raise HTTPException(status_code=422, detail="Enter an email address or phone number")
    email = normalize_email(body.email) if body.email else ""
    if body.phone and not any(character.isdecimal() for character in body.phone):
        raise HTTPException(status_code=422, detail="Enter a phone number with digits")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = db.execute("""
            SELECT id, business_id, snapshot FROM storefront_websites
            WHERE slug = ? AND archived_at IS NULL
        """, (slug,)).fetchone()
        if site is None or json.loads(site["snapshot"]).get("accept_inquiries") is not True:
            raise HTTPException(status_code=404, detail="This website is not accepting enquiries")
        db.execute("""
            INSERT INTO website_inquiries (business_id, website_id, request_id, name, email, phone, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (website_id, request_id) DO NOTHING
        """, (site["business_id"], site["id"], str(body.request_id), body.name, email, body.phone,
              body.message, datetime.now(timezone.utc).isoformat()))
    return Response(status_code=204)


@router.get("/inquiries", response_model=list[Inquiry])
def list_inquiries(account: ManagerAccount):
    with get_db() as db:
        rows = db.execute(INQUIRY_QUERY + " ORDER BY i.id DESC", (account.business_id,)).fetchall()
    return [dict(row) for row in rows]


@router.put("/inquiries/{inquiry_id}/status", response_model=Inquiry)
def update_inquiry_status(
    inquiry_id: InquiryId, body: InquiryUpdate, account: ManagerAccount,
):
    with get_db() as db:
        db.execute("""
            UPDATE website_inquiries SET status = ?, updated_at = ?, updated_by = ?
            WHERE id = ? AND business_id = ? AND status != ?
        """, (body.status, datetime.now(timezone.utc).isoformat(), account.email,
              inquiry_id, account.business_id, body.status))
        return get_inquiry(db, account.business_id, inquiry_id)


@router.put("/inquiries/{inquiry_id}/notes", response_model=Inquiry)
def save_inquiry_notes(inquiry_id: InquiryId, body: InquiryNotes, account: ManagerAccount):
    with get_db() as db:
        db.execute("""
            UPDATE website_inquiries SET notes = ?, notes_updated_at = ?, notes_updated_by = ?
            WHERE id = ? AND business_id = ? AND notes != ?
        """, (body.notes, datetime.now(timezone.utc).isoformat(), account.email,
              inquiry_id, account.business_id, body.notes))
        return get_inquiry(db, account.business_id, inquiry_id)


@router.put("/inquiries/{inquiry_id}/customer", response_model=Inquiry)
def link_customer(inquiry_id: InquiryId, body: CustomerLink, account: ManagerAccount):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        get_inquiry(db, account.business_id, inquiry_id)
        if body.customer_id is not None and db.execute("""
            SELECT 1 FROM customers WHERE id = ? AND business_id = ?
        """, (body.customer_id, account.business_id)).fetchone() is None:
            raise HTTPException(status_code=404, detail="Customer not found")
        db.execute("""
            UPDATE website_inquiries SET customer_id = ? WHERE id = ? AND business_id = ?
        """, (body.customer_id, inquiry_id, account.business_id))
        return get_inquiry(db, account.business_id, inquiry_id)


@router.post("/inquiries/{inquiry_id}/customer", response_model=InquiryCustomerCreated)
def create_inquiry_customer(inquiry_id: InquiryId, account: ManagerAccount):
    business_id = account.business_id
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        inquiry = get_inquiry(db, business_id, inquiry_id)
        existing = db.execute("""
            SELECT id, name, email, phone FROM customers WHERE id = ? AND business_id = ?
        """, (inquiry["customer_id"], business_id)).fetchone()
        if existing is not None:
            return {"inquiry": inquiry, "customer": dict(existing)}
        customer = insert_customer(db, business_id, CustomerDetails(
            name=inquiry["name"], email=inquiry["email"], phone=inquiry["phone"],
        ))
        db.execute("""
            UPDATE website_inquiries SET customer_id = ? WHERE id = ? AND business_id = ?
        """, (customer["id"], inquiry_id, business_id))
        return {"inquiry": get_inquiry(db, business_id, inquiry_id), "customer": customer}
