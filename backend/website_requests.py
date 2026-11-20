from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from activity import record_activity
from auth import CurrentIdentity, ManagerAccount
from database import get_db
from platform_admin import require_platform_admin
from storefront import WebsiteCreate, insert_website


router = APIRouter(prefix="/api/storefront/requests", tags=["Website requests"])
platform_router = APIRouter(prefix="/api/platform/website-requests", tags=["Platform Admin"])


class WebsiteRequestCreate(WebsiteCreate):
    notes: str = Field(default="", max_length=300)


class WebsiteDecision(BaseModel):
    status: Literal["approved", "declined"]


class WebsiteRequest(BaseModel):
    id: int
    label: str
    notes: str
    status: Literal["pending", "approved", "declined"]
    requested_by: str
    requested_at: str
    decided_by: str | None
    decided_at: str | None
    website_id: int | None


class PlatformWebsiteRequest(WebsiteRequest):
    business_id: int
    business_name: str


def initialize_website_requests():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS website_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                label TEXT NOT NULL COLLATE NOCASE,
                notes TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'declined')),
                requested_by TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                decided_by TEXT,
                decided_at TEXT,
                website_id INTEGER REFERENCES storefront_websites(id)
            );
            CREATE INDEX IF NOT EXISTS website_requests_business_id ON website_requests (business_id, id);
            CREATE UNIQUE INDEX IF NOT EXISTS website_requests_pending_label ON website_requests (business_id, label)
            WHERE status = 'pending';
        """)


COLUMNS = "id, label, notes, status, requested_by, requested_at, decided_by, decided_at, website_id"


@router.get("", response_model=list[WebsiteRequest])
def list_website_requests(account: ManagerAccount):
    with get_db() as db:
        rows = db.execute(f"""
            SELECT {COLUMNS} FROM website_requests WHERE business_id = ? ORDER BY id DESC
        """, (account.business_id,)).fetchall()
    return [dict(row) for row in rows]


@router.post("", response_model=WebsiteRequest, status_code=201)
def request_website(body: WebsiteRequestCreate, account: ManagerAccount):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Enter a website name")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("""
            SELECT 1 FROM storefront_websites WHERE business_id = ? AND label = ?
        """, (account.business_id, label)).fetchone():
            raise HTTPException(status_code=409, detail="This business already has a website with that name")
        row = db.execute(f"""
            INSERT INTO website_requests (business_id, label, notes, requested_by, requested_at)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING RETURNING {COLUMNS}
        """, (account.business_id, label, body.notes.strip(), account.email,
              datetime.now(timezone.utc).isoformat())).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="A request for this website is already pending")
    return dict(row)


@platform_router.get("", response_model=list[PlatformWebsiteRequest])
def list_platform_website_requests(identity: CurrentIdentity):
    require_platform_admin(identity)
    with get_db() as db:
        rows = db.execute("""
            SELECT r.*, b.name AS business_name FROM website_requests AS r
            JOIN businesses AS b ON b.id = r.business_id
            ORDER BY (r.status = 'pending') DESC, r.id DESC
        """).fetchall()
    return [dict(row) for row in rows]


@platform_router.put("/{request_id}", response_model=PlatformWebsiteRequest)
def decide_website_request(request_id: int, decision: WebsiteDecision, identity: CurrentIdentity):
    require_platform_admin(identity)
    if not 1 <= request_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Website request not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("""
            SELECT r.*, b.name AS business_name FROM website_requests AS r
            JOIN businesses AS b ON b.id = r.business_id WHERE r.id = ?
        """, (request_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Website request not found")
        if current["status"] == decision.status:
            return dict(current)
        if current["status"] != "pending":
            raise HTTPException(status_code=409, detail="This website request has already been decided")

        website_id = None
        if decision.status == "approved":
            site = insert_website(db, current["business_id"], current["business_name"], current["label"])
            website_id = site["id"]
        result = db.execute("""
            UPDATE website_requests SET status = ?, decided_by = ?, decided_at = ?, website_id = ?
            WHERE id = ? RETURNING *
        """, (decision.status, identity.email, datetime.now(timezone.utc).isoformat(),
              website_id, request_id)).fetchone()
        record_activity(
            db, current["business_id"], identity.email,
            f"Website request {decision.status}", current["label"],
        )
    return {**dict(result), "business_name": current["business_name"]}
