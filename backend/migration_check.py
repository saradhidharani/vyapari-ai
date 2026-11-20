import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from database_backup import open_readonly


# Column names used by tenancy checks and the current migration baseline.
REQUIRED_COLUMNS = {
    "businesses": {"id", "name"},
    "users": {"id", "business_id", "owns_home", "password_hash", "email_verified_at"},
    "sessions": {"token_hash", "user_id"},
    "business_memberships": {"business_id", "user_id", "role", "website_ids"},
    "platform_admins": {"user_id"},
    "products": {"id", "business_id", "stock", "restock_target"},
    "customers": {"id", "business_id"},
    "orders": {"id", "business_id", "customer_id", "source_inquiry_id", "source_website_id"},
    "order_items": {"order_id", "product_id"},
    "storefront_websites": {"id", "business_id", "product_ids", "archived_at", "snapshot"},
    "website_requests": {"id", "business_id", "website_id"},
    "website_inquiries": {"id", "business_id", "website_id", "customer_id"},
    "workspace_invitations": {"business_id", "token_hash"},
    "workspace_activity": {"business_id"},
    "assistant_history": {"business_id"},
    "inventory_movements": {"business_id", "product_id", "order_id"},
    "suppliers": {"id", "business_id"},
    "purchase_orders": {"id", "business_id", "supplier_id"},
    "purchase_items": {"purchase_id", "product_id"},
    "agencies": {"id", "name", "access_code"},
    "agency_members": {"agency_id", "user_id", "role"},
    "agency_client_grants": {"agency_id", "business_id", "role", "website_ids"},
    "agency_client_assignments": {"agency_id", "business_id", "user_id", "role"},
    "auth_codes": {"id", "purpose", "destination", "code_hash"},
    "auth_rate_events": {"key_hash", "created_at"},
}

# Some historical references deliberately survive deletion. Check for links
# to another business only when both records still exist.
TENANCY_LINKS = (
    ("orders", "customer_id", "customers"),
    ("orders", "source_inquiry_id", "website_inquiries"),
    ("orders", "source_website_id", "storefront_websites"),
    ("website_requests", "website_id", "storefront_websites"),
    ("website_inquiries", "website_id", "storefront_websites"),
    ("website_inquiries", "customer_id", "customers"),
    ("inventory_movements", "product_id", "products"),
    ("inventory_movements", "order_id", "orders"),
    ("purchase_orders", "supplier_id", "suppliers"),
)


def inspect_database(db):
    issues = []
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        issues.append("SQLite integrity check failed")
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        issues.append("SQLite foreign-key check failed")
    tables = {row[0] for row in db.execute("""
        SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
    """)}
    counts = {}
    schema_issues = []
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            schema_issues.append(f"Missing table: {table}")
            continue
        columns = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
        missing = required - columns
        if missing:
            schema_issues.append(f"{table}: missing columns {', '.join(sorted(missing))}")
        counts[table] = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    issues.extend(schema_issues)

    if not schema_issues:
        for child, key, parent in TENANCY_LINKS:
            count = db.execute(f"""
                SELECT COUNT(*) FROM {child} AS c JOIN {parent} AS p ON p.id = c.{key}
                WHERE c.business_id IS NOT p.business_id
            """).fetchone()[0]
            if count:
                issues.append(f"{child}.{key}: {count} cross-business links")
        for line_table, order_table, order_key in (
            ("order_items", "orders", "order_id"),
            ("purchase_items", "purchase_orders", "purchase_id"),
        ):
            count = db.execute(f"""
                SELECT COUNT(*) FROM {line_table} AS i
                JOIN {order_table} AS o ON o.id = i.{order_key}
                JOIN products AS p ON p.id = i.product_id
                WHERE o.business_id IS NOT p.business_id
            """).fetchone()[0]
            if count:
                issues.append(f"{line_table}.product_id: {count} cross-business links")
        for table, column, target in (
            ("storefront_websites", "product_ids", "products"),
            ("business_memberships", "website_ids", "storefront_websites"),
            ("agency_client_grants", "website_ids", "storefront_websites"),
        ):
            invalid = db.execute(f"""
                SELECT COUNT(*) FROM {table}
                WHERE {column} IS NOT NULL
                  AND NOT CASE WHEN json_valid({column}) THEN json_type({column}) = 'array' ELSE 0 END
            """).fetchone()[0]
            if invalid:
                issues.append(f"{table}.{column}: {invalid} invalid selections")
                continue
            invalid_ids = db.execute(f"""
                SELECT COUNT(*) FROM {table} AS t JOIN json_each(t.{column}) AS selection
                WHERE selection.type != 'integer' OR selection.value <= 0
            """).fetchone()[0]
            if invalid_ids:
                issues.append(f"{table}.{column}: {invalid_ids} invalid IDs")
            count = db.execute(f"""
                SELECT COUNT(*) FROM {table} AS t
                JOIN json_each(t.{column}) AS selection
                JOIN {target} AS s ON s.id = selection.value
                WHERE t.business_id IS NOT s.business_id
            """).fetchone()[0]
            if count:
                issues.append(f"{table}.{column}: {count} cross-business links")

    return {"ready": not issues, "table_counts": counts, "issues": issues}


def table_checksum(db, table):
    columns = db.execute(f'PRAGMA table_info("{table}")').fetchall()
    names = [row[1] for row in columns]
    key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]] or names
    order_by = ", ".join('"' + name.replace('"', '""') + '"' for name in key)
    digest = hashlib.sha256()
    digest.update(json.dumps(names).encode())
    for row in db.execute(f'SELECT * FROM "{table}" ORDER BY {order_by}'):
        values = [{"blob": value.hex()} if isinstance(value, bytes) else value for value in row]
        digest.update(json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode() + b"\n")
    return digest.digest()


def compare_databases(reference, rehearsal):
    source = inspect_database(reference)
    copy = inspect_database(rehearsal)
    different = []
    if source["ready"] and copy["ready"]:
        different = [table for table in REQUIRED_COLUMNS
                     if table_checksum(reference, table) != table_checksum(rehearsal, table)]
    return {
        "ready": source["ready"] and copy["ready"] and not different,
        "different_tables": different,
        "reference_issues": source["issues"],
        "rehearsal_issues": copy["issues"],
    }


def main():
    parser = argparse.ArgumentParser(description="Check a local Vyapari database before migration.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check")
    check.add_argument("source", type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("reference", type=Path)
    compare.add_argument("rehearsal", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            with closing(open_readonly(args.source)) as source:
                source.execute("BEGIN")
                result = inspect_database(source)
        else:
            with closing(open_readonly(args.reference)) as reference, closing(open_readonly(args.rehearsal)) as rehearsal:
                reference.execute("BEGIN")
                rehearsal.execute("BEGIN")
                result = compare_databases(reference, rehearsal)
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Migration check failed: {error}\n")
    print(json.dumps(result, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
