"""Consolidate existing grants into one warehouse-scoped business role."""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    mysql = op.get_context().dialect.name == 'mysql'
    def has(code):
        if mysql:
            return f"JSON_CONTAINS(roles, JSON_QUOTE('{code}'))"
        return f"EXISTS (SELECT 1 FROM json_each(users.roles) WHERE value='{code}')"
    highest = 'CASE ' + ' '.join(f"WHEN {has(code)} THEN '{code}'" for code in ('ADMIN','REVIEWER','PLANNER')) + ' END'
    length = 'JSON_LENGTH' if mysql else 'json_array_length'
    changed = f'({highest} IS NULL OR {length}(roles) <> 1)'
    make_id = "REPLACE(UUID(),'-','')" if mysql else 'lower(hex(randomblob(16)))'
    roles_json = 'roles' if mysql else 'json(roles)'
    stamp = 'UTC_TIMESTAMP(6)' if mysql else "strftime('%Y-%m-%d %H:%M:%f','now')"
    op.execute(f"""INSERT INTO audit (id,user_id,action,detail,created_at)
        SELECT {make_id},id,'升级账号角色 0006',
        JSON_OBJECT('previous_roles',{roles_json},'previous_active',active,'assigned',{highest}),
        {stamp} FROM users WHERE {changed}""")
    op.execute(f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE {highest} IS NULL)")
    op.execute(f"""UPDATE users SET active=CASE WHEN {highest} IS NULL THEN 0 ELSE active END,
        roles=CASE WHEN {highest} IS NULL THEN JSON_ARRAY() ELSE JSON_ARRAY({highest}) END
        WHERE {changed}""")


def downgrade():
    # Restore pre-upgrade grants only if no administrator touched the account subsequently.
    mysql = op.get_context().dialect.name == 'mysql'
    target = "JSON_EXTRACT(e.detail,'$.target')"
    if mysql: target = f'JSON_UNQUOTE({target})'
    archived = f"""FROM audit a WHERE a.user_id=users.id AND a.action='升级账号角色 0006'
        AND NOT EXISTS (SELECT 1 FROM audit e WHERE e.action='修改用户授权'
            AND {target}=users.id AND REPLACE(e.created_at,'T',' ') >= a.created_at)
        ORDER BY a.created_at DESC LIMIT 1"""
    roles = f"(SELECT JSON_EXTRACT(a.detail,'$.previous_roles') {archived})"
    active = f"(SELECT JSON_EXTRACT(a.detail,'$.previous_active') {archived})"
    op.execute(f'UPDATE users SET roles={roles}, active={active} WHERE {roles} IS NOT NULL')
