"""Migrate the desktop database and provision its first administrator."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--create-admin', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    data = args.data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    os.environ.update(APP_DATA_DIR=str(data), PLAN_REVIEW_DATA=str(data), PLAN_REVIEW_DEMO='0', DEPLOY_ENV='local')
    for key in ('PLAN_REVIEW_DATABASE_URL', 'PLAN_REVIEW_DATABASE_URL_FILE', 'PLAN_REVIEW_DB_PASSWORD_FILE'):
        os.environ.pop(key, None)

    from alembic import command
    from alembic.config import Config
    from bootstrap import bootstrap, warehouse_config
    from backend.db import User, transaction

    if args.create_admin:
        password = sys.stdin.buffer.readline().decode('utf-8-sig').rstrip('\r\n')
        bootstrap('admin', '系统管理员', password, warehouse_config())
    else:
        command.upgrade(Config(str(root/'alembic.ini')), 'head')
        with transaction() as db:
            print('READY' if db.query(User.id).first() else 'EMPTY')


if __name__ == '__main__':
    main()
