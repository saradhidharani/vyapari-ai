import argparse
import base64
import hashlib
import os
import re
from itertools import islice
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from migration_export import TABLES, verify_bundle


def write_rehearsal_sql(bundle_path: Path, destination: Path, schema="vyapari_rehearsal"):
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
        raise ValueError("Use a schema name of up to 63 lowercase letters, digits, or underscores, starting with a letter")
    manifest = verify_bundle(bundle_path)
    target = f'"{schema}"'
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as output, ZipFile(bundle_path) as bundle:
            output.write(f"""\\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA {target};
REVOKE ALL ON SCHEMA {target} FROM PUBLIC;
CREATE TABLE {target}.table_manifest (
    table_name text PRIMARY KEY,
    expected_rows bigint NOT NULL,
    sha256 text NOT NULL,
    sequence_high_watermark bigint
);
CREATE TABLE {target}.source_rows (
    table_name text NOT NULL REFERENCES {target}.table_manifest(table_name),
    row_number bigint NOT NULL,
    payload bytea NOT NULL,
    PRIMARY KEY (table_name, row_number)
);
""")
            for table in TABLES:
                metadata = manifest["tables"][table]
                sequence = manifest["sequence_high_watermarks"].get(table)
                sequence_sql = str(sequence) if sequence is not None else "NULL"
                output.write(
                    f"INSERT INTO {target}.table_manifest VALUES "
                    f"('{table}', {metadata['rows']}, '{metadata['sha256']}', {sequence_sql});\n"
                )
                count = 0
                digest = hashlib.sha256()
                with bundle.open(f"tables/{table}.jsonl") as rows:
                    while batch := list(islice(rows, 100)):
                        values = []
                        for line in batch:
                            count += 1
                            digest.update(line)
                            payload = base64.b64encode(line).decode("ascii")
                            values.append(f"('{table}', {count}, decode('{payload}', 'base64'))")
                        output.write(f"INSERT INTO {target}.source_rows VALUES\n" + ",\n".join(values) + ";\n")
                if count != metadata["rows"] or digest.hexdigest() != metadata["sha256"]:
                    raise ValueError(f"Bundle changed while reading {table}")
            output.write(f"""
CREATE TEMP TABLE vyapari_row_check (
    table_name text NOT NULL,
    expected_rows bigint NOT NULL,
    loaded_rows bigint NOT NULL,
    CHECK (expected_rows = loaded_rows)
) ON COMMIT DROP;
INSERT INTO vyapari_row_check
SELECT m.table_name, m.expected_rows, COUNT(r.row_number)
FROM {target}.table_manifest AS m
LEFT JOIN {target}.source_rows AS r ON r.table_name = m.table_name
GROUP BY m.table_name, m.expected_rows;
SELECT table_name, expected_rows, loaded_rows FROM vyapari_row_check ORDER BY table_name;
COMMIT;
""")
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Generate a private PostgreSQL rehearsal script from a Vyapari bundle.")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--schema", default="vyapari_rehearsal")
    args = parser.parse_args()
    try:
        write_rehearsal_sql(args.bundle, args.destination, args.schema)
    except (OSError, BadZipFile, ValueError) as error:
        parser.exit(1, f"Rehearsal script generation failed: {error}\n")
    print(f"Generated rehearsal script: {args.destination.resolve()}")


if __name__ == "__main__":
    main()
