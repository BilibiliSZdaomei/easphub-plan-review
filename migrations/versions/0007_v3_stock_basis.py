"""Publish corrected V3 stock rules while preserving pinned plan versions."""
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    mysql = op.get_context().dialect.name == 'mysql'
    model = "JSON_EXTRACT(package, '$.model')"
    if mysql:
        model = f"JSON_UNQUOTE({model})"
    old = f"{model}='V3' AND JSON_EXTRACT(package, '$.v3_revision') IS NULL"
    corrected = "JSON_SET(package, '$.v3_revision', '2026-11-25')"
    new_id = "CONCAT('v3r25-',id)" if mysql else "'v3r25-' || id"
    name = "CONCAT(LEFT(name,86),' · 11.25 修订')" if mysql else "substr(name,1,86) || ' · 11.25 修订'"
    stamp = "UTC_TIMESTAMP(6)" if mysql else "strftime('%Y-%m-%dT%H:%M:%fZ','now')"
    note = "AC=W+X+Y，当月销量、缺货数量必填。"
    op.execute(f"""INSERT INTO rules (id,name,scope,scope_code,state,active,package,revision,
        proof,note,creator,created_at,published_at,publisher)
        SELECT {new_id},{name},scope,scope_code,'PUBLISHED',0,{corrected},1,
        NULL,'{note}','migration-0007',{stamp},{stamp},'migration-0007' FROM rules
        WHERE state='PUBLISHED' AND active=1 AND {old}""")
    op.execute(f"UPDATE rules SET active=0, revision=revision+1 WHERE active=1 AND {old}")
    op.execute("UPDATE rules SET active=1 WHERE publisher='migration-0007' AND state='PUBLISHED'")
    op.execute(f"""UPDATE rules SET package={corrected}, revision=revision+1, proof=NULL
        WHERE state='DRAFT' AND {old}""")


def downgrade():
    # A previous binary does not implement the new arithmetic. Restoring its
    # pre-upgrade data backup keeps completed reviews and formula exports coherent.
    raise RuntimeError("回退 0007 需恢复升级前备份，以保留规则与审核版本的一致性")
