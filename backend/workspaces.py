import json
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from activity import record_activity
from auth import AssignableRole, CurrentAccount, CurrentIdentity, WorkspaceRole, access_candidates, merge_access
from database import get_db


router = APIRouter(prefix="/api/workspaces", tags=["Workspaces"])


class Workspace(BaseModel):
    id: int
    name: str
    role: WorkspaceRole
    access: Literal["direct", "agency"] = "direct"
    agency_names: list[str] = []


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Member(BaseModel):
    id: int
    email: str
    role: WorkspaceRole
    website_ids: list[int] | None = None


class WebsiteAccess(BaseModel):
    website_ids: list[Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]] | None


class MemberRole(BaseModel):
    role: AssignableRole = "manager"


class MemberGrant(MemberRole):
    email: str = Field(min_length=3, max_length=254)


@router.get("", response_model=list[Workspace])
def list_workspaces(identity: CurrentIdentity):
    with get_db() as db:
        access = merge_access(access_candidates(db, identity.user_id))
    return sorted((
        Workspace(id=item["business_id"], name=item["business_name"], role=item["role"],
                  access=item["access"], agency_names=item["agency_names"])
        for item in access.values()
    ), key=lambda workspace: (workspace.name, workspace.id))


@router.post("", response_model=Workspace, status_code=201)
def create_workspace(body: WorkspaceCreate, identity: CurrentIdentity):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a business name")
    with get_db() as db:
        cursor = db.execute("INSERT INTO businesses (name) VALUES (?)", (name,))
        business_id = cursor.lastrowid
        db.execute("""
            INSERT INTO business_memberships (business_id, user_id, role) VALUES (?, ?, 'owner')
        """, (business_id, identity.user_id))
    return Workspace(id=business_id, name=name, role="owner")


def require_owner(account: CurrentAccount):
    if account.role != "owner":
        raise HTTPException(status_code=403, detail="Only a business owner can manage team access")


@router.get("/members", response_model=list[Member])
def list_members(account: CurrentAccount):
    require_owner(account)
    with get_db() as db:
        rows = db.execute("""
            SELECT users.id, users.email, business_memberships.role, business_memberships.website_ids
            FROM business_memberships JOIN users ON users.id = business_memberships.user_id
            WHERE business_memberships.business_id = ? ORDER BY users.email
        """, (account.business_id,)).fetchall()
    return [
        {**dict(row), "website_ids": json.loads(row["website_ids"]) if row["website_ids"] is not None else None}
        for row in rows
    ]


@router.post("/members", response_model=Member, status_code=201)
def grant_member(body: MemberGrant, account: CurrentAccount):
    require_owner(account)
    email = body.email.strip().casefold()
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Ask this person to create a Vyapari account first")
        result = db.execute("""
            INSERT INTO business_memberships (business_id, user_id, role, website_ids)
            VALUES (?, ?, ?, ?) ON CONFLICT (business_id, user_id) DO NOTHING
        """, (account.business_id, user["id"], body.role, "[]" if body.role == "website_editor" else None))
        if result.rowcount == 0:
            raise HTTPException(status_code=409, detail="This person already has workspace access")
        record_activity(db, account.business_id, account.email, "Team access granted", f"{email} · {body.role}")
    return Member(id=user["id"], email=email, role=body.role, website_ids=[] if body.role == "website_editor" else None)


@router.put("/members/{user_id}", response_model=Member)
def update_member_role(user_id: int, body: MemberRole, account: CurrentAccount):
    require_owner(account)
    if not 1 <= user_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT users.email, membership.role, membership.website_ids
            FROM business_memberships AS membership JOIN users ON users.id = membership.user_id
            WHERE membership.business_id = ? AND membership.user_id = ?
              AND membership.role != 'owner'
        """, (account.business_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Workspace member not found")
        scope = row["website_ids"]
        if row["role"] != body.role:
            scope = "[]" if body.role == "website_editor" else None
            db.execute("""
                UPDATE business_memberships SET role = ?, website_ids = ? WHERE business_id = ? AND user_id = ?
            """, (body.role, scope, account.business_id, user_id))
            record_activity(
                db, account.business_id, account.email, "Team role changed",
                f"{row['email']} · {row['role']} → {body.role}",
            )
    return Member(id=user_id, email=row["email"], role=body.role, website_ids=json.loads(scope) if scope is not None else None)


@router.put("/members/{user_id}/websites", response_model=Member)
def update_website_access(user_id: int, body: WebsiteAccess, account: CurrentAccount):
    require_owner(account)
    if not 1 <= user_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Website editor not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""
            SELECT users.email, membership.website_ids
            FROM business_memberships AS membership JOIN users ON users.id = membership.user_id
            WHERE membership.business_id = ? AND membership.user_id = ? AND membership.role = 'website_editor'
        """, (account.business_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Website editor not found")
        ids = None
        access = "All current and future websites"
        if body.website_ids is not None:
            ids = sorted(set(body.website_ids))
            available = {site["id"]: site["label"] for site in db.execute(
                "SELECT id, label FROM storefront_websites WHERE business_id = ?", (account.business_id,)
            )}
            if not available.keys() >= set(ids):
                raise HTTPException(status_code=422, detail="Choose websites from this business")
            access = ", ".join(available[id] for id in ids) if ids else "No websites"
        previous = None if row["website_ids"] is None else sorted(json.loads(row["website_ids"]))
        if previous != ids:
            db.execute("""
                UPDATE business_memberships SET website_ids = ? WHERE business_id = ? AND user_id = ?
            """, (json.dumps(ids) if ids is not None else None, account.business_id, user_id))
            record_activity(db, account.business_id, account.email, "Website access changed", f"{row['email']} · {access}")
    return Member(id=user_id, email=row["email"], role="website_editor", website_ids=ids)


@router.delete("/members/{user_id}", status_code=204)
def revoke_member(user_id: int, account: CurrentAccount):
    require_owner(account)
    if not 1 <= user_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    with get_db() as db:
        result = db.execute("""
            DELETE FROM business_memberships WHERE business_id = ? AND user_id = ? AND role != 'owner'
        """, (account.business_id, user_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Workspace member not found")
        email = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()["email"]
        record_activity(db, account.business_id, account.email, "Team access removed", email)
    return Response(status_code=204)

