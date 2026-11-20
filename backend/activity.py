from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from auth import CurrentAccount
from database import get_db


router = APIRouter(prefix="/api/workspaces/activity", tags=["Workspaces"])
PAGE_SIZE = 50


class ActivityEvent(BaseModel):
    id: int
    actor: str
    action: str
    details: str
    created_at: str


class ActivityPage(BaseModel):
    events: list[ActivityEvent]
    older_before: int | None


def initialize_activity():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS workspace_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id INTEGER NOT NULL REFERENCES businesses(id),
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS workspace_activity_business_id
            ON workspace_activity (business_id, id DESC)
        """)


def record_activity(db, business_id, actor, action, details):
    db.execute("""
        INSERT INTO workspace_activity (business_id, actor, action, details, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (business_id, actor, action, details, datetime.now(timezone.utc).isoformat()))


@router.get("", response_model=ActivityPage)
def list_activity(account: CurrentAccount, before: Annotated[int | None, Query(gt=0, le=2**63 - 1)] = None):
    if account.role != "owner":
        raise HTTPException(status_code=403, detail="Only a business owner can view workspace activity")
    with get_db() as db:
        rows = db.execute("""
            SELECT id, actor, action, details, created_at FROM workspace_activity
            WHERE business_id = ? AND (? IS NULL OR id < ?)
            ORDER BY id DESC LIMIT ?
        """, (account.business_id, before, before, PAGE_SIZE + 1)).fetchall()
    page = rows[:PAGE_SIZE]
    return ActivityPage(
        events=[ActivityEvent(**dict(row)) for row in page],
        older_before=page[-1]["id"] if len(rows) > PAGE_SIZE else None,
    )
