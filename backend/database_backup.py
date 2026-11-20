import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from database import DATABASE_PATH


def open_readonly(path: Path):
    if not path.is_file():
        raise ValueError(f"Database file not found: {path}")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def verify_database(path: Path):
    with closing(open_readonly(path)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("SQLite foreign-key check failed")
        if db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'businesses'").fetchone() is None:
            raise ValueError("The file does not contain a Vyapari business database")


def copy_database(source: Path, destination: Path):
    # SQLite's backup API includes committed changes still in the WAL.
    with closing(open_readonly(source)) as original:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            with closing(sqlite3.connect(destination)) as copy:
                original.backup(copy)
            verify_database(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def main():
    parser = argparse.ArgumentParser(description="Back up or verify a local Vyapari SQLite database.")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Copy the configured database to a new backup file.")
    backup.add_argument("destination", type=Path)
    restore = commands.add_parser("restore", help="Restore a verified backup to a new database file.")
    restore.add_argument("source", type=Path)
    restore.add_argument("destination", type=Path)
    verify = commands.add_parser("verify", help="Check a database or backup file.")
    verify.add_argument("source", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "backup":
            copy_database(DATABASE_PATH, args.destination)
            result = args.destination
        elif args.command == "restore":
            verify_database(args.source)
            copy_database(args.source, args.destination)
            result = args.destination
        else:
            verify_database(args.source)
            result = args.source
    except (OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, f"Database operation failed: {error}\n")
    print(f"Verified Vyapari database: {result.resolve()}")


if __name__ == "__main__":
    main()
