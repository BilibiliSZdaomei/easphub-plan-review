import hashlib
from fastapi import Request, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from .db import transaction, Idempotency
from .auth import authenticate
from .rules import fingerprint

def context(request:Request):
    with transaction() as db:
        user,session=authenticate(db,request,request.method not in ('GET','HEAD','OPTIONS'))
        yield db,user

def once(db,user,request,data,action,*,on_replay=None,replay_conflicts=False):
    token=request.headers.get('Idempotency-Key','')
    if not token or len(token)>100:raise HTTPException(422,'缺少有效的操作标识，请刷新重试')
    key=hashlib.sha256((user.id+request.url.path+token).encode()).hexdigest()
    digest=fingerprint(data)
    def replay(saved):
        if on_replay is not None:
            on_replay()
        if saved.digest!=digest:raise HTTPException(409,'相同操作标识对应不同内容')
        return saved.response
    saved=db.get(Idempotency,key)
    if saved:
        return replay(saved)
    try:
        result=action()
        db.add(Idempotency(key=key,digest=digest,response=result))
        db.flush()
        return result
    except (HTTPException,StaleDataError,IntegrityError) as exc:
        if not replay_conflicts or (isinstance(exc,HTTPException) and exc.status_code!=409):
            raise
        # A concurrent request with this key may have committed while we waited for the version.
        # Read its result in a fresh transaction, including on MySQL REPEATABLE READ.
        db.rollback()
        saved=db.get(Idempotency,key)
        if saved:
            return replay(saved)
        raise
