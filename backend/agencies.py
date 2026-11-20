"""Agency organizations and client-controlled agency access.

Ownership rules:
- An agency never holds the owner role. Only a direct workspace owner can grant,
  change, or revoke agency access to a business.
- When an agency creates a workspace for a new client, the workspace has no owner
  until the client accepts the owner invitation. During onboarding the agency has
  manager access through its grant and can reissue the owner invitation. It cannot
  withdraw, which would leave the workspace with nobody in charge.
- After the client accepts, the client is the owner and can revoke agency access at
  any time. The agency can no longer issue owner invitations, but may withdraw.
- Revoking a grant removes inherited access immediately. Direct workspace
  memberships are separate and are not changed.
"""
import json
import secrets
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from activity import record_activity
from auth import (
    MANAGER_ROLES, WEBSITE_ROLES, AssignableRole, CurrentAccount, CurrentIdentity, agency_access_rows, normalize_email,
)
from database import get_db
from invitations import CreatedInvitation, has_owner, issue_owner_invitation
from reports import DAY, IST, SalesPeriod, calculate_sales, sales_period
from storefront import visible_websites
from workspaces import require_owner


router = APIRouter(prefix="/api/agencies", tags=["Agencies"])
client_router = APIRouter(prefix="/api/workspaces/agencies", tags=["Workspaces"])
AgencyRole = Literal["admin", "staff"]
RecordId = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def initialize_agencies():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS agencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                access_code TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agency_members (
                agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
                PRIMARY KEY (agency_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS agency_members_user_id ON agency_members (user_id, agency_id);
            CREATE TABLE IF NOT EXISTS agency_client_grants (
                agency_id INTEGER NOT NULL REFERENCES agencies(id) ON DELETE CASCADE,
                business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('manager', 'sales', 'website_editor')),
                website_ids TEXT,
                created_client INTEGER NOT NULL DEFAULT 0 CHECK(created_client IN (0, 1)),
                granted_by TEXT NOT NULL,
                granted_at TEXT NOT NULL,
                PRIMARY KEY (agency_id, business_id)
            );
            CREATE INDEX IF NOT EXISTS agency_client_grants_business_id
            ON agency_client_grants (business_id, agency_id);
            CREATE TABLE IF NOT EXISTS agency_client_assignments (
                agency_id INTEGER NOT NULL,
                business_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('manager', 'sales', 'website_editor')),
                assigned_by TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (agency_id, business_id, user_id),
                FOREIGN KEY (agency_id, business_id)
                    REFERENCES agency_client_grants (agency_id, business_id) ON DELETE CASCADE,
                FOREIGN KEY (agency_id, user_id)
                    REFERENCES agency_members (agency_id, user_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS agency_client_assignments_user_id
            ON agency_client_assignments (user_id, business_id);
        """)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def format_code(code):
    return "-".join(code[index:index + 4] for index in range(0, len(code), 4))


def normalize_code(value):
    return "".join(character for character in value.upper() if character.isalnum())


def role_fits_grant(role, grant_role):
    """Managers may be given any narrower role. Other grants allow only the same role."""
    return grant_role == "manager" or role == grant_role


def website_scope(db, business_id, role, website_ids):
    """Website editors can be limited to specific sites. Other roles cover the business."""
    if role != "website_editor" or website_ids is None:
        return None
    ids = sorted(set(website_ids))
    available = {row["id"] for row in db.execute(
        "SELECT id FROM storefront_websites WHERE business_id = ?", (business_id,)
    )}
    if not available >= set(ids):
        raise HTTPException(status_code=422, detail="Choose websites from this business")
    return ids


# ---------------------------------------------------------------------------
# Agency side
# ---------------------------------------------------------------------------

class AgencyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class AgencySummary(BaseModel):
    id: int
    name: str
    role: AgencyRole
    access_code: str | None = None


class AgencyMemberRole(BaseModel):
    role: AgencyRole = "staff"


class AgencyMemberGrant(AgencyMemberRole):
    email: str = Field(min_length=3, max_length=254)


class AgencyMember(BaseModel):
    id: int
    email: str
    role: AgencyRole


class AssignmentRole(BaseModel):
    role: AssignableRole


class Assignment(BaseModel):
    user_id: int
    email: str
    role: AssignableRole


class AgencyClient(BaseModel):
    business_id: int
    business_name: str
    grant_role: AssignableRole
    website_ids: list[int] | None
    created_by_agency: bool
    owner_status: Literal["owner", "invitation_pending", "no_owner"]
    pending_owner_email: str | None = None
    your_role: AssignableRole
    assignments: list[Assignment] | None = None


class ClientCreate(BaseModel):
    business_name: str = Field(min_length=1, max_length=100)
    owner_email: str = Field(min_length=3, max_length=254)


class OwnerInvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ClientOnboarding(BaseModel):
    business_id: int
    business_name: str
    invitation: CreatedInvitation


def agency_membership(db, agency_id, identity, admin=False):
    if not 1 <= agency_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Agency not found")
    row = db.execute("""
        SELECT agencies.id, agencies.name, agencies.access_code, member.role
        FROM agency_members AS member JOIN agencies ON agencies.id = member.agency_id
        WHERE member.agency_id = ? AND member.user_id = ?
    """, (agency_id, identity.user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Agency not found")
    if admin and row["role"] != "admin":
        raise HTTPException(status_code=403, detail="Agency admin access required")
    return row


def agency_summary(row):
    return AgencySummary(
        id=row["id"], name=row["name"], role=row["role"],
        access_code=format_code(row["access_code"]) if row["role"] == "admin" else None,
    )


def agency_grant(db, agency_id, business_id):
    if not 1 <= business_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Client business not found")
    row = db.execute("""
        SELECT grants.*, businesses.name AS business_name
        FROM agency_client_grants AS grants JOIN businesses ON businesses.id = grants.business_id
        WHERE grants.agency_id = ? AND grants.business_id = ?
    """, (agency_id, business_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Client business not found")
    return row


def agency_admin_count(db, agency_id):
    return db.execute(
        "SELECT COUNT(*) FROM agency_members WHERE agency_id = ? AND role = 'admin'", (agency_id,)
    ).fetchone()[0]


@router.get("", response_model=list[AgencySummary])
def list_agencies(identity: CurrentIdentity):
    with get_db() as db:
        rows = db.execute("""
            SELECT agencies.id, agencies.name, agencies.access_code, member.role
            FROM agency_members AS member JOIN agencies ON agencies.id = member.agency_id
            WHERE member.user_id = ? ORDER BY agencies.name, agencies.id
        """, (identity.user_id,)).fetchall()
    return [agency_summary(row) for row in rows]


@router.post("", response_model=AgencySummary, status_code=201)
def create_agency(body: AgencyCreate, identity: CurrentIdentity):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter an agency name")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
    with get_db() as db:
        agency_id = db.execute(
            "INSERT INTO agencies (name, access_code, created_at) VALUES (?, ?, ?)", (name, code, now_iso())
        ).lastrowid
        db.execute(
            "INSERT INTO agency_members (agency_id, user_id, role) VALUES (?, ?, 'admin')",
            (agency_id, identity.user_id),
        )
    return AgencySummary(id=agency_id, name=name, role="admin", access_code=format_code(code))


@router.get("/{agency_id}", response_model=AgencySummary)
def get_agency(agency_id: int, identity: CurrentIdentity):
    with get_db() as db:
        return agency_summary(agency_membership(db, agency_id, identity))


@router.get("/{agency_id}/members", response_model=list[AgencyMember])
def list_agency_members(agency_id: int, identity: CurrentIdentity):
    with get_db() as db:
        agency_membership(db, agency_id, identity, admin=True)
        rows = db.execute("""
            SELECT users.id, users.email, member.role
            FROM agency_members AS member JOIN users ON users.id = member.user_id
            WHERE member.agency_id = ? ORDER BY users.email
        """, (agency_id,)).fetchall()
    return [dict(row) for row in rows]


@router.post("/{agency_id}/members", response_model=AgencyMember, status_code=201)
def add_agency_member(agency_id: int, body: AgencyMemberGrant, identity: CurrentIdentity):
    email = normalize_email(body.email)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency_membership(db, agency_id, identity, admin=True)
        user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="Ask this person to create a Vyapari account first")
        result = db.execute("""
            INSERT INTO agency_members (agency_id, user_id, role) VALUES (?, ?, ?)
            ON CONFLICT (agency_id, user_id) DO NOTHING
        """, (agency_id, user["id"], body.role))
        if result.rowcount == 0:
            raise HTTPException(status_code=409, detail="This person is already in the agency")
    return AgencyMember(id=user["id"], email=email, role=body.role)


def agency_member_row(db, agency_id, user_id):
    if not 1 <= user_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Agency member not found")
    row = db.execute("""
        SELECT users.id, users.email, member.role
        FROM agency_members AS member JOIN users ON users.id = member.user_id
        WHERE member.agency_id = ? AND member.user_id = ?
    """, (agency_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Agency member not found")
    return row


@router.put("/{agency_id}/members/{user_id}", response_model=AgencyMember)
def update_agency_member(agency_id: int, user_id: int, body: AgencyMemberRole, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency_membership(db, agency_id, identity, admin=True)
        member = agency_member_row(db, agency_id, user_id)
        if member["role"] == "admin" and body.role != "admin" and agency_admin_count(db, agency_id) == 1:
            raise HTTPException(status_code=409, detail="An agency needs at least one admin")
        db.execute(
            "UPDATE agency_members SET role = ? WHERE agency_id = ? AND user_id = ?", (body.role, agency_id, user_id)
        )
    return AgencyMember(id=user_id, email=member["email"], role=body.role)


@router.delete("/{agency_id}/members/{user_id}", status_code=204)
def remove_agency_member(agency_id: int, user_id: int, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_membership(db, agency_id, identity, admin=True)
        member = agency_member_row(db, agency_id, user_id)
        if member["role"] == "admin" and agency_admin_count(db, agency_id) == 1:
            raise HTTPException(status_code=409, detail="An agency needs at least one admin")
        assigned = db.execute(
            "SELECT business_id FROM agency_client_assignments WHERE agency_id = ? AND user_id = ?",
            (agency_id, user_id),
        ).fetchall()
        # Assignments are removed by the foreign key cascade.
        db.execute("DELETE FROM agency_members WHERE agency_id = ? AND user_id = ?", (agency_id, user_id))
        for row in assigned:
            record_activity(db, row["business_id"], identity.email, "Agency staff unassigned",
                            f"{member['email']} · {agency['name']}")
    return Response(status_code=204)


@router.get("/{agency_id}/clients", response_model=list[AgencyClient])
def list_agency_clients(agency_id: int, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN")
        agency = agency_membership(db, agency_id, identity)
        admin = agency["role"] == "admin"
        rows = db.execute("""
            SELECT grants.*, businesses.name AS business_name, assignment.role AS assigned_role,
                   EXISTS (SELECT 1 FROM business_memberships AS owner
                           WHERE owner.business_id = grants.business_id AND owner.role = 'owner') AS has_owner,
                   (SELECT email FROM workspace_invitations AS invite
                    WHERE invite.business_id = grants.business_id AND invite.role = 'owner'
                      AND invite.accepted_at IS NULL AND invite.revoked_at IS NULL
                      AND invite.expires_at > CAST(strftime('%s', 'now') AS INTEGER)
                    ORDER BY invite.id DESC LIMIT 1) AS pending_owner_email
            FROM agency_client_grants AS grants
            JOIN businesses ON businesses.id = grants.business_id
            LEFT JOIN agency_client_assignments AS assignment
              ON assignment.agency_id = grants.agency_id AND assignment.business_id = grants.business_id
             AND assignment.user_id = ?
            WHERE grants.agency_id = ?
            ORDER BY businesses.name, businesses.id
        """, (identity.user_id, agency_id)).fetchall()
        clients = []
        for row in rows:
            if admin:
                your_role = row["role"]
            elif row["assigned_role"] and role_fits_grant(row["assigned_role"], row["role"]):
                your_role = row["assigned_role"]
            else:
                continue
            assignments = None
            if admin:
                assignments = [Assignment(**dict(item)) for item in db.execute("""
                    SELECT users.id AS user_id, users.email, assignment.role
                    FROM agency_client_assignments AS assignment JOIN users ON users.id = assignment.user_id
                    WHERE assignment.agency_id = ? AND assignment.business_id = ? ORDER BY users.email
                """, (agency_id, row["business_id"]))]
            owner_status = "owner" if row["has_owner"] else (
                "invitation_pending" if row["pending_owner_email"] else "no_owner")
            clients.append(AgencyClient(
                business_id=row["business_id"], business_name=row["business_name"], grant_role=row["role"],
                website_ids=json.loads(row["website_ids"]) if row["website_ids"] is not None else None,
                created_by_agency=bool(row["created_client"]), owner_status=owner_status,
                pending_owner_email=row["pending_owner_email"] if admin and not row["has_owner"] else None,
                your_role=your_role, assignments=assignments,
            ))
    return clients


class SalesTotals(BaseModel):
    payments_paise: int = 0
    refunds_paise: int = 0
    net_paise: int = 0
    payment_count: int = 0
    refund_count: int = 0


class DashboardClient(BaseModel):
    business_id: int
    business_name: str
    role: AssignableRole
    # None when the role has no website access (sales staff).
    website_count: int | None
    report_access: bool
    sales: SalesTotals | None


class AgencyDashboard(BaseModel):
    agency_id: int
    agency_name: str
    agency_role: AgencyRole
    period: SalesPeriod
    start_date: date
    end_date: date
    clients: list[DashboardClient]
    combined: SalesTotals
    reported_clients: int
    clients_without_report_access: int


@router.get("/{agency_id}/dashboard", response_model=AgencyDashboard)
def agency_dashboard(agency_id: int, identity: CurrentIdentity, period: SalesPeriod = "last 7 days"):
    """Clients the user reaches through this agency, with sales where permitted.

    Only access inherited through this agency counts. Direct memberships are left
    out even for the same business, so the dashboard reflects what the agency
    relationship allows. Access and report permission are checked per client on
    every request, so revoked or unassigned clients never appear or contribute."""
    with get_db() as db:
        db.execute("BEGIN")  # One consistent snapshot for the list and the totals.
        agency = agency_membership(db, agency_id, identity)
        today = datetime.now(IST).date()
        combined = SalesTotals()
        start_date, after_end = sales_period(period, today)
        clients, reported = [], 0
        for row in agency_access_rows(db, identity.user_id, agency_id=agency_id):
            role = row["role"]
            website_ids = json.loads(row["website_ids"]) if role == "website_editor" and row["website_ids"] is not None else None
            website_count = None
            if role in WEBSITE_ROLES:
                website_count = len(visible_websites(db, row["business_id"], role, website_ids))
            sales = None
            if role in MANAGER_ROLES:
                report = calculate_sales(db, row["business_id"], period, today=today)
                sales = SalesTotals(**report.model_dump(include=set(SalesTotals.model_fields)))
                for field in SalesTotals.model_fields:
                    setattr(combined, field, getattr(combined, field) + getattr(sales, field))
                reported += 1
            clients.append(DashboardClient(
                business_id=row["business_id"], business_name=row["business_name"], role=role,
                website_count=website_count, report_access=sales is not None, sales=sales,
            ))
    return AgencyDashboard(
        agency_id=agency["id"], agency_name=agency["name"], agency_role=agency["role"], period=period,
        start_date=start_date, end_date=after_end - DAY, clients=clients, combined=combined,
        reported_clients=reported, clients_without_report_access=len(clients) - reported,
    )


@router.put("/{agency_id}/clients/{business_id}/assignments/{user_id}", response_model=Assignment)
def assign_agency_staff(agency_id: int, business_id: int, user_id: int, body: AssignmentRole, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_membership(db, agency_id, identity, admin=True)
        grant = agency_grant(db, agency_id, business_id)
        member = agency_member_row(db, agency_id, user_id)
        if member["role"] != "staff":
            raise HTTPException(status_code=422, detail="Agency admins already have the client's granted access")
        if not role_fits_grant(body.role, grant["role"]):
            raise HTTPException(status_code=422, detail="Choose a role within the access this client granted")
        previous = db.execute("""
            SELECT role FROM agency_client_assignments WHERE agency_id = ? AND business_id = ? AND user_id = ?
        """, (agency_id, business_id, user_id)).fetchone()
        if previous is None or previous["role"] != body.role:
            db.execute("""
                INSERT INTO agency_client_assignments (agency_id, business_id, user_id, role, assigned_by, assigned_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (agency_id, business_id, user_id)
                DO UPDATE SET role = excluded.role, assigned_by = excluded.assigned_by, assigned_at = excluded.assigned_at
            """, (agency_id, business_id, user_id, body.role, identity.email, now_iso()))
            record_activity(db, business_id, identity.email, "Agency staff assigned",
                            f"{member['email']} · {agency['name']} · {body.role}")
    return Assignment(user_id=user_id, email=member["email"], role=body.role)


@router.delete("/{agency_id}/clients/{business_id}/assignments/{user_id}", status_code=204)
def unassign_agency_staff(agency_id: int, business_id: int, user_id: int, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_membership(db, agency_id, identity, admin=True)
        agency_grant(db, agency_id, business_id)
        member = agency_member_row(db, agency_id, user_id)
        result = db.execute("""
            DELETE FROM agency_client_assignments WHERE agency_id = ? AND business_id = ? AND user_id = ?
        """, (agency_id, business_id, user_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Assignment not found")
        record_activity(db, business_id, identity.email, "Agency staff unassigned",
                        f"{member['email']} · {agency['name']}")
    return Response(status_code=204)


@router.post("/{agency_id}/clients", response_model=ClientOnboarding, status_code=201)
def create_client_workspace(agency_id: int, body: ClientCreate, identity: CurrentIdentity):
    """Create a workspace for a new client. The agency gets manager access and the
    client becomes the owner by accepting the returned invitation."""
    name = body.business_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter a business name")
    email = normalize_email(body.owner_email)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_membership(db, agency_id, identity, admin=True)
        business_id = db.execute("INSERT INTO businesses (name) VALUES (?)", (name,)).lastrowid
        db.execute("""
            INSERT INTO agency_client_grants (agency_id, business_id, role, created_client, granted_by, granted_at)
            VALUES (?, ?, 'manager', 1, ?, ?)
        """, (agency_id, business_id, identity.email, now_iso()))
        record_activity(db, business_id, identity.email, "Workspace created by agency",
                        f"{agency['name']} · manager access until the owner changes it")
        invitation = issue_owner_invitation(db, business_id, email, identity.email)
    return ClientOnboarding(business_id=business_id, business_name=name, invitation=invitation)


@router.post("/{agency_id}/clients/{business_id}/owner-invitation", response_model=CreatedInvitation, status_code=201)
def reissue_owner_invitation(agency_id: int, business_id: int, body: OwnerInvitationRequest, identity: CurrentIdentity):
    email = normalize_email(body.email)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency_membership(db, agency_id, identity, admin=True)
        grant = agency_grant(db, agency_id, business_id)
        if not grant["created_client"]:
            raise HTTPException(status_code=403, detail="Only the agency that created this workspace can invite its owner")
        return issue_owner_invitation(db, business_id, email, identity.email)


@router.delete("/{agency_id}/clients/{business_id}", status_code=204)
def withdraw_from_client(agency_id: int, business_id: int, identity: CurrentIdentity):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_membership(db, agency_id, identity, admin=True)
        agency_grant(db, agency_id, business_id)
        if not has_owner(db, business_id):
            raise HTTPException(status_code=409, detail="This workspace has no owner yet. Invite the client owner before withdrawing.")
        db.execute("DELETE FROM agency_client_grants WHERE agency_id = ? AND business_id = ?", (agency_id, business_id))
        record_activity(db, business_id, identity.email, "Agency withdrew access", agency["name"])
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Client side: owners control agency access to their business
# ---------------------------------------------------------------------------

class AgencyCode(BaseModel):
    access_code: str = Field(min_length=4, max_length=40)


class AgencyPreview(BaseModel):
    name: str
    already_granted: bool


class AgencyGrantUpdate(BaseModel):
    role: AssignableRole = "manager"
    website_ids: list[RecordId] | None = None


class AgencyGrantCreate(AgencyGrantUpdate, AgencyCode):
    pass


class AgencyPerson(BaseModel):
    email: str
    agency_role: AgencyRole
    role: AssignableRole


class AgencyGrant(BaseModel):
    agency_id: int
    agency_name: str
    role: AssignableRole
    website_ids: list[int] | None
    created_client: bool
    granted_by: str
    granted_at: str
    people: list[AgencyPerson]


def agency_by_code(db, value):
    code = normalize_code(value)
    row = db.execute("SELECT id, name FROM agencies WHERE access_code = ?", (code,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="No agency matches this access code")
    return row


def grant_details(db, business_id, agency_id):
    grant = db.execute("""
        SELECT grants.*, agencies.name AS agency_name
        FROM agency_client_grants AS grants JOIN agencies ON agencies.id = grants.agency_id
        WHERE grants.business_id = ? AND grants.agency_id = ?
    """, (business_id, agency_id)).fetchone()
    if grant is None:
        raise HTTPException(status_code=404, detail="Agency access not found")
    people = []
    for row in db.execute("""
        SELECT users.email, member.role AS agency_role, assignment.role AS assigned_role
        FROM agency_members AS member JOIN users ON users.id = member.user_id
        LEFT JOIN agency_client_assignments AS assignment
          ON assignment.agency_id = member.agency_id AND assignment.business_id = ? AND assignment.user_id = member.user_id
        WHERE member.agency_id = ? ORDER BY users.email
    """, (business_id, agency_id)):
        if row["agency_role"] == "admin":
            people.append(AgencyPerson(email=row["email"], agency_role="admin", role=grant["role"]))
        elif row["assigned_role"] and role_fits_grant(row["assigned_role"], grant["role"]):
            people.append(AgencyPerson(email=row["email"], agency_role="staff", role=row["assigned_role"]))
    return AgencyGrant(
        agency_id=grant["agency_id"], agency_name=grant["agency_name"], role=grant["role"],
        website_ids=json.loads(grant["website_ids"]) if grant["website_ids"] is not None else None,
        created_client=bool(grant["created_client"]), granted_by=grant["granted_by"],
        granted_at=grant["granted_at"], people=people,
    )


def describe_grant(role, website_ids):
    if role != "website_editor":
        return role
    return f"{role} · " + ("all websites" if website_ids is None else f"{len(website_ids)} websites")


@client_router.get("", response_model=list[AgencyGrant])
def list_agency_grants(account: CurrentAccount):
    require_owner(account)
    with get_db() as db:
        db.execute("BEGIN")
        ids = [row["agency_id"] for row in db.execute(
            "SELECT agency_id FROM agency_client_grants WHERE business_id = ? ORDER BY granted_at", (account.business_id,)
        )]
        return [grant_details(db, account.business_id, agency_id) for agency_id in ids]


@client_router.post("/preview", response_model=AgencyPreview)
def preview_agency(body: AgencyCode, account: CurrentAccount):
    require_owner(account)
    with get_db() as db:
        agency = agency_by_code(db, body.access_code)
        exists = db.execute(
            "SELECT 1 FROM agency_client_grants WHERE agency_id = ? AND business_id = ?",
            (agency["id"], account.business_id),
        ).fetchone()
    return AgencyPreview(name=agency["name"], already_granted=exists is not None)


@client_router.post("", response_model=AgencyGrant, status_code=201)
def grant_agency_access(body: AgencyGrantCreate, account: CurrentAccount):
    require_owner(account)
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        agency = agency_by_code(db, body.access_code)
        scope = website_scope(db, account.business_id, body.role, body.website_ids)
        result = db.execute("""
            INSERT INTO agency_client_grants (agency_id, business_id, role, website_ids, granted_by, granted_at)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (agency_id, business_id) DO NOTHING
        """, (agency["id"], account.business_id, body.role,
              json.dumps(scope) if scope is not None else None, account.email, now_iso()))
        if result.rowcount == 0:
            raise HTTPException(status_code=409, detail="This agency already has access")
        record_activity(db, account.business_id, account.email, "Agency access granted",
                        f"{agency['name']} · {describe_grant(body.role, scope)}")
        return grant_details(db, account.business_id, agency["id"])


@client_router.put("/{agency_id}", response_model=AgencyGrant)
def update_agency_access(agency_id: int, body: AgencyGrantUpdate, account: CurrentAccount):
    require_owner(account)
    if not 1 <= agency_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Agency access not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        current = grant_details(db, account.business_id, agency_id)
        scope = website_scope(db, account.business_id, body.role, body.website_ids)
        db.execute("""
            UPDATE agency_client_grants SET role = ?, website_ids = ? WHERE agency_id = ? AND business_id = ?
        """, (body.role, json.dumps(scope) if scope is not None else None, agency_id, account.business_id))
        if body.role != "manager":
            # Keep staff assignments within the narrower grant: managers are reduced to
            # the granted role and other roles that no longer fit are removed.
            db.execute("""
                UPDATE agency_client_assignments SET role = ?
                WHERE agency_id = ? AND business_id = ? AND role = 'manager'
            """, (body.role, agency_id, account.business_id))
            db.execute("""
                DELETE FROM agency_client_assignments WHERE agency_id = ? AND business_id = ? AND role != ?
            """, (agency_id, account.business_id, body.role))
        if (current.role, current.website_ids) != (body.role, scope):
            record_activity(db, account.business_id, account.email, "Agency access changed",
                            f"{current.agency_name} · {describe_grant(body.role, scope)}")
        return grant_details(db, account.business_id, agency_id)


@client_router.delete("/{agency_id}", status_code=204)
def revoke_agency_access(agency_id: int, account: CurrentAccount):
    require_owner(account)
    if not 1 <= agency_id <= 2**63 - 1:
        raise HTTPException(status_code=404, detail="Agency access not found")
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")
        grant = grant_details(db, account.business_id, agency_id)
        # Staff assignments for this client are removed by the foreign key cascade.
        # Direct workspace memberships are separate and remain unchanged.
        db.execute("DELETE FROM agency_client_grants WHERE agency_id = ? AND business_id = ?",
                   (agency_id, account.business_id))
        record_activity(db, account.business_id, account.email, "Agency access revoked", grant.agency_name)
    return Response(status_code=204)
