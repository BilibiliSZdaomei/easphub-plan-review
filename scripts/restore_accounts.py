"""Transfer login configuration separately from the application and business database."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORMAT = b"EASPHUB-PLAN-ACCOUNTS\x00\x01"
USER_FIELDS = ("id", "username", "name", "password_hash", "email", "roles", "warehouses", "active", "created_at")
AVATAR_FIELDS = ("user_id", "preset", "source", "revision", "config")
WAREHOUSE_FIELDS = ("code", "name", "market")


class TransferError(ValueError):
    """Message safe to show to the operator, including for production accounts."""


def snapshot_sqlite(filename):
    # A single read transaction sees one consistent revision of all three tables, including committed WAL data.
    with closing(sqlite3.connect(filename.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        users = [dict(row) for row in db.execute("SELECT " + ",".join(USER_FIELDS) + " FROM users ORDER BY id")]
        avatars = [dict(row) for row in db.execute("SELECT " + ",".join(AVATAR_FIELDS) + " FROM user_avatars ORDER BY user_id")]
        warehouses = [dict(row) for row in db.execute("SELECT " + ",".join(WAREHOUSE_FIELDS) + " FROM warehouses ORDER BY code")]
    for user in users:
        user["roles"] = json.loads(user["roles"])
        user["warehouses"] = json.loads(user["warehouses"])
        user["active"] = bool(user["active"])
    for avatar in avatars:
        if avatar["config"] is not None:
            avatar["config"] = json.loads(avatar["config"])
    return {"users": users, "avatars": avatars, "warehouses": warehouses}


def validate(records):
    if not isinstance(records, dict) or set(records) != {"users", "avatars", "warehouses"}:
        raise TransferError("Unsupported account bundle layout.")
    for group, fields, unique in (("users", USER_FIELDS, ("id", "username")),
                                  ("avatars", AVATAR_FIELDS, ("user_id",)),
                                  ("warehouses", WAREHOUSE_FIELDS, ("code",))):
        rows = records[group]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != set(fields) for row in rows):
            raise TransferError("Invalid account bundle records.")
        for field in unique:
            if any(not isinstance(row[field], str) or not row[field] for row in rows) or len({r[field] for r in rows}) != len(rows):
                raise TransferError("Missing or duplicate record identity.")
    users = records["users"]
    codes = {r["code"] for r in records["warehouses"]}
    if any(not isinstance(u["roles"], list) or not isinstance(u["warehouses"], list) or
           not set(u["warehouses"]).issubset(codes) or not isinstance(u["password_hash"], str) or
           not u["password_hash"].startswith("$argon2") for u in users):
        raise TransferError("Invalid account permissions, warehouse reference, or password verifier.")
    if not any(u["active"] and "ADMIN" in u["roles"] for u in users):
        raise TransferError("A usable account bundle needs an active administrator.")
    if not {a["user_id"] for a in records["avatars"]}.issubset({u["id"] for u in users}):
        raise TransferError("Invalid avatar owner.")


def write_new(path, data):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600), "wb"
    ) as file:
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        except OSError:
            file.close()
            path.unlink(missing_ok=True)
            raise


def export(sqlite_file, bundle, key_file):
    if bundle.resolve() == key_file.resolve() or bundle.exists() or key_file.exists():
        raise TransferError("Choose two distinct new files; an existing file cannot be replaced.")
    records = snapshot_sqlite(sqlite_file)
    validate(records)
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    payload = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    sealed = FORMAT + nonce + AESGCM(key).encrypt(nonce, payload, FORMAT)
    write_new(key_file, key)
    try:
        write_new(bundle, sealed)
    except BaseException:
        key_file.unlink(missing_ok=True)
        raise
    return {"exported_accounts": len(records["users"])}


def decrypt(bundle, key_file):
    raw = bundle.read_bytes()
    key = key_file.read_bytes()
    if not raw.startswith(FORMAT) or len(key) != 32:
        raise TransferError("Invalid bundle or key.")
    start = len(FORMAT)
    try:
        plaintext = AESGCM(key).decrypt(raw[start:start + 12], raw[start + 12:], FORMAT)
    except (ValueError, InvalidTag):
        raise TransferError("Authentication failed. Check the bundle and its separate key file.") from None
    records = json.loads(plaintext)
    validate(records)
    return records


def fields_of(row, fields):
    return {name: getattr(row, name) for name in fields}


def restore(records):
    from sqlalchemy import select, text
    from backend.db import SCHEMA_REVISION, Audit, Rule, User, UserAvatar, Warehouse, transaction
    from scripts.bootstrap import add_default_rules

    with transaction() as db:
        if db.get_bind().dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        if db.scalar(text("SELECT version_num FROM alembic_version")) != SCHEMA_REVISION:
            raise TransferError("Migrate the target database to the application's current revision first.")
        existing = list(db.scalars(select(User).order_by(User.id).with_for_update()))
        by_id = {u.id: u for u in existing}
        by_name = {u.username: u for u in existing}
        old_avatars = {a.user_id: a for a in db.scalars(select(UserAvatar).with_for_update())}
        avatars = {a["user_id"]: a for a in records["avatars"]}
        new_users = []
        for account in records["users"]:
            current = by_id.get(account["id"])
            named = by_name.get(account["username"])
            if current is None and named is None:
                new_users.append(account)
                continue
            if current is None or current is not named or fields_of(current, USER_FIELDS) != account:
                raise TransferError("Account conflict. Existing identities, passwords and permissions were preserved. Use a fresh database for an exact replica.")
            old = old_avatars.get(current.id)
            if (fields_of(old, AVATAR_FIELDS) if old else None) != avatars.get(current.id):
                raise TransferError("Avatar conflict. Existing accounts were preserved.")
        catalog = {w.code: w for w in db.scalars(select(Warehouse).with_for_update())}
        registered = []
        for record in records["warehouses"]:
            warehouse = catalog.get(record["code"])
            if warehouse is None:
                warehouse = Warehouse(**record)
                db.add(warehouse)
            elif fields_of(warehouse, WAREHOUSE_FIELDS) != record:
                raise TransferError("Warehouse identity conflict. Existing accounts and warehouses were preserved.")
            registered.append(warehouse)
        db.add_all(User(**row) for row in new_users)
        db.flush()
        db.add_all(UserAvatar(**avatars[row["id"]]) for row in new_users if row["id"] in avatars)
        # The normal fresh bootstrap installs default rules. Keep that behavior when the bundle supplies the first admin.
        if not existing and db.scalar(select(Rule.id).limit(1)) is None:
            admin = next(row for row in records["users"] if row["active"] and "ADMIN" in row["roles"])
            add_default_rules(db, admin["id"], registered)
        if new_users:
            db.add(Audit(user_id="deployment-cli", action="恢复账号配置", detail={"accounts": len(new_users)}))
        return {"imported_accounts": len(new_users), "unchanged_accounts": len(records["users"]) - len(new_users),
                "other_existing_accounts": len(existing) - (len(records["users"]) - len(new_users))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    save = actions.add_parser("export", help="Create a new encrypted bundle and a separate 32-byte key from a read-only SQLite source")
    save.add_argument("--sqlite", type=Path, required=True)
    load = actions.add_parser("restore", help="Restore into a migrated target. Exact existing records are skipped; conflicts roll back.")
    load.add_argument("--data-dir", type=Path, help="Explicit local SQLite workspace; otherwise use the application's database configuration")
    for action in (save, load):
        action.add_argument("--bundle", type=Path, required=True)
        action.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "export":
            result = export(args.sqlite, args.bundle, args.key_file)
        else:
            records = decrypt(args.bundle, args.key_file)
            if args.data_dir:
                database = args.data_dir.resolve() / "plan-review.sqlite3"
                if not database.is_file() or any(os.environ.get(k) for k in
                       ("PLAN_REVIEW_DATABASE_URL", "PLAN_REVIEW_DATABASE_URL_FILE", "PLAN_REVIEW_DB_PASSWORD_FILE")):
                    raise TransferError("Use an existing migrated SQLite workspace without a separate database connection setting.")
                os.environ["APP_DATA_DIR"] = str(database.parent)
                os.environ["PLAN_REVIEW_DATA"] = str(database.parent)
                os.environ["DEPLOY_ENV"] = "local"
            result = restore(records)
        print(json.dumps(result))
        return 0
    except TransferError as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        # Exception text from database drivers or filesystem helpers can include identities, bound SQL or credentials.
        print("Account transfer failed (" + type(exc).__name__ + "). Check the files, permissions and migrated database.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
