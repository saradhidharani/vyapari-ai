import argparse
import base64
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from database_backup import open_readonly
from migration_check import REQUIRED_COLUMNS, inspect_database


# Short-lived credentials are not migrated: users sign in again and request new codes.
EXCLUDED = ("sessions", "workspace_invitations", "auth_codes", "auth_rate_events")
TABLES = tuple(table for table in REQUIRED_COLUMNS if table not in EXCLUDED)
FORMAT_VERSION = 3  # 2: adds agency tables. 3: users.email_verified_at, auth tables excluded.


def encode_value(value):
    if isinstance(value, bytes):
        return {"$base64": base64.b64encode(value).decode("ascii")}
    return value


def export_bundle(source: Path, destination: Path):
    with closing(open_readonly(source)) as db:
        db.execute("BEGIN")
        findings = inspect_database(db)
        if not findings["ready"]:
            raise ValueError("Database failed preflight. Run migration_check check for details.")
        db.row_factory = sqlite3.Row
        sequences = {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
            sequences = {
                row["name"]: row["seq"] for row in db.execute("SELECT name, seq FROM sqlite_sequence")
                if row["name"] in TABLES
            }
        manifest = {
            "format_version": FORMAT_VERSION,
            "excluded_tables": list(EXCLUDED),
            "sequence_high_watermarks": sequences,
            "tables": {},
        }
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as output, ZipFile(output, "w", compression=ZIP_DEFLATED) as bundle:
                for table in TABLES:
                    path = f"tables/{table}.jsonl"
                    digest = hashlib.sha256()
                    count = 0
                    with bundle.open(path, "w", force_zip64=True) as entry:
                        for row in db.execute(f'SELECT * FROM "{table}"'):
                            record = {key: encode_value(row[key]) for key in row.keys()}
                            line = json.dumps(record, ensure_ascii=True, allow_nan=False).encode("utf-8") + b"\n"
                            entry.write(line)
                            digest.update(line)
                            count += 1
                    manifest["tables"][table] = {"rows": count, "sha256": digest.hexdigest()}
                bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
            verify_bundle(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return manifest


def verify_bundle(path: Path):
    with ZipFile(path) as bundle:
        expected = {"manifest.json", *(f"tables/{table}.jsonl" for table in TABLES)}
        names = bundle.namelist()
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError("Archive contains missing, duplicate, or unexpected files")
        manifest = json.loads(bundle.read("manifest.json"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("format_version") != FORMAT_VERSION
            or manifest.get("excluded_tables") != list(EXCLUDED)
            or not isinstance(manifest.get("tables"), dict)
            or set(manifest["tables"]) != set(TABLES)
        ):
            raise ValueError("Unsupported migration bundle manifest")
        sequences = manifest.get("sequence_high_watermarks")
        if not isinstance(sequences, dict) or any(
            table not in TABLES or type(value) is not int or value < 0
            for table, value in sequences.items()
        ):
            raise ValueError("Invalid sequence metadata")
        for table in TABLES:
            digest = hashlib.sha256()
            count = 0
            with bundle.open(f"tables/{table}.jsonl") as entry:
                for line in entry:
                    digest.update(line)
                    count += 1
            if manifest["tables"][table] != {"rows": count, "sha256": digest.hexdigest()}:
                raise ValueError(f"Row count or checksum mismatch: {table}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Export or verify a private Vyapari migration bundle.")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("source", type=Path)
    export.add_argument("destination", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        manifest = export_bundle(args.source, args.destination) if args.command == "export" else verify_bundle(args.bundle)
    except (OSError, BadZipFile, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Migration bundle failed: {error}\n")
    print(f"Verified migration bundle with {len(manifest['tables'])} tables.")


if __name__ == "__main__":
    main()
