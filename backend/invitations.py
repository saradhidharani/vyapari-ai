import secrets
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, Field

from activity import record_activity
from auth import CurrentAccount, WorkspaceRole, Identity, SignIn, create_session, normalize_email, password_hash, token_hash, workspace_account
from database import get_db
from verification import CodeSent, consume_code, find_user, identity_for, request_code, verify_password_or_fail
from workspaces import MemberGrant, require_owner


router = APIRouter(prefix="/api/workspaces/invitations", tags=["Workspaces"])
auth_router = APIRouter(prefix="/api/auth/invitations", tags=["Authentication"])
INVITE_TTL = 7 * 24 * 60 * 60
INVITATION_SCHEMA = """
    CREATE TABLE IF NOT EXISTS {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id INTEGER NOT NULL REFERENCES businesses(id),
        email TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('owner', 'manager', 'sales', 'website_editor')),
        token_hash BLOB NOT NULL UNIQUE,
        expires_at INTEGER NOT NULL,
        accepted_at INTEGER,
        revoked_at INTEGER
    )
"""


class InvitationToken(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class AcceptInvitation(InvitationToken):
    password: str = Field(min_length=12, max_length=128)
    code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class Invitation(BaseModel):
    id: int
    email: str
    # Owner invitations are only issued by an agency for a client workspace that has no owner yet.
    role: WorkspaceRole
    expires_at: int


class CreatedInvitation(Invitation):
    token: str


class InvitationPreview(BaseModel):
    email: str
    role: WorkspaceRole
    business_name: str
    existing_account: bool
    verification_required: bool


def initialize_invitations():
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(INVITATION_SCHEMA.format(table="workspace_invitations"))
        schema = db.execute("""
            SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'workspace_invitations'
        """).fetchone()["sql"]
        if "'owner'" not in schema:
            db.execute(INVITATION_SCHEMA.format(table="workspace_invitations_new"))
            db.execute("""
                INSERT INTO workspace_invitations_new
                    (id, business_id, email, role, token_hash, expires_at, accepted_at, revoked_at)
                SELECT id, business_id, email, role, token_hash, expires_at, accepted_at, revoked_at
                FROM workspace_invitations
            """)
            db.execute("DROP TABLE workspace_invitations")
            db.execute("ALTER TABLE workspace_invitations_new RENAME TO workspace_invitations")
        db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS workspace_invitations_pending
            ON workspace_invitations (business_id, email)
            WHERE accepted_at IS NULL AND revoked_at IS NULL
        """)


def has_owner(db, business_id):
    return db.execute("""
        SELECT 1 FROM business_memberships WHERE business_id = ? AND role = 'owner'
    """, (business_id,)).fetchone() is not None


def issue_owner_invitation(db, business_id, email, actor):
    """Create an owner invitation for a workspace without an owner. Any earlier
    pending owner invitation for the workspace is revoked."""
    if has_owner(db, business_id):
        raise HTTPException(status_code=409, detail="This business already has an owner")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("""
        UPDATE workspace_invitations SET revoked_at = ?
        WHERE business_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND (role = 'owner' OR email = ?)
    """, (now, business_id, email))
    row = db.execute("""
        INSERT INTO workspace_invitations (business_id, email, role, token_hash, expires_at)
        VALUES (?, ?, 'owner', ?, ?) RETURNING id, email, role, expires_at
    """, (business_id, email, token_hash(token), now + INVITE_TTL)).fetchone()
    record_activity(db, business_id, actor, "Owner invitation created", email)
    return CreatedInvitation(**dict(row), token=token)


@router.get("", response_model=list[Invitation])
def list_invitations(account: CurrentAccount):
    require_owner(account)
    with get_db() as db:
        rows = db.execute("""
            SELECT id, email, role, expires_at FROM workspace_invitations
            WHERE business_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
            ORDER BY id DESC
        """, (account.business_id, int(time.time()))).fetchall()
    return [dict(row) for row in rows]


@router.post("", response_model=CreatedInvitation, status_code=201)
def create_invitation(body: MemberGrant, account: CurrentAccount):
    require_owner(account)
    email = normalize_email(body.email)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        member = db.execute("""
            SELECT 1 FROM business_memberships JOIN users ON users.id = business_memberships.user_id
            WHERE business_memberships.business_id = ? AND users.email = ?
        """, (account.business_id, email)).fetchone()
        if member:
            raise HTTPException(status_code=409, detail="This person already has workspace access")
        db.execute("""
            UPDATE workspace_invitations SET revoked_at = ?
            WHERE business_id = ? AND email = ? AND accepted_at IS NULL AND revoked_at IS NULL
        """, (now, account.business_id, email))
        row = db.execute("""
            INSERT INTO workspace_invitations (business_id, email, role, token_hash, expires_at)
            VALUES (?, ?, ?, ?, ?) RETURNING id, email, role, expires_at
        """, (account.business_id, email, body.role, token_hash(token), now + INVITE_TTL)).fetchone()
        record_activity(db, account.business_id, account.email, "Team invitation created", f"{email} · {body.role}")
    return CreatedInvitation(**dict(row), token=token)


@router.delete("/{invite_id}", status_code=204)
def revoke_invitation(invite_id: int, account: CurrentAccount):
    require_owner(account)
    if not 1 <= invite_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    with get_db() as db:
        now = int(time.time())
        row = db.execute("""
            UPDATE workspace_invitations SET revoked_at = ?
            WHERE id = ? AND business_id = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
            RETURNING email
        """, (now, invite_id, account.business_id, now)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Pending invitation not found")
        record_activity(db, account.business_id, account.email, "Team invitation revoked", row["email"])
    return Response(status_code=204)


def active_invitation(db, token):
    row = db.execute("""
        SELECT workspace_invitations.*, businesses.name AS business_name
        FROM workspace_invitations JOIN businesses ON businesses.id = workspace_invitations.business_id
        WHERE token_hash = ? AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > ?
    """, (token_hash(token), int(time.time()))).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="This invitation expired, was revoked, or was already used")
    return row


@auth_router.post("/preview", response_model=InvitationPreview)
def preview_invitation(body: InvitationToken):
    with get_db() as db:
        invite = active_invitation(db, body.token)
        user = db.execute("SELECT email_verified_at FROM users WHERE email = ?", (invite["email"],)).fetchone()
    return InvitationPreview(
        email=invite["email"], business_name=invite["business_name"], role=invite["role"],
        existing_account=user is not None,
        verification_required=user is None or user["email_verified_at"] is None,
    )


@auth_router.post("/send-code", response_model=CodeSent, status_code=202)
def send_invitation_code(body: InvitationToken, request: Request, background: BackgroundTasks):
    """Email a code to the invited address. Only the invited email can accept."""
    with get_db() as db:
        invite = active_invitation(db, body.token)
    return request_code(background, request, "invitation", invite["email"])


@auth_router.post("/accept", response_model=SignIn)
def accept_invitation(body: AcceptInvitation, request: Request):
    """Accept an invitation as the person it was issued to.

    Verified accounts confirm with their password. New accounts, and existing
    accounts that have not verified their email yet, also need the code emailed to
    the invited address. The invitation grants only its own business and role."""
    with get_db() as db:
        invite = active_invitation(db, body.token)
        user = find_user(db, invite["email"])
    email = invite["email"]
    if user is not None:
        user = verify_password_or_fail(request, email, body.password, "Incorrect password for the invited account")
    needs_code = user is None or user["email_verified_at"] is None
    if needs_code:
        if not body.code:
            raise HTTPException(status_code=422, detail="Enter the code we emailed to the invited address")
        consume_code(request, "invitation", email, body.code)
    salt = secrets.token_bytes(16)
    new_hash = password_hash(body.password, salt) if user is None else None
    now = int(time.time())
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        invite = active_invitation(db, body.token)
        business_id = invite["business_id"]
        current = find_user(db, email)
        if (current is None) != (user is None):
            raise HTTPException(status_code=409, detail="This account changed while you were joining. Open the invitation again.")
        if current is None:
            user_id = db.execute("""
                INSERT INTO users (email, password_hash, salt, business_id, owns_home, email_verified_at)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (email, new_hash, salt, business_id, now)).lastrowid
            identity = Identity(user_id=user_id, email=email, home_business_id=business_id, is_platform_admin=False)
        else:
            if needs_code:
                db.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) WHERE id = ?",
                           (now, current["id"]))
            identity = identity_for(current)

        if invite["role"] == "owner":
            if has_owner(db, business_id):
                raise HTTPException(status_code=409, detail="This business already has an owner")
            db.execute("""
                INSERT INTO business_memberships (business_id, user_id, role, website_ids)
                VALUES (?, ?, 'owner', NULL)
                ON CONFLICT (business_id, user_id) DO UPDATE SET role = 'owner', website_ids = NULL
            """, (business_id, identity.user_id))
            db.execute("""
                UPDATE workspace_invitations SET revoked_at = ?
                WHERE business_id = ? AND role = 'owner' AND id != ? AND accepted_at IS NULL AND revoked_at IS NULL
            """, (now, business_id, invite["id"]))
        else:
            db.execute("""
                INSERT INTO business_memberships (business_id, user_id, role, website_ids)
                VALUES (?, ?, ?, ?) ON CONFLICT (business_id, user_id) DO NOTHING
            """, (business_id, identity.user_id, invite["role"], "[]" if invite["role"] == "website_editor" else None))
        db.execute("UPDATE workspace_invitations SET accepted_at = ? WHERE id = ?", (now, invite["id"]))
        account = workspace_account(db, identity, business_id)
        record_activity(db, business_id, email, "Team invitation accepted", account.role)
        token = create_session(db, identity.user_id)
    return SignIn(**account.model_dump(), token=token)
