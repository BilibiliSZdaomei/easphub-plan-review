"""Aggregate fixed UI events without storing URLs, input values or click trails."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import time
import uuid
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, UUID4, ValidationError, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .api_common import context
from .auth import hash_token, role
from .db import LoginSession, UsageDay, UsageMetric, UsagePresence, UsageReceipt, User
from .roles import account_role
from .settings import DEPLOY_ENV
from .usage_retention import ONLINE_SECONDS, REPORT_DAYS
from .usage_umami import forward_usage, umami_enabled

router = APIRouter()
Page = Literal['home','plans','detail','history','data','rules','accounts','inbox','profile','usage']
Device = Literal['desktop','mobile']
Target = Literal['navigation','button','input','select','table','filter','dialog','create','import','export',
                 'save','submit','approve','reject','return','undo','redo','transfer','account','other']
FRICTION = {'repeat','error','validation'}
RETRY_SECONDS = 86400


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['pulse','view','click','repeat','error','validation']
    page: Page
    device: Device
    target: Target | None = None
    x: Annotated[int, Field(strict=True, ge=0, le=7)] | None = None
    y: Annotated[int, Field(strict=True, ge=0, le=5)] | None = None

    @model_validator(mode='after')
    def event_dimensions(self):
        if self.kind == 'click':
            if self.x is None or self.y is None or self.target is None:
                raise ValueError('click needs a region and action')
        elif self.x is not None or self.y is not None or (self.target is not None) != (self.kind in FRICTION):
            raise ValueError('unexpected dimensions for event')
        return self


class UsageBatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_id: UUID4
    sent_at: Annotated[float, Field(strict=True, allow_inf_nan=False)]
    events: Annotated[list[UsageEvent], Field(min_length=1, max_length=60)]


async def read_batch(request: Request):
    origin = request.headers.get('origin')
    if origin:
        parts = urlsplit(origin)
        # The public company/home endpoint is HTTPS; Nginx preserves Host but can
        # terminate TLS before Uvicorn. Never infer scheme from a client header.
        scheme = 'https' if DEPLOY_ENV in ('company','home') else request.url.scheme
        if (parts.scheme,parts.netloc) != (scheme,request.url.netloc) or parts.path or parts.query or parts.fragment:
            raise HTTPException(403,'不允许跨站请求')
    if request.headers.get('sec-fetch-site') in ('cross-site','same-site'):
        raise HTTPException(403,'不允许跨站请求')
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 16 * 1024:
            raise HTTPException(413,'统计数据过大')
        raw.extend(chunk)
    try:
        return UsageBatch.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422,'统计数据格式无效') from None


def upsert(db, model, values, updates):
    """The update mapping uses the dialect's incoming row for atomic counters."""
    table = model.__table__
    if db.get_bind().dialect.name == 'mysql':
        stmt = mysql_insert(table).values(values)
        stmt = stmt.on_duplicate_key_update(**updates(stmt.inserted, True))
    else:
        stmt = sqlite_insert(table).values(values)
        stmt = stmt.on_conflict_do_update(index_elements=list(table.primary_key.columns), set_=updates(stmt.excluded, False))
    db.execute(stmt)


def accept_batch(db, user_id, batch):
    key = hashlib.sha256(f'{user_id}/{batch.batch_id}'.encode()).hexdigest()
    digest = hashlib.sha256(batch.model_dump_json().encode()).hexdigest()
    nonce = uuid.uuid4().hex
    upsert(db, UsageReceipt, {'id':key,'digest':digest,'nonce':nonce,'expires':batch.sent_at + RETRY_SECONDS + 1},
           lambda incoming, mysql: {'id':UsageReceipt.id})
    # A locking read sees the first committer even under MySQL REPEATABLE READ.
    receipt = db.execute(select(UsageReceipt.nonce,UsageReceipt.digest).where(UsageReceipt.id == key).with_for_update()).one()
    if receipt.digest != digest:
        raise HTTPException(409,'重复统计批次的内容不同')
    return receipt.nonce == nonce


@router.post('/usage/events')
def record(request: Request, tasks: BackgroundTasks, ctx=Depends(context,scope='function'), batch=Depends(read_batch)):
    db,user = ctx
    stamp = time.time()
    if not stamp - RETRY_SECONDS <= batch.sent_at <= stamp + 300:
        raise HTTPException(422,'统计批次时间无效')
    if not accept_batch(db,user.id,batch):
        return {'ok':True}

    observed = min(batch.sent_at,stamp)
    day = datetime.fromtimestamp(observed,timezone.utc).date()
    kinds = Counter(event.kind for event in batch.events)
    totals = {'views':kinds['view'],'clicks':kinds['click'],'friction':sum(kinds[k] for k in FRICTION)}
    upsert(db, UsageDay, {'user_id':user.id,'day':day,**totals},
           lambda incoming, mysql: {k:getattr(UsageDay,k) + incoming[k] for k in totals})
    counts = Counter((e.kind,e.page,e.device,e.target or '-',8 * e.y + e.x if e.kind == 'click' else -1)
                     for e in batch.events if e.kind != 'pulse')
    if counts:
        rows = [{'user_id':user.id,'day':day,'kind':k,'page':p,'device':d,'target':t,'cell':c,'count':n}
                for (k,p,d,t,c),n in sorted(counts.items())]
        upsert(db,UsageMetric,rows,lambda incoming, mysql: {'count':UsageMetric.count + incoming['count']})
    if kinds['pulse'] and observed >= stamp - ONLINE_SECONDS:
        upsert(db, UsagePresence, {'session_hash':hash_token(request.cookies['plan_session']),'last_seen':observed},
               lambda incoming, mysql: {'last_seen':(func.greatest if mysql else func.max)(UsagePresence.last_seen,incoming.last_seen)})
    if umami_enabled():
        tasks.add_task(forward_usage,batch.events)
    return {'ok':True}


@router.get('/usage/insights')
def insights(scope: Literal['me','team']='me', days: int=7, page: Page | Literal['all']='all',
             device: Device | Literal['all']='all',ctx=Depends(context,scope='function')):
    db,user = ctx
    role(user,'ADMIN')
    if days not in (1,7,REPORT_DAYS):
        raise HTTPException(422,'统计周期无效')
    if scope == 'team':
        authorized = set(user.warehouses)
        directory = db.execute(select(User.id,User.name,User.roles,User.warehouses,User.active))
        users = [u for u in directory if set(u.warehouses) <= authorized]
    else:
        users = [user]
    people = {u.id:{'id':u.id,'name':u.name,'role':account_role(u),'active_days':0,'page_views':0,'click_count':0,
                    'friction_events':0,'online':False} for u in users}
    stamp = time.time()
    generated = datetime.fromtimestamp(stamp,timezone.utc)
    start = generated.date() - timedelta(days=days-1)
    trend = {start + timedelta(days=i):{'date':str(start + timedelta(days=i)),'page_views':0,
                                       'active_users':0,'friction_events':0} for i in range(days)}
    allowed_ids = list(people)
    daily = db.scalars(select(UsageDay).where(UsageDay.user_id.in_(allowed_ids),UsageDay.day.between(start,generated.date())))
    clicks = 0
    for row in daily:
        daily_total,person = trend[row.day],people[row.user_id]
        daily_total['page_views'] += row.views
        daily_total['active_users'] += 1
        daily_total['friction_events'] += row.friction
        person['active_days'] += 1
        person['page_views'] += row.views
        person['click_count'] += row.clicks
        person['friction_events'] += row.friction
        clicks += row.clicks
    online = db.scalars(select(LoginSession.user_id).join(UsagePresence,UsagePresence.session_hash == LoginSession.token_hash)
                        .where(LoginSession.user_id.in_(allowed_ids),LoginSession.expires > stamp,
                               UsagePresence.last_seen >= stamp - ONLINE_SECONDS).distinct())
    active_ids = {u.id for u in users if u.active}
    for uid in online:
        people[uid]['online'] = uid in active_ids

    metric = UsageMetric
    filters = [metric.user_id.in_(allowed_ids), metric.day.between(start,generated.date())]
    grouped = db.execute(select(metric.kind,metric.page,metric.target,func.sum(metric.count).label('total'))
                         .where(*filters).group_by(metric.kind,metric.page,metric.target))
    pages,actions = Counter(), Counter()
    friction = []
    for kind,feature,target,total in grouped:
        if kind == 'view':
            pages[feature] += int(total)
        elif kind == 'click':
            actions[target] += int(total)
        elif kind in FRICTION:
            friction.append({'kind':kind,'page':feature,'target':target,'count':int(total)})
    if page != 'all':
        filters.append(metric.page == page)
    if device != 'all':
        filters.append(metric.device == device)
    quantity = func.sum(metric.count)
    tiles = db.execute(select(metric.cell,metric.target,quantity).where(*filters,metric.kind == 'click')
                       .group_by(metric.cell,metric.target).order_by(metric.cell,quantity.desc(),metric.target))
    cells_by_index = {}
    for index,target,total in tiles:
        cell = cells_by_index.setdefault(index,{'x':index % 8,'y':index // 8,'count':0,'actions':[]})
        cell['count'] += int(total)
        cell['actions'].append({'target':target,'count':int(total)})
    cells = list(cells_by_index.values())
    summary = {'page_views':sum(pages.values()),'active_days':sum(t['active_users'] > 0 for t in trend.values()),
               'active_users':sum(p['active_days'] > 0 for p in people.values()),'online_users':sum(p['online'] for p in people.values()),
               'click_count':clicks,'friction_events':sum(p['friction_events'] for p in people.values())}
    return {'generated_at':generated.isoformat(),'scope':scope,'days':days,'timezone':'UTC','summary':summary,
            'trend':list(trend.values()),'pages':[{'page':p,'page_views':n} for p,n in sorted(pages.items(),key=lambda p:(-p[1],p[0]))],
            'actions':[{'target':t,'count':n} for t,n in sorted(actions.items(),key=lambda p:(-p[1],p[0]))],
            'people':sorted(people.values(),key=lambda p:(-p['page_views'],p['name'],p['id'])),
            'friction':sorted(friction,key=lambda f:(-f['count'],f['kind'],f['page'],f['target'])),
            'heatmap':{'columns':8,'rows':6,'cells':cells,'total':sum(c['count'] for c in cells)}}
