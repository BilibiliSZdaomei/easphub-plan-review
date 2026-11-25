from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import os
import uuid
from contextvars import ContextVar
import logging
REQUEST_ID=ContextVar('request_id',default='background')
from sqlalchemy import create_engine, event, Column, String, Integer, Boolean, Text, JSON, Float, ForeignKey, UniqueConstraint,Index
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects import mysql
# MySQL needs explicit VARCHAR sizes. Other dialects keep their existing type.
# Case/accent-sensitive comparisons preserve the local SQLite identity semantics.
STRING = String().with_variant(mysql.VARCHAR(255, charset='utf8mb4', collation='utf8mb4_0900_bin'), 'mysql')
REAL = Float().with_variant(mysql.DOUBLE(), 'mysql')
from .settings import data_directory, database_url
SCHEMA_REVISION = '0006'

ROOT=Path(__file__).resolve().parents[1]
DATA=data_directory()
DATA.mkdir(parents=True,exist_ok=True)
URL=database_url(DATA)
engine=create_engine(URL,connect_args={'check_same_thread':False,'timeout':30} if URL.startswith('sqlite') else {'connect_timeout':5},pool_pre_ping=True,hide_parameters=True)
if URL.startswith('sqlite'):
    @event.listens_for(engine,'connect')
    def configure_sqlite(conn,record):
        conn.execute('PRAGMA foreign_keys=ON'); conn.execute('PRAGMA journal_mode=WAL'); conn.execute('PRAGMA busy_timeout=30000')
SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)
Base=declarative_base()
def uid(): return uuid.uuid4().hex
def now(): return datetime.now(timezone.utc).isoformat()

class User(Base):
    __tablename__='users'
    id=Column(STRING,primary_key=True,default=uid); username=Column(STRING,unique=True,nullable=False)
    name=Column(STRING,nullable=False); password_hash=Column(Text,nullable=False)
    roles=Column(JSON,nullable=False); warehouses=Column(JSON,nullable=False)
    active=Column(Boolean,default=True,nullable=False); created_at=Column(STRING,default=now)

class LoginSession(Base):
    __tablename__='sessions'
    token_hash=Column(STRING,primary_key=True); user_id=Column(STRING,ForeignKey('users.id'),nullable=False)
    csrf=Column(STRING,nullable=False); expires=Column(REAL,nullable=False)

class Warehouse(Base):
    __tablename__='warehouses'
    code=Column(STRING,primary_key=True); name=Column(STRING,nullable=False); market=Column(STRING,nullable=False)

class Rule(Base):
    __tablename__='rules'
    id=Column(STRING,primary_key=True,default=uid); name=Column(STRING,nullable=False)
    scope=Column(STRING,nullable=False,default='DEFAULT'); scope_code=Column(STRING,nullable=False,default='EUROPE')
    state=Column(STRING,default='DRAFT',nullable=False); active=Column(Boolean,default=False,nullable=False)
    package=Column(JSON,nullable=False); revision=Column(Integer,nullable=False,default=1)
    proof=Column(JSON,nullable=True); note=Column(Text,default=''); creator=Column(STRING,nullable=False)
    created_at=Column(STRING,default=now); published_at=Column(STRING); publisher=Column(STRING)
    __mapper_args__={'version_id_col':revision}

class Mapping(Base):
    __tablename__='mappings'
    id=Column(STRING,primary_key=True,default=uid); name=Column(STRING,nullable=False)
    warehouse=Column(STRING,ForeignKey('warehouses.code'),nullable=False)
    config=Column(JSON,nullable=False); creator=Column(STRING); created_at=Column(STRING,default=now)

ACTIVE_RULE_INDEX=Index('uq_rules_active_scope',Rule.scope,Rule.scope_code,unique=True,sqlite_where=Rule.active.is_(True),postgresql_where=Rule.active.is_(True)).ddl_if(dialect=('sqlite','postgresql'))
from sqlalchemy import text as sql_text
MYSQL_ACTIVE_RULE_INDEX=Index('uq_rules_active_scope_mysql',Rule.scope,Rule.scope_code,sql_text('(CASE WHEN active = 1 THEN 1 ELSE NULL END)'),unique=True).ddl_if(dialect='mysql')

class NotificationEvent(Base):
    __tablename__='notification_events'
    id=Column(STRING,primary_key=True,default=uid)
    payload=Column(JSON,nullable=False);state=Column(STRING,default='QUEUED',nullable=False,index=True)
    attempts=Column(Integer,default=0,nullable=False);lease=Column(REAL,default=0,nullable=False)
    created_at=Column(STRING,default=now);error=Column(STRING)

class Snapshot(Base):
    __tablename__='snapshots'
    id=Column(STRING,primary_key=True,default=uid); warehouse=Column(STRING,ForeignKey('warehouses.code'),nullable=False,index=True)
    name=Column(STRING,nullable=False); as_of=Column(STRING,nullable=False); created_at=Column(STRING,default=now)
    net_mode=Column(STRING,nullable=False); basis=Column(Text,nullable=False); items=Column(JSON,nullable=False)
    source_id=Column(STRING); mapping_id=Column(STRING); creator=Column(STRING,nullable=False)
    digest=Column(STRING,nullable=False)

class Batch(Base):
    __tablename__='batches'
    id=Column(STRING,primary_key=True,default=uid); number=Column(STRING,unique=True,nullable=False)
    title=Column(STRING,nullable=False); warehouse=Column(STRING,ForeignKey('warehouses.code'),nullable=False,index=True)
    period=Column(STRING,nullable=False); owner=Column(STRING,ForeignKey('users.id'),nullable=False)
    state=Column(STRING,nullable=False,default='DRAFT',index=True); current_id=Column(STRING)
    created_at=Column(STRING,default=now); updated_at=Column(STRING,default=now)

class Version(Base):
    __tablename__='versions'
    id=Column(STRING,primary_key=True,default=uid); batch_id=Column(STRING,ForeignKey('batches.id'),nullable=False,index=True)
    seq=Column(Integer,nullable=False); revision=Column(Integer,nullable=False,default=1)
    state=Column(STRING,nullable=False,default='DRAFT'); snapshot_id=Column(STRING,ForeignKey('snapshots.id'),nullable=True)
    reviewer_id=Column(STRING,nullable=True)
    reviewer_name=Column(STRING,nullable=True)
    rule_id=Column(STRING,ForeignKey('rules.id'),nullable=False); items=Column(JSON,nullable=False)
    created_at=Column(STRING,default=now); submitted_at=Column(STRING); finalized_at=Column(STRING)
    __table_args__=(UniqueConstraint('batch_id','seq'),)
    __mapper_args__={'version_id_col':revision}

class Audit(Base):
    __tablename__='audit'
    id=Column(STRING,primary_key=True,default=uid); user_id=Column(STRING,nullable=False)
    action=Column(STRING,nullable=False); warehouse=Column(STRING,index=True); batch_id=Column(STRING,index=True)
    version_id=Column(STRING); detail=Column(JSON,nullable=False); created_at=Column(STRING,default=now)

class Notification(Base):
    __tablename__='notifications'
    id=Column(STRING,primary_key=True,default=uid); user_id=Column(STRING,ForeignKey('users.id'),nullable=False,index=True)
    batch_id=Column(STRING,nullable=False); warehouse=Column(STRING,nullable=False)
    text=Column(Text,nullable=False); seen=Column(Boolean,default=False,nullable=False); created_at=Column(STRING,default=now)

class Job(Base):
    __tablename__='jobs'
    id=Column(STRING,primary_key=True,default=uid); kind=Column(STRING,nullable=False)
    user_id=Column(STRING,nullable=False); warehouse=Column(STRING,nullable=False,index=True)
    state=Column(STRING,default='QUEUED',nullable=False,index=True); payload=Column(JSON,nullable=False)
    result=Column(JSON); error=Column(Text); lease=Column(REAL,default=0,nullable=False)
    attempts=Column(Integer,default=0,nullable=False); created_at=Column(STRING,default=now)
    finished_at=Column(STRING); committed_id=Column(STRING)

class Idempotency(Base):
    __tablename__='idempotency'
    key=Column(STRING,primary_key=True); digest=Column(STRING,nullable=False); response=Column(JSON,nullable=False)
    created_at=Column(STRING,default=now)

def audit(db,user,action,warehouse=None,batch=None,version=None,**detail):
    detail['request_id']=REQUEST_ID.get()
    db.add(Audit(user_id=user.id,action=action,warehouse=warehouse,batch_id=batch,version_id=version,detail=detail))
    logging.getLogger('uvicorn.error').info('audit request=%s batch=%s version=%s action=%s',REQUEST_ID.get(),batch or '-',version or '-',action)

def init_db():
    if os.environ.get('PLAN_REVIEW_DEMO','0')=='1':
        Base.metadata.create_all(engine)
    else:
        from sqlalchemy import inspect,text
        if 'alembic_version' not in inspect(engine).get_table_names():
            raise RuntimeError('正式环境请先运行 python -m alembic upgrade head')
        with engine.connect() as db:
            if db.execute(text('SELECT version_num FROM alembic_version')).scalar()!=SCHEMA_REVISION:
                raise RuntimeError('数据库版本与应用不一致，请先完成迁移')

@contextmanager
def transaction():
    db=SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()
