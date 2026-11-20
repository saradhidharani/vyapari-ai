import argparse
import os
import re
from contextlib import closing
from pathlib import Path
from zipfile import BadZipFile

from database_backup import open_readonly
from migration_check import inspect_database
from migration_export import TABLES, verify_bundle


POSTGRES_TYPES = {"INTEGER": "bigint", "REAL": "double precision", "TEXT": "text", "BLOB": "bytea"}
PARTIAL_INDEX_PREDICATES = {
    ("website_requests", "website_requests_pending_label"): "status = 'pending'",
    ("orders", "orders_source_inquiry"): "source_inquiry_id IS NOT NULL",
}


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def literal(value):
    return "'" + value.replace("'", "''") + "'"


CHECK_COMPARISON = re.compile(r"([a-z_][a-z0-9_]*) (>=|>|!=) (-?[0-9]+)")
CHECK_MEMBERSHIP = re.compile(r"([a-z_][a-z0-9_]*) IN \(((?:'[a-z_]+'|-?[0-9]+)(?:, (?:'[a-z_]+'|-?[0-9]+))*)\)")


CHECK_KEYWORD = re.compile(r"\bCHECK\s*\(", re.IGNORECASE)


def sqlite_checks(table_sql):
    """Yield the body of each CHECK(...) clause in a SQLite CREATE TABLE statement."""
    position, length = 0, len(table_sql)
    while position < length:
        char = table_sql[position]
        if char in "'\"`[":
            # Skip quoted literals and identifiers so their contents are never parsed.
            closing_char = "]" if char == "[" else char
            position = table_sql.index(closing_char, position + 1) + 1
            continue
        match = CHECK_KEYWORD.match(table_sql, position)
        if match and (position == 0 or not (table_sql[position - 1].isalnum() or table_sql[position - 1] == "_")):
            start = cursor = match.end()
            depth = 1
            while depth:
                if cursor >= length:
                    raise ValueError("Unbalanced SQLite CHECK constraint")
                if table_sql[cursor] == "'":
                    cursor = table_sql.index("'", cursor + 1)
                elif table_sql[cursor] == "(":
                    depth += 1
                elif table_sql[cursor] == ")":
                    depth -= 1
                cursor += 1
            yield table_sql[start:cursor - 1]
            position = cursor
            continue
        position += 1


def build_checks(db, table, columns):
    """Translate SQLite CHECK constraints into PostgreSQL table constraints.

    Only simple column comparisons and IN lists are accepted. Anything else fails
    script generation so new constraints are reviewed before migration."""
    table_sql, = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    constraints, names = [], set()
    for body in sqlite_checks(table_sql):
        # Normalize whitespace around parentheses and commas before matching.
        expression = " ".join(body.split())
        expression = re.sub(r"\s*\)", ")", re.sub(r"\(\s*", "(", expression))
        expression = re.sub(r"\s*,\s*", ", ", expression)
        expression = re.sub(r"\s+IN\s*\(", " IN (", expression, flags=re.IGNORECASE)
        comparison = CHECK_COMPARISON.fullmatch(expression)
        membership = CHECK_MEMBERSHIP.fullmatch(expression)
        if comparison:
            column, operator, value = comparison.groups()
            condition = f"{identifier(column)} {operator} {value}"
        elif membership:
            column, values = membership.groups()
            condition = f"{identifier(column)} IN ({values})"
        else:
            raise ValueError(f"Unsupported SQLite CHECK constraint on {table}")
        if column not in columns:
            raise ValueError(f"SQLite CHECK constraint on {table} references an unknown column")
        name = f"{table}_{column}_check"
        if name in names:
            raise ValueError(f"Multiple SQLite CHECK constraints on {table}.{column}")
        names.add(name)
        constraints.append(f"CONSTRAINT {identifier(name)} CHECK ({condition})")
    return constraints


def column_default(table, column, value):
    if re.fullmatch(r"[-+]?[0-9]+|'(?:[^'\r\n]|'')*'|NULL", value, re.IGNORECASE):
        return value
    raise ValueError(f"Unsupported SQLite default on {table}.{column}")


def build_indexes(db, table, qualified):
    for _, name, unique, origin, partial in db.execute(f"PRAGMA index_list({identifier(table)})"):
        if origin == "pk":
            continue
        keys = []
        for _, position, column, descending, collation, is_key in db.execute(
            f"PRAGMA index_xinfo({identifier(name)})"
        ):
            if not is_key:
                continue
            if position < 0 or collation not in ("BINARY", "NOCASE"):
                raise ValueError(f"Unsupported SQLite index key on {table}.{name}")
            field = identifier(column)
            if collation == "NOCASE":
                # SQLite NOCASE folds only ASCII letters.
                field = (
                    f"(pg_catalog.translate({field}, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                    "'abcdefghijklmnopqrstuvwxyz')) COLLATE pg_catalog.\"C\""
                )
            keys.append(f"{field} DESC NULLS LAST" if descending else f"{field} ASC NULLS FIRST")
        where = ""
        if partial:
            source_sql, = db.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
            ).fetchone()
            predicate = re.split(r"\bWHERE\b", source_sql, maxsplit=1, flags=re.IGNORECASE)[-1]
            expected = PARTIAL_INDEX_PREDICATES.get((table, name))
            if " ".join(predicate.split()) != expected:
                raise ValueError(f"Unsupported SQLite partial index on {table}.{name}")
            where = f" WHERE {expected}"
        unique_sql = "UNIQUE " if unique else ""
        yield f"CREATE {unique_sql}INDEX {identifier(name)} ON {qualified} ({', '.join(keys)}){where};"


def build_sql(db, manifest, staging, target):
    statements = [
        r"\set ON_ERROR_STOP on",
        "BEGIN;",
        "SET LOCAL standard_conforming_strings = on;",
        f"LOCK TABLE {staging}.table_manifest, {staging}.source_rows IN SHARE MODE;",
        f"CREATE SCHEMA {target};",
        f"REVOKE ALL ON SCHEMA {target} FROM PUBLIC;",
        """CREATE TEMP TABLE vyapari_typed_check (
    table_name text PRIMARY KEY,
    expected_rows bigint NOT NULL,
    loaded_rows bigint NOT NULL CHECK (loaded_rows = expected_rows),
    manifest_matches boolean NOT NULL CHECK (manifest_matches)
) ON COMMIT DROP;""",
    ]
    indexes, foreign_keys = [], []
    check_count = 0
    for table in TABLES:
        name = identifier(table)
        qualified = f"{target}.{name}"
        columns = list(db.execute(f"PRAGMA table_info({name})"))
        primary = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        identity = primary == ["id"] and any(row[1:3] == ("id", "INTEGER") for row in columns)
        definitions, names, values, present = [], [], [], []
        for _, column, declared_type, required, default, key_order in columns:
            pg_type = POSTGRES_TYPES.get(declared_type.upper())
            if pg_type is None:
                raise ValueError(f"Unsupported SQLite type {declared_type!r} on {table}.{column}")
            field = identifier(column)
            key = literal(column)
            definition = f"{field} {pg_type}"
            if column == "id" and identity:
                definition += " GENERATED BY DEFAULT AS IDENTITY"
            if default is not None:
                definition += f" DEFAULT {column_default(table, column, default)}"
            if required or key_order:
                definition += " NOT NULL"
            definitions.append(definition)
            names.append(field)
            present.append(f"record -> {key} IS NOT NULL")
            if pg_type == "bytea":
                values.append(f"decode(record -> {key} ->> '$base64', 'base64')")
            else:
                values.append(f"(record ->> {key})::{pg_type}")
        if primary:
            definitions.append("PRIMARY KEY (" + ", ".join(map(identifier, primary)) + ")")
        checks = build_checks(db, table, {row[1] for row in columns})
        check_count += len(checks)
        definitions.extend(checks)
        statements.append(f"CREATE TABLE {qualified} (\n    " + ",\n    ".join(definitions) + "\n);")
        statements.append(
            f"INSERT INTO {qualified} ({', '.join(names)})\n"
            f"SELECT {', '.join(values)}\n"
            f"FROM (SELECT convert_from(payload, 'UTF8')::json AS record FROM {staging}.source_rows "
            f"WHERE table_name = {literal(table)}) AS staged\n"
            f"WHERE {' AND '.join(present)};"
        )
        metadata = manifest["tables"][table]
        rows = metadata["rows"]
        watermark = manifest["sequence_high_watermarks"].get(table)
        sequence_sql = "NULL" if watermark is None else str(watermark)
        statements.append(
            f"INSERT INTO pg_temp.vyapari_typed_check SELECT {literal(table)}, {rows}, "
            f"(SELECT COUNT(*) FROM {qualified}), EXISTS ("
            f"SELECT 1 FROM {staging}.table_manifest WHERE table_name = {literal(table)} "
            f"AND expected_rows = {rows} AND sha256 = {literal(metadata['sha256'])} "
            f"AND sequence_high_watermark IS NOT DISTINCT FROM {sequence_sql}) "
            f"AND (SELECT COUNT(*) FROM {staging}.source_rows WHERE table_name = {literal(table)}) = {rows};"
        )
        if identity:
            statements.append(
                f"SELECT setval(pg_get_serial_sequence({literal(qualified)}, 'id'), "
                "GREATEST(high_id, 1), high_id > 0) "
                f"FROM (SELECT GREATEST(MAX(id), {watermark or 0}) AS high_id FROM {qualified}) AS ids;"
            )
        indexes.extend(build_indexes(db, table, qualified))
        # Rows sharing an id belong to one (possibly composite) foreign key.
        grouped = {}
        for key_id, sequence, parent, child_key, parent_key, update, delete, _ in db.execute(
            f"PRAGMA foreign_key_list({name})"
        ):
            if parent not in TABLES or not parent_key:
                raise ValueError(f"Unsupported foreign key on {table} referencing {parent}")
            entry = grouped.setdefault(key_id, {"parent": parent, "update": update, "delete": delete, "columns": []})
            entry["columns"].append((sequence, child_key, parent_key))
        for entry in grouped.values():
            pairs = sorted(entry["columns"])
            if [sequence for sequence, _, _ in pairs] != list(range(len(pairs))):
                raise ValueError(f"Unsupported foreign key on {table} referencing {entry['parent']}")
            foreign_keys.append(
                f"ALTER TABLE {qualified} ADD FOREIGN KEY ({', '.join(identifier(c) for _, c, _ in pairs)}) "
                f"REFERENCES {target}.{identifier(entry['parent'])} ({', '.join(identifier(p) for _, _, p in pairs)}) "
                f"ON UPDATE {entry['update']} ON DELETE {entry['delete']};"
            )
    return "\n".join([
        *statements,
        *indexes,
        *foreign_keys,
        f"""DO $vyapari$
BEGIN
    IF (SELECT COUNT(*) FROM pg_catalog.pg_constraint
        WHERE contype = 'c' AND connamespace = {literal(target)}::regnamespace) <> {check_count} THEN
        RAISE EXCEPTION 'Typed schema does not have the expected {check_count} CHECK constraints';
    END IF;
END
$vyapari$;""",
        "SELECT table_name, expected_rows, loaded_rows FROM pg_temp.vyapari_typed_check ORDER BY table_name;",
        "COMMIT;",
        "",
    ])


def write_typed_sql(source, bundle, destination, staging="vyapari_rehearsal", target="vyapari_typed_rehearsal"):
    if not all(re.fullmatch(r"[a-z][a-z0-9_]{0,62}", name) for name in (staging, target)):
        raise ValueError("Schema names must start with a lowercase letter and have at most 63 lowercase letters, digits, or underscores")
    if staging == target:
        raise ValueError("Use different staging and typed schema names")
    manifest = verify_bundle(bundle)
    with closing(open_readonly(source)) as db:
        db.execute("BEGIN")
        findings = inspect_database(db)
        if not findings["ready"]:
            raise ValueError("Database failed preflight. Run migration_check check for details.")
        for table in TABLES:
            if findings["table_counts"][table] != manifest["tables"][table]["rows"]:
                raise ValueError(f"SQLite source and bundle row counts differ for {table}")
        sql = build_sql(db, manifest, identifier(staging), identifier(target))
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(sql)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description="Generate a typed PostgreSQL rehearsal script.")
    parser.add_argument("source", type=Path, help="The SQLite backup used to create the bundle")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--staging-schema", default="vyapari_rehearsal")
    parser.add_argument("--typed-schema", default="vyapari_typed_rehearsal")
    args = parser.parse_args()
    try:
        write_typed_sql(args.source, args.bundle, args.destination, args.staging_schema, args.typed_schema)
    except (OSError, BadZipFile, ValueError) as error:
        parser.exit(1, f"Typed rehearsal script generation failed: {error}\n")
    print(f"Generated typed rehearsal script: {args.destination.resolve()}")


if __name__ == "__main__":
    main()
