import hashlib
from fastapi import Request, HTTPException
from .db import transaction, Idempotency
from .auth import authenticate
from .rules import fingerprint

def context(request:Request):
    with transaction() as db:
        user,session=authenticate(db,request,request.method not in ('GET','HEAD','OPTIONS'))
        yield db,user

def once(db,user,request,data,action):
    token=request.headers.get('Idempotency-Key','')
    if not token or len(token)>100:raise HTTPException(422,'缺少有效的操作标识，请刷新重试')
    key=hashlib.sha256((user.id+request.url.path+token).encode()).hexdigest()
    digest=fingerprint(data);old=db.get(Idempotency,key)
    if old:
        if old.digest!=digest:raise HTTPException(409,'相同操作标识对应不同内容')
        return old.response
    result=action();db.add(Idempotency(key=key,digest=digest,response=result));db.flush()
    return result
