from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select

from backend.db import Audit, Base, LoginSession, User


def test_upgrade_preserves_warehouse_grants_and_disables_unassigned_accounts(tmp_path):
    db = create_engine('sqlite:///' + str(tmp_path / 'legacy.sqlite3'))
    Base.metadata.create_all(db)
    revision = import_module('migrations.versions.0006_account_roles')
    users, sessions, audit = User.__table__, LoginSession.__table__, Audit.__table__
    old = {
        'admin': ['RULE_PUBLISHER', 'ADMIN', 'PLANNER'],
        'review': ['PLANNER', 'REVIEWER'],
        'plan': ['DATA_STEWARD', 'PLANNER'],
        'technical': ['RULE_EDITOR', 'RULE_PUBLISHER'],
        'reader': ['VIEWER'],
        'unassigned': [],
        'inactive': ['DATA_STEWARD', 'REVIEWER'],
        'already': ['PLANNER'],
    }
    with db.begin() as connection:
        for key, roles in old.items():
            connection.execute(users.insert().values(
                id=key, username=key, name=key, roles=roles, warehouses=['UK_MAIN'],
                password_hash='original-hash', active=key!='inactive'))
            connection.execute(sessions.insert().values(token_hash=key, user_id=key, csrf='test', expires=1))
        ctx = MigrationContext.configure(connection)
        with Operations.context(ctx):
            revision.upgrade()
        after = {record.id: record for record in connection.execute(select(users))}
        assert {key: record.roles for key,record in after.items()} == {
            'admin':['ADMIN'], 'review':['REVIEWER'], 'plan':['PLANNER'], 'technical':[],
            'reader':[], 'unassigned':[], 'inactive':['REVIEWER'], 'already':['PLANNER'],
        }
        assert {key for key,record in after.items() if record.active} == {'admin','review','plan','already'}
        assert all(record.password_hash=='original-hash' and record.warehouses==['UK_MAIN'] for record in after.values())
        assert set(connection.scalars(select(sessions.c.user_id))) == {'admin','review','plan','inactive','already'}
        history = {r.user_id:r.detail for r in connection.execute(select(audit))}
        assert set(history)==set(old)-{'already'} and all(v['previous_roles']==old[k] for k,v in history.items())
        # A new grant by the administrator survives a rollback of the software.
        connection.execute(users.update().where(users.c.id=='reader').values(roles=['PLANNER'],active=True))
        connection.execute(audit.insert().values(user_id='admin',action='修改用户授权',detail={'target':'reader'}))
        with Operations.context(ctx):
            revision.downgrade()
        restored = {record.id:record for record in connection.execute(select(users))}
        assert {key:r.roles for key,r in restored.items()} == {**old,'reader':['PLANNER']}
        assert all(record.active==(key!='inactive') for key,record in restored.items())
    db.dispose()
