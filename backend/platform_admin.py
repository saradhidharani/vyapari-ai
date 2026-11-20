import argparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth import CurrentIdentity, initialize_accounts
from database import DATABASE_PATH, get_db


router = APIRouter(prefix="/api/platform", tags=["Platform Admin"])


class BusinessDirectoryEntry(BaseModel):
    id: int
    name: str
    owner_emails: list[str]
    member_count: int
    storefront_published: bool
    website_count: int
    published_website_count: int
    archived_website_count: int


def require_platform_admin(identity: CurrentIdentity):
    if not identity.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin access required")


@router.get("/businesses", response_model=list[BusinessDirectoryEntry])
def list_businesses(identity: CurrentIdentity):
    require_platform_admin(identity)
    with get_db() as db:
        businesses = {}
        rows = db.execute("""
            SELECT businesses.id, businesses.name, users.email, memberships.role,
                   COALESCE(sites.total, 0) AS website_count,
                   COALESCE(sites.published, 0) AS published_website_count,
                   COALESCE(sites.archived, 0) AS archived_website_count
            FROM businesses
            LEFT JOIN business_memberships AS memberships ON memberships.business_id = businesses.id
            LEFT JOIN users ON users.id = memberships.user_id
            LEFT JOIN (
                SELECT business_id, COUNT(*) AS total, COUNT(slug) AS published, COUNT(archived_at) AS archived
                FROM storefront_websites GROUP BY business_id
            ) AS sites ON sites.business_id = businesses.id
            ORDER BY businesses.name, businesses.id, users.email
        """)
        for row in rows:
            business = businesses.get(row["id"])
            if business is None:
                business = BusinessDirectoryEntry(
                    id=row["id"], name=row["name"], owner_emails=[], member_count=0,
                    storefront_published=row["published_website_count"] > 0,
                    website_count=row["website_count"],
                    published_website_count=row["published_website_count"],
                    archived_website_count=row["archived_website_count"],
                )
                businesses[business.id] = business
            if row["role"]:
                business.member_count += 1
            if row["role"] == "owner":
                business.owner_emails.append(row["email"])
    return list(businesses.values())


def main():
    parser = argparse.ArgumentParser(description="Manage platform admin access on this local installation.")
    # verify-email marks an address as verified without a code. Use it only for
    # fictional demo accounts or after confirming the person controls the address.
    parser.add_argument("action", choices=("grant", "revoke", "verify-email"))
    parser.add_argument("email")
    args = parser.parse_args()
    if not DATABASE_PATH.is_file():
        parser.error("Start Vyapari AI and register the account first.")
    from verification import initialize_verification

    initialize_accounts()
    initialize_verification()
    with get_db() as db:
        user = db.execute("SELECT id FROM users WHERE email = ?", (args.email.strip().casefold(),)).fetchone()
        if not user:
            parser.error("No registered account has this email.")
        if args.action == "verify-email":
            db.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, CAST(strftime('%s', 'now') AS INTEGER)) WHERE id = ?", (user["id"],))
            print("Email marked as verified.")
            return
        if args.action == "grant":
            db.execute("INSERT OR IGNORE INTO platform_admins (user_id) VALUES (?)", (user["id"],))
        else:
            db.execute("DELETE FROM platform_admins WHERE user_id = ?", (user["id"],))
    print("Platform admin access updated.")


if __name__ == "__main__":
    main()
