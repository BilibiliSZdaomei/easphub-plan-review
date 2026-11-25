import hashlib
import secrets
import time
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException
from sqlalchemy import select, delete
from .db import User, LoginSession
from .roles import account_role, has_role
from .account_email import notification_email
from .personas import SOURCE as AVATAR_SOURCE, REVISION as AVATAR_REVISION

hasher=PasswordHasher()
def hash_token(token): return hashlib.sha256(token.encode()).hexdigest()
def public_user(user):
    assigned=account_role(user)
    avatar=user.avatar
    return {"id":user.id,"username":user.username,"name":user.name,"roles":[assigned] if assigned else [],
            "warehouses":user.warehouses,"active":user.active,"email":user.email,"notification_email":notification_email(user),
            "avatar_preset":avatar.preset if avatar else "blank","avatar_config":avatar.config if avatar else None,
            "avatar_source":avatar.source if avatar else AVATAR_SOURCE,"avatar_revision":avatar.revision if avatar else AVATAR_REVISION}
def login(db,username,password):
    user=db.scalar(select(User).where(User.username==username,User.active.is_(True)))
    try:
        if not user or not account_role(user) or not hasher.verify(user.password_hash,password):
            raise HTTPException(401,'账号或密码不正确')
    except VerificationError:
        raise HTTPException(401,'账号或密码不正确')
    token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(24)
    db.add(LoginSession(token_hash=hash_token(token),user_id=user.id,csrf=csrf,expires=time.time()+8*3600))
    return user,token,csrf
def authenticate(db,request,write=False):
    token=request.cookies.get('plan_session','')
    session=db.get(LoginSession,hash_token(token))
    user=db.get(User,session.user_id) if session and session.expires>time.time() else None
    if not user or not user.active or not account_role(user): raise HTTPException(401,'登录已失效，请重新登录')
    if write and not secrets.compare_digest(request.headers.get('x-csrf-token',''),session.csrf):
        raise HTTPException(403,'请求验证失败，请刷新页面后重试')
    return user,session
def role(user,minimum):
    if not has_role(user,minimum): raise HTTPException(403,'当前账号没有此操作权限')
def scope(user,warehouse):
    if warehouse not in user.warehouses: raise HTTPException(403,'没有该仓库的数据权限')

def valid_password(value):
    return isinstance(value,str) and 6<=len(value)<=200 and bool(value.strip())

def password_change(db,user,password):
    if not valid_password(password):
        raise HTTPException(422,'新密码需为 6–200 位')
    user.password_hash=hasher.hash(password)
    db.execute(delete(LoginSession).where(LoginSession.user_id==user.id))
