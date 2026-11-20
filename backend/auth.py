import hashlib
import json
import secrets
import sqlite3
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from database import get_db


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
bearer = HTTPBearer(auto_error=False)
SESSION_SECONDS = 12 * 60 * 60
WorkspaceRole = Literal["owner", "manager", "sales", "website_editor"]
AssignableRole = Literal["manager", "sales", "website_editor"]


class Account(BaseModel):
    email: str
    business_id: int
    business_name: str
    role: WorkspaceRole = "owner"
    is_platform_admin: bool = False
    website_ids: list[int] | None = None
    # "agency" when the effective role comes from an agency grant rather than a direct membership.
    access: Literal["direct", "agency"] = "direct"
    agency_names: list[str] = []


class SignIn(Account):
    token: str


class Identity(BaseModel):
    user_id: int
    email: str
    home_business_id: int
    is_platform_admin: bool


def initialize_accounts():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS businesses (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash BLOB NOT NULL,
                salt BLOB NOT NULL,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                owns_home INTEGER NOT NULL DEFAULT 1 CHECK(owns_home IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash BLOB PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS business_memberships (
                business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner', 'manager', 'sales', 'website_editor')),
                PRIMARY KEY (business_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS memberships_user_id
            ON business_memberships(user_id, business_id);
            CREATE TABLE IF NOT EXISTS platform_admins (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        db.execute("BEGIN IMMEDIATE")
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "owns_home" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN owns_home INTEGER NOT NULL DEFAULT 1 CHECK(owns_home IN (0, 1))")
        schema = db.execute("""
            SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'business_memberships'
        """).fetchone()["sql"]
        if "'website_editor'" not in schema:
            db.execute("""
                CREATE TABLE business_memberships_new (
                    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('owner', 'manager', 'sales', 'website_editor')),
                    PRIMARY KEY (business_id, user_id)
                )
            """)
            db.execute("""
                INSERT INTO business_memberships_new (business_id, user_id, role)
                SELECT business_id, user_id, role FROM business_memberships
            """)
            db.execute("DROP TABLE business_memberships")
            db.execute("ALTER TABLE business_memberships_new RENAME TO business_memberships")
            db.execute("""
                CREATE INDEX memberships_user_id ON business_memberships(user_id, business_id)
            """)
        membership_columns = {row["name"] for row in db.execute("PRAGMA table_info(business_memberships)")}
        if "website_ids" not in membership_columns:
            db.execute("ALTER TABLE business_memberships ADD COLUMN website_ids TEXT")
        db.execute("""
            INSERT OR IGNORE INTO business_memberships (business_id, user_id, role)
            SELECT business_id, id, 'owner' FROM users WHERE owns_home = 1
        """)


def password_hash(password: str, salt: bytes):
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**17, r=8, p=1, maxmem=256 * 1024**2
    )


def token_hash(token: str):
    return hashlib.sha256(token.encode()).digest()


def create_session(db: sqlite3.Connection, user_id: int):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    db.execute(
        "INSERT INTO sessions VALUES (?, ?, ?)",
        (token_hash(token), user_id, now + SESSION_SECONDS),
    )
    return token


Bearer = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def require_identity(credentials: Bearer):
    if credentials:
        with get_db() as db:
            row = db.execute("""
                SELECT users.id AS user_id, users.email, users.business_id AS home_business_id,
                       platform_admins.user_id IS NOT NULL AS is_platform_admin
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                LEFT JOIN platform_admins ON platform_admins.user_id = users.id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                  AND users.email_verified_at IS NOT NULL
            """, (token_hash(credentials.credentials), int(time.time()))).fetchone()
        if row:
            return Identity(**dict(row))
    raise HTTPException(status_code=401, detail="Please sign in", headers={"WWW-Authenticate": "Bearer"})


CurrentIdentity = Annotated[Identity, Depends(require_identity)]


ROLE_RANK = {"owner": 3, "manager": 2, "sales": 1, "website_editor": 1}


# Role sets shared by request dependencies and the agency dashboard.
MANAGER_ROLES = ("owner", "manager")
OPERATIONS_ROLES = ("owner", "manager", "sales")
WEBSITE_ROLES = ("owner", "manager", "website_editor")


def agency_access_rows(db, user_id, *, business_id=None, agency_id=None):
    """Access a user inherits through agency grants. It exists only while the
    client's grant exists, the user belongs to the agency, and either the user is
    an agency admin or holds an assignment that fits within the grant."""
    return db.execute("""
        SELECT businesses.id AS business_id, businesses.name AS business_name,
               CASE WHEN member.role = 'admin' THEN grants.role ELSE assignment.role END AS role,
               grants.website_ids, agencies.id AS agency_id, agencies.name AS agency_name
        FROM agency_client_grants AS grants
        JOIN businesses ON businesses.id = grants.business_id
        JOIN agencies ON agencies.id = grants.agency_id
        JOIN agency_members AS member ON member.agency_id = grants.agency_id AND member.user_id = :user
        LEFT JOIN agency_client_assignments AS assignment
          ON assignment.agency_id = grants.agency_id AND assignment.business_id = grants.business_id
         AND assignment.user_id = member.user_id
        WHERE (:business IS NULL OR businesses.id = :business)
          AND (:agency IS NULL OR agencies.id = :agency)
          AND (member.role = 'admin'
               OR (assignment.role IS NOT NULL AND (grants.role = 'manager' OR assignment.role = grants.role)))
        ORDER BY businesses.name, businesses.id
    """, {"user": user_id, "business": business_id, "agency": agency_id}).fetchall()


def access_candidates(db, user_id, business_id=None):
    """Every route by which a user can reach a business: direct memberships and
    access inherited through agency grants."""
    direct = db.execute("""
        SELECT businesses.id AS business_id, businesses.name AS business_name,
               membership.role, membership.website_ids, NULL AS agency_id, NULL AS agency_name
        FROM business_memberships AS membership JOIN businesses ON businesses.id = membership.business_id
        WHERE membership.user_id = ? AND (? IS NULL OR businesses.id = ?)
    """, (user_id, business_id, business_id)).fetchall()
    return [*direct, *agency_access_rows(db, user_id, business_id=business_id)]


def merge_access(rows):
    """Combine access routes per business. The highest role wins. Sales and website
    editor are different permissions, so on a tie a direct membership is kept.
    Website editor scopes from equally ranked routes are combined."""
    merged = {}
    for row in sorted(rows, key=lambda row: (row["agency_id"] is not None, row["agency_id"] or 0)):
        website_ids = json.loads(row["website_ids"]) if row["website_ids"] is not None else None
        if row["role"] != "website_editor":
            website_ids = None
        current = merged.get(row["business_id"])
        if current is None or ROLE_RANK[row["role"]] > ROLE_RANK[current["role"]]:
            merged[row["business_id"]] = current = {
                "business_id": row["business_id"], "business_name": row["business_name"],
                "role": row["role"], "website_ids": website_ids, "agency_names": [],
                "access": "direct" if row["agency_id"] is None else "agency",
            }
        elif row["role"] == current["role"] == "website_editor":
            if current["website_ids"] is not None:
                current["website_ids"] = None if website_ids is None else sorted(set(current["website_ids"]) | set(website_ids))
        if row["agency_name"] is not None and row["agency_name"] not in current["agency_names"]:
            current["agency_names"].append(row["agency_name"])
    return merged


def workspace_account(db, identity, business_id=None):
    access = merge_access(access_candidates(db, identity.user_id, business_id))
    if not access:
        message = "You do not have access to this business" if business_id is not None else "This account has no active workspace access"
        raise HTTPException(status_code=403, detail=message)
    chosen = access.get(identity.home_business_id) if business_id is None else None
    chosen = chosen or access[min(access)]
    return Account(email=identity.email, is_platform_admin=identity.is_platform_admin, **chosen)


def require_account(
    identity: CurrentIdentity,
    business_id: Annotated[int | None, Header(alias="X-Business-Id", gt=0, le=2**63 - 1)] = None,
):
    with get_db() as db:
        return workspace_account(db, identity, business_id)


CurrentAccount = Annotated[Account, Depends(require_account)]


def require_manager(account: CurrentAccount):
    if account.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Owner or manager access required")
    return account


ManagerAccount = Annotated[Account, Depends(require_manager)]


def require_operations(account: CurrentAccount):
    if account.role not in OPERATIONS_ROLES:
        raise HTTPException(status_code=403, detail="Business operations access required")
    return account


def require_website_editing(account: CurrentAccount):
    if account.role not in WEBSITE_ROLES:
        raise HTTPException(status_code=403, detail="Website editing access required")
    return account


OperationsAccount = Annotated[Account, Depends(require_operations)]
WebsiteAccount = Annotated[Account, Depends(require_website_editing)]


def normalize_email(value):
    email = value.strip().casefold()
    if email.count("@") != 1 or not all(email.split("@")) or any(c.isspace() for c in email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


@router.get("/me", response_model=Account)
def me(account: CurrentAccount):
    return account


@router.post("/logout", status_code=204)
def logout(credentials: Bearer):
    if credentials:
        with get_db() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(credentials.credentials),))
    return Response(status_code=204)
