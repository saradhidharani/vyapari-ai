from datetime import datetime, timezone
import json
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, Field

from activity import record_activity
from auth import ManagerAccount, WebsiteAccount
from database import get_db


router = APIRouter(prefix="/api/storefront", tags=["Storefront"])
DEFAULT_HEADLINE = "Tradition, styled for today."
DEFAULT_COLOR = "#7158db"
SiteId = Annotated[int | None, Query(gt=0, le=2**63 - 1)]
WebsitePathId = Annotated[int, Path(gt=0, le=2**63 - 1)]
WEBSITE_COLUMNS = "id, label, slug IS NOT NULL AS published, archived_at"


class StorefrontDesign(BaseModel):
    name: str = Field(max_length=100)
    headline: str = Field(max_length=200)
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    accept_inquiries: bool = Field(default=False, strict=True)


class StorefrontDraft(StorefrontDesign):
    product_ids: list[Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]] | None = None


class WebsiteCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)


class Website(BaseModel):
    id: int
    label: str
    published: bool
    archived_at: str | None = None


class WebsiteArchive(BaseModel):
    archived: bool = Field(strict=True)


class Publication(BaseModel):
    slug: str
    published_at: str


class PublicProduct(BaseModel):
    name: str
    price: float


class CatalogProduct(PublicProduct):
    id: int


class PublicStorefront(StorefrontDesign):
    products: list[PublicProduct]


def initialize_storefronts():
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            CREATE TABLE IF NOT EXISTS storefront_websites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                label TEXT NOT NULL COLLATE NOCASE,
                name TEXT NOT NULL,
                headline TEXT NOT NULL,
                accent_color TEXT NOT NULL,
                draft_saved INTEGER NOT NULL DEFAULT 0,
                product_ids TEXT,
                slug TEXT UNIQUE,
                published_at TEXT,
                snapshot TEXT,
                archived_at TEXT,
                accept_inquiries INTEGER NOT NULL DEFAULT 0 CHECK(accept_inquiries IN (0, 1)),
                UNIQUE (business_id, label)
            )
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(storefront_websites)")}
        if "product_ids" not in columns:
            db.execute("ALTER TABLE storefront_websites ADD COLUMN product_ids TEXT")
        if "archived_at" not in columns:
            db.execute("ALTER TABLE storefront_websites ADD COLUMN archived_at TEXT")
        if "accept_inquiries" not in columns:
            db.execute("""
                ALTER TABLE storefront_websites ADD COLUMN accept_inquiries INTEGER NOT NULL DEFAULT 0
                CHECK(accept_inquiries IN (0, 1))
            """)
        tables = {row["name"] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        if {"storefront_drafts", "storefront_publications"} <= tables:
            db.execute("""
                INSERT INTO storefront_websites (
                    business_id, label, name, headline, accent_color, draft_saved,
                    slug, published_at, snapshot
                )
                SELECT b.id, 'Main website', COALESCE(d.name, b.name),
                       COALESCE(d.headline, ?), COALESCE(d.accent_color, ?),
                       d.business_id IS NOT NULL, p.slug, p.published_at, p.snapshot
                FROM businesses AS b
                LEFT JOIN storefront_drafts AS d ON d.business_id = b.id
                LEFT JOIN storefront_publications AS p ON p.business_id = b.id
                WHERE (d.business_id IS NOT NULL OR p.business_id IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM storefront_websites WHERE business_id = b.id)
            """, (DEFAULT_HEADLINE, DEFAULT_COLOR))


@router.get("/catalog", response_model=list[CatalogProduct])
def list_website_catalog(account: WebsiteAccount):
    with get_db() as db:
        if account.role == "website_editor" and find_website(db, account, None) is None:
            raise HTTPException(status_code=403, detail="You need access to an active website before you can view its catalog")
        rows = db.execute("""
            SELECT id, name, price FROM products WHERE business_id = ? ORDER BY id DESC
        """, (account.business_id,)).fetchall()
    return [dict(row) for row in rows]


def visible_websites(db, business_id, role, website_ids, include_archived=False):
    """Websites a role can see: editors see only their assigned sites and never
    archived ones. Callers must check that the role has website access."""
    assigned = None if role != "website_editor" or website_ids is None else json.dumps(website_ids)
    include_archived = include_archived and role != "website_editor"
    return db.execute(f"""
        SELECT {WEBSITE_COLUMNS}
        FROM storefront_websites WHERE business_id = ?
          AND (? IS NULL OR id IN (SELECT value FROM json_each(?)))
          AND (? OR archived_at IS NULL)
        ORDER BY id
    """, (business_id, assigned, assigned, include_archived)).fetchall()


@router.get("/sites", response_model=list[Website])
def list_websites(account: WebsiteAccount, include_archived: bool = False):
    with get_db() as db:
        rows = visible_websites(db, account.business_id, account.role, account.website_ids, include_archived)
    return [dict(row) for row in rows]


@router.post("/sites", response_model=Website, status_code=201)
def create_website(body: WebsiteCreate, account: ManagerAccount):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Enter a website name")
    with get_db() as db:
        row = insert_website(db, account.business_id, account.business_name, label)
    return dict(row)


def insert_website(db, business_id, business_name, label):
    row = db.execute(f"""
        INSERT INTO storefront_websites (business_id, label, name, headline, accent_color)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (business_id, label) DO NOTHING
        RETURNING {WEBSITE_COLUMNS}
    """, (business_id, label, business_name, DEFAULT_HEADLINE, DEFAULT_COLOR)).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="A website already uses that name in this business")
    return row


def find_website(db, account, site_id, *, include_archived=False):
    assigned = None if account.role != "website_editor" or account.website_ids is None else json.dumps(account.website_ids)
    row = db.execute("""
        SELECT * FROM storefront_websites WHERE business_id = ?
          AND (? IS NULL OR id = ?)
          AND (? IS NULL OR id IN (SELECT value FROM json_each(?)))
          AND (? OR archived_at IS NULL)
        ORDER BY id LIMIT 1
    """, (account.business_id, site_id, site_id, assigned, assigned, include_archived)).fetchone()
    if row is None and site_id is not None:
        raise HTTPException(status_code=404, detail="Website not found")
    return row


@router.patch("/sites/{site_id}", response_model=Website)
def rename_website(site_id: WebsitePathId, body: WebsiteCreate, account: ManagerAccount):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Enter a website name")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = find_website(db, account, site_id)
        if db.execute("""
            SELECT 1 FROM storefront_websites WHERE business_id = ? AND label = ? AND id != ?
        """, (account.business_id, label, site_id)).fetchone():
            raise HTTPException(status_code=409, detail="A website already uses that name in this business")
        row = db.execute(f"""
            UPDATE storefront_websites SET label = ? WHERE business_id = ? AND id = ?
            RETURNING {WEBSITE_COLUMNS}
        """, (label, account.business_id, site_id)).fetchone()
        if site["label"] != label:
            record_activity(db, account.business_id, account.email, "Website renamed", f"{site['label']} → {label}")
    return dict(row)


@router.post("/sites/{site_id}/duplicate", response_model=Website, status_code=201)
def duplicate_website(site_id: WebsitePathId, body: WebsiteCreate, account: ManagerAccount):
    label = body.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Enter a website name")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        original = find_website(db, account, site_id)
        copy = insert_website(db, account.business_id, account.business_name, label)
        db.execute("""
            UPDATE storefront_websites
            SET name = ?, headline = ?, accent_color = ?, product_ids = ?, draft_saved = ?, accept_inquiries = ?
            WHERE business_id = ? AND id = ?
        """, (original["name"], original["headline"], original["accent_color"], original["product_ids"],
              original["draft_saved"], original["accept_inquiries"], account.business_id, copy["id"]))
        record_activity(db, account.business_id, account.email, "Website duplicated", f"{original['label']} → {label}")
    return dict(copy)


@router.put("/sites/{site_id}/archive", response_model=Website)
def set_website_archived(site_id: WebsitePathId, body: WebsiteArchive, account: ManagerAccount):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = find_website(db, account, site_id, include_archived=True)
        if bool(site["archived_at"]) == body.archived:
            return {
                "id": site["id"], "label": site["label"], "published": bool(site["slug"]),
                "archived_at": site["archived_at"],
            }
        archived_at = datetime.now(timezone.utc).isoformat() if body.archived else None
        row = db.execute(f"""
            UPDATE storefront_websites SET archived_at = ?, slug = NULL, published_at = NULL, snapshot = NULL
            WHERE business_id = ? AND id = ?
            RETURNING {WEBSITE_COLUMNS}
        """, (archived_at, account.business_id, site_id)).fetchone()
        action = "Website archived" if body.archived else "Website restored"
        details = f"{site['label']} · Published link taken down" if site["slug"] else site["label"]
        record_activity(db, account.business_id, account.email, action, details)
    return dict(row)


def draft_fields(row):
    return StorefrontDesign(
        name=row["name"], headline=row["headline"], accent_color=row["accent_color"],
        accept_inquiries=bool(row["accept_inquiries"]),
    )


def available_product_ids(db, business_id, selected):
    rows = db.execute("SELECT id FROM products WHERE business_id = ?", (business_id,))
    available = {row["id"] for row in rows}
    return [product_id for product_id in selected if product_id in available]


@router.get("", response_model=StorefrontDraft)
def get_storefront(account: WebsiteAccount, site_id: SiteId = None):
    with get_db() as db:
        row = find_website(db, account, site_id)
        if row is not None:
            selected = None if row["product_ids"] is None else available_product_ids(
                db, account.business_id, json.loads(row["product_ids"])
            )
            return StorefrontDraft(**draft_fields(row).model_dump(), product_ids=selected)
    if account.role == "website_editor":
        raise HTTPException(status_code=404, detail="No website is assigned to this account")
    return StorefrontDraft(name=account.business_name, headline=DEFAULT_HEADLINE, accent_color=DEFAULT_COLOR)


@router.put("", response_model=StorefrontDraft)
def save_storefront(draft: StorefrontDraft, account: WebsiteAccount, site_id: SiteId = None):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = find_website(db, account, site_id)
        if site is None and account.role == "website_editor":
            raise HTTPException(status_code=403, detail="An owner or manager must create a website first")
        selected = draft.product_ids
        if "product_ids" not in draft.model_fields_set and site is not None and site["product_ids"] is not None:
            selected = available_product_ids(db, account.business_id, json.loads(site["product_ids"]))
        elif selected is not None:
            selected = list(dict.fromkeys(selected))
            if available_product_ids(db, account.business_id, selected) != selected:
                raise HTTPException(status_code=422, detail="Choose products from this business’s current catalog")
        serialized = None if selected is None else json.dumps(selected)
        accepts_inquiries = (
            bool(site["accept_inquiries"])
            if site is not None and "accept_inquiries" not in draft.model_fields_set
            else draft.accept_inquiries
        )
        if site is None:
            site = insert_website(db, account.business_id, account.business_name, "Main website")
        db.execute("""
            UPDATE storefront_websites
            SET name = ?, headline = ?, accent_color = ?, draft_saved = 1, product_ids = ?, accept_inquiries = ?
            WHERE business_id = ? AND id = ?
        """, (draft.name, draft.headline, draft.accent_color, serialized, accepts_inquiries,
              account.business_id, site["id"]))
    return draft.model_copy(update={"product_ids": selected, "accept_inquiries": accepts_inquiries})


@router.get("/publication", response_model=Publication | None)
def get_publication(account: WebsiteAccount, site_id: SiteId = None):
    with get_db() as db:
        row = find_website(db, account, site_id)
    if row is not None and row["slug"]:
        return Publication(slug=row["slug"], published_at=row["published_at"])
    return None


@router.put("/publication", response_model=Publication)
def publish_storefront(account: ManagerAccount, site_id: SiteId = None):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = find_website(db, account, site_id)
        if site is None or not site["draft_saved"]:
            raise HTTPException(status_code=409, detail="Save this website's draft before publishing")
        products = db.execute(
            "SELECT id, name, price FROM products WHERE business_id = ? ORDER BY id DESC",
            (account.business_id,),
        ).fetchall()
        selected = None if site["product_ids"] is None else set(json.loads(site["product_ids"]))
        snapshot = PublicStorefront(**draft_fields(site).model_dump(), products=[
            PublicProduct(name=product["name"], price=product["price"])
            for product in products if selected is None or product["id"] in selected
        ])
        row = db.execute("""
            UPDATE storefront_websites SET slug = COALESCE(slug, ?), published_at = ?, snapshot = ?
            WHERE business_id = ? AND id = ?
            RETURNING slug, published_at
        """, (uuid4().hex, datetime.now(timezone.utc).isoformat(), snapshot.model_dump_json(),
              account.business_id, site["id"])).fetchone()
        action = "Website updated" if site["slug"] else "Website published"
        record_activity(db, account.business_id, account.email, action, site["label"])
    return dict(row)


@router.delete("/publication", status_code=204)
def unpublish_storefront(account: ManagerAccount, site_id: SiteId = None):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        site = find_website(db, account, site_id)
        if site is not None and site["slug"]:
            db.execute("""
                UPDATE storefront_websites SET slug = NULL, published_at = NULL, snapshot = NULL
                WHERE business_id = ? AND id = ?
            """, (account.business_id, site["id"]))
            record_activity(db, account.business_id, account.email, "Website taken down", site["label"])
    return Response(status_code=204)


@router.get("/public/{slug}", response_model=PublicStorefront)
def read_public_storefront(slug: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with get_db() as db:
        row = db.execute(
            "SELECT snapshot FROM storefront_websites WHERE slug = ? AND archived_at IS NULL", (slug,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Storefront is unavailable", headers={"Cache-Control": "no-store"})
    return json.loads(row["snapshot"])
