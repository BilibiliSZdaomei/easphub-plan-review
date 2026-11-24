"""Readiness probes check real dependencies without exposing failure details."""
import json
import os
import re
import tempfile
from pathlib import Path
from sqlalchemy import inspect, text
from .db import engine, Base, ROOT, DATA, SCHEMA_REVISION
from .settings import BASE_PATH, DEPLOY_ENV

UI_DIR = Path(os.environ.get('PLAN_REVIEW_UI_DIR', str(ROOT/'frontend'/'dist')))


def check_database():
    with engine.connect() as connection:
        connection.execute(text('SELECT 1'))
        tables = set(inspect(connection).get_table_names())
        if not set(Base.metadata.tables) <= tables:
            raise RuntimeError('schema unavailable')
        if os.environ.get('PLAN_REVIEW_DEMO', '0') != '1':
            if connection.execute(text('SELECT version_num FROM alembic_version')).scalar() != SCHEMA_REVISION:
                raise RuntimeError('schema version mismatch')
        connection.execute(text('SELECT id FROM jobs LIMIT 1'))


def check_files():
    with tempfile.TemporaryFile(dir=DATA/'files') as probe:
        probe.write(b'readiness'); probe.flush(); probe.seek(0)
        if probe.read() != b'readiness':
            raise RuntimeError('storage unavailable')


def check_ui():
    html = (UI_DIR/'index.html').read_text(encoding='utf-8')
    manifest = UI_DIR/'app-build.json'
    if manifest.exists():
        if json.loads(manifest.read_text(encoding='utf-8'))['base_path'] != BASE_PATH:
            raise RuntimeError('frontend prefix mismatch; rebuild image')
    elif DEPLOY_ENV in ('home', 'company'):
        raise RuntimeError('frontend build manifest missing')
    assets = re.findall(r'(?:src|href)=["\']([^"\']+/assets/[^"\']+)["\']', html)
    if not assets:
        raise RuntimeError('frontend assets missing')
    for url in assets:
        if not url.startswith(BASE_PATH + '/') or not (UI_DIR/url[len(BASE_PATH)+1:]).is_file():
            raise RuntimeError('frontend asset unavailable')


def readiness():
    try:
        check_database(); check_files(); check_ui()
        return True
    except Exception:
        return False
