"""Bind the API tests to a new local database before importing the backend."""
import os
from pathlib import Path
import tempfile
import pytest


for name in tuple(os.environ):
    if name.startswith(('PLAN_REVIEW_DATABASE_URL', 'PLAN_REVIEW_DB_')) or name in ('APP_DATA_DIR', 'PLAN_REVIEW_DATA'):
        os.environ.pop(name)

test_data_dir = Path(tempfile.mkdtemp(prefix='plan-review-test-')).resolve()
os.environ.update(APP_DATA_DIR=str(test_data_dir), PLAN_REVIEW_DATA=str(test_data_dir),
                  APP_BASE_PATH='/plan-review', DEPLOY_ENV='local', PLAN_REVIEW_DEMO='1', PLAN_REVIEW_WORKER='0')


@pytest.fixture(scope='session')
def test_database_path():
    return test_data_dir/'plan-review.sqlite3'
