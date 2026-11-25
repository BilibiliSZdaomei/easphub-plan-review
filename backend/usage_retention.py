"""Clean expired aggregates and replay keys in short, indexed worker transactions."""
from datetime import datetime, timedelta, timezone
from threading import Lock
import time

from sqlalchemy import delete, select, tuple_

from .db import SessionLocal, UsageDay, UsageMetric, UsagePresence, UsageReceipt

_lock = Lock()
_next_run = 0.0
ONLINE_SECONDS = 120
REPORT_DAYS = 30


def prune(db, stamp, limit=100):
    # Each report covers at most the current UTC day and 29 preceding days.
    start = datetime.fromtimestamp(stamp,timezone.utc).date() - timedelta(days=REPORT_DAYS-1)
    pending = False
    for model,column,cutoff in ((UsageReceipt,UsageReceipt.expires,stamp),
                                (UsagePresence,UsagePresence.last_seen,stamp - ONLINE_SECONDS),
                                (UsageMetric,UsageMetric.day,start),(UsageDay,UsageDay.day,start)):
        keys = list(model.__table__.primary_key.columns)
        expired = db.execute(select(*keys).where(column < cutoff).order_by(column,*keys).limit(limit)).all()
        if expired:
            matched = (keys[0].in_([r[0] for r in expired]) if len(keys) == 1
                       else tuple_(*keys).in_([tuple(r) for r in expired]))
            # Recheck the cutoff in case a session has sent a new pulse since the scan.
            db.execute(delete(model).where(column < cutoff,matched).execution_options(synchronize_session=False))
        pending |= len(expired) == limit
    return pending


def prune_if_due():
    global _next_run
    if time.monotonic() < _next_run or not _lock.acquire(blocking=False):
        return
    try:
        if time.monotonic() < _next_run:
            return
        _next_run = time.monotonic() + 600
        with SessionLocal.begin() as db:
            more = prune(db,time.time())
        if more:
            _next_run = time.monotonic() + 1
    finally:
        _lock.release()
