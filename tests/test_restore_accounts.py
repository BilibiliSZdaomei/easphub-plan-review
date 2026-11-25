"""Isolated account migration: no production data, credentials, or network used."""
import secrets

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend import db as model
from backend.auth import hasher, login
from scripts import restore_accounts as transfer


def database(path):
    engine = create_engine("sqlite:///" + str(path))
    model.Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        db.exec_driver_sql("INSERT INTO alembic_version VALUES (?)", (model.SCHEMA_REVISION,))
    return engine


def test_encrypted_accounts_roundtrip_conflict_and_integrity(tmp_path, monkeypatch):
    source = tmp_path / "source.sqlite3"
    seed = database(source)
    password = secrets.token_urlsafe(24)
    with Session(seed) as db, db.begin():
        db.add(model.Warehouse(code="UK_TEST", name="Test warehouse", market="UK"))
        db.add(model.User(id="sample-a", username="sample-admin", name="Test admin", password_hash=hasher.hash(password),
                          roles=["ADMIN"], warehouses=["UK_TEST"], email="admin@example.test", active=True))
        db.add(model.User(id="sample-b", username="sample-planner", name="Test planner", password_hash=hasher.hash(password),
                          roles=["PLANNER"], warehouses=[], active=False))
        db.flush()
        db.add(model.UserAvatar(user_id="sample-a", preset="blank", source="sample", revision="1", config=None))
    seed.dispose()
    bundle, key = tmp_path / "sealed", tmp_path / "separate-key"
    assert transfer.export(source, bundle, key) == {"exported_accounts": 2}
    assert len(key.read_bytes()) == 32 and b"sample-admin" not in bundle.read_bytes()
    with pytest.raises(transfer.TransferError):
        transfer.export(source, bundle, key)
    payload = transfer.decrypt(bundle, key)
    assert payload == transfer.snapshot_sqlite(source)
    target = database(tmp_path / "target.sqlite3")
    monkeypatch.setattr(model, "SessionLocal", sessionmaker(bind=target, expire_on_commit=False))
    assert transfer.restore(payload) == {"imported_accounts": 2, "unchanged_accounts": 0, "other_existing_accounts": 0}
    assert transfer.restore(payload)["unchanged_accounts"] == 2
    with Session(target) as db, db.begin():
        assert login(db, "sample-admin", password)[0].email == "admin@example.test"
        assert db.scalar(select(func.count()).select_from(model.Rule)) == 1
        assert db.get(model.UserAvatar, "sample-a").preset == "blank"
        assert db.get(model.User, "sample-b").active is False
        db.get(model.User, "sample-b").name = "Later local change"
    # A prior unreconciled row cannot cause any partial insertion before the conflict.
    payload["users"].insert(0, dict(payload["users"][0], id="sample-c", username="new-before-conflict"))
    with pytest.raises(transfer.TransferError, match="Account conflict"):
        transfer.restore(payload)
    with Session(target) as db:
        assert db.get(model.User, "sample-c") is None
        assert db.get(model.User, "sample-b").name == "Later local change"
    fake_key = tmp_path / "wrong-key"
    fake_key.write_bytes(secrets.token_bytes(32))
    with pytest.raises(transfer.TransferError, match="Authentication failed"):
        transfer.decrypt(bundle, fake_key)
    altered = bytearray(bundle.read_bytes())
    altered[-1] ^= 1
    bundle.write_bytes(altered)
    with pytest.raises(transfer.TransferError, match="Authentication failed"):
        transfer.decrypt(bundle, key)
    target.dispose()
