"""Exercise migrations, initial access, backup and restore on a disposable installation."""
from contextlib import closing
from pathlib import Path
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile

from artifact_paths import artifact_root
from backup_restore import backup, restore, digest

ROOT = Path(__file__).resolve().parents[1]


def verify(temp):
    data = temp / "workspace"
    data.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PLAN_REVIEW_", "APP_")) and key != "DEPLOY_ENV"}
    env.update(APP_DATA_DIR=str(data), APP_BASE_PATH="/plan-review", DEPLOY_ENV="local",
               PLAN_REVIEW_DEMO="0", PLAN_REVIEW_WORKER="0",
               PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    def run(*args, input=None):
        return subprocess.run([sys.executable, "-B", *args], cwd=ROOT, env=env, input=input,
                              text=True, encoding="utf-8", capture_output=True, check=True)
    run("-m", "alembic", "upgrade", "head")
    run("-m", "alembic", "check")
    run("-c", """
import sys
from scripts.bootstrap import bootstrap
from backend.api import app
from fastapi.testclient import TestClient
password=sys.stdin.read()
bootstrap('test-admin','Isolated administrator',password,[{'code':'UK_MAIN','name':'UK test','market':'UK'}])
with TestClient(app,base_url='https://testserver') as c:
    assert c.get('/plan-review/api/v1/health').json()['demo'] is False
    assert c.post('/plan-review/api/v1/sessions',json={'username':'planner','password':password}).status_code==401
    login=c.post('/plan-review/api/v1/sessions',json={'username':'test-admin','password':password})
    assert login.status_code==200
    assert 'Secure' in login.headers['set-cookie'] and 'HttpOnly' in login.headers['set-cookie']
    assert c.get('/plan-review/api/v1/batches').json()==[]
""", input=secrets.token_urlsafe(32))
    attachment = data / "files" / "synthetic.txt"
    attachment.parent.mkdir(exist_ok=True)
    attachment.write_text("synthetic test attachment", encoding="utf-8")
    archive = backup(data, temp / "backups")
    destination = temp / "restored"
    restore(archive["backup"], destination)
    with closing(sqlite3.connect(data/"plan-review.sqlite3")) as source, closing(sqlite3.connect(destination/"plan-review.sqlite3")) as restored:
        assert source.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] > 0
        assert restored.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        business_dump = (line for line in source.iterdump() if not line.startswith('INSERT INTO "sessions"'))
        assert list(business_dump) == list(restored.iterdump())
    assert digest(attachment) == digest(destination / "files" / attachment.name)
    try:
        restore(archive["backup"], destination)
    except ValueError:
        pass
    else:
        raise AssertionError("Restore overwrote a nonempty destination")


if __name__ == "__main__":
    path = artifact_root(ROOT)
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="operations-",dir=path) as directory:
        verify(Path(directory))
    print(json.dumps({"migrations":"head", "initial_access":"ok", "sqlite_backup_restore":"ok"}))
