from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.account_email import normalize_email, notification_email
from backend.db import Audit, SessionLocal, WorkflowMail
from test_api import P, clients, post


def test_single_recipient_and_safe_fallback():
    assert normalize_email(' Ops.Plus+shift@MAIL.Example.org ') == 'Ops.Plus+shift@mail.example.org'
    for invalid in ('x,y@example.org','x@example.org;z@example.org','x@example.org\r\nBcc: z@example.org',
                    'x@example.org\n','Display <x@example.org>','a..b@example.org','.a@example.org',
                    'a@-example.org','a@example-.org','a@example..org','a@localhost','a@b.c@d.org',
                    'x'*65+'@example.org','a@'+'x'*64+'.org',123,[]):
        with pytest.raises(ValueError):
            normalize_email(invalid)
    for empty in (None,'','   '):
        assert normalize_email(empty) is None
        assert notification_email(SimpleNamespace(email=empty,username='9123456')) is None
        assert notification_email(SimpleNamespace(email=empty,username='Someone@EXAMPLE.org'))=='Someone@example.org'
    assert notification_email(SimpleNamespace(email='team@example.org',username='login@example.org'))=='team@example.org'


def test_admin_only_email_change_keeps_session_and_redirects_pending_mail(clients):
    planner, reviewer, admin, _=clients
    profile=planner.get(P+'/me').json()['user']
    endpoint=P+'/users/'+profile['id']
    with SessionLocal.begin() as db:
        db.add(WorkflowMail(id='test-pending-email',event_id='test',recipient_id=profile['id'],kind='RETURNED',
                            warehouse='UK_MAIN',batch_id='case',version_id='v1',payload={},state='WAITING_EMAIL'))
    def check_mail(state,address):
        with SessionLocal() as db:
            row=db.get(WorkflowMail,'test-pending-email')
            assert (row.state,row.destination)==(state,address)
    for member in (planner,reviewer):
        assert member.patch(endpoint,json={'email':'test@example.org'}).status_code==403
    assert admin.patch(endpoint,json={'email':'inject\r\n@example.org'}).status_code==422
    check_mail('WAITING_EMAIL',None)
    assert admin.patch(endpoint,json={'email':'first@EXAMPLE.org'}).json()['notification_email']=='first@example.org'
    check_mail('QUEUED','first@example.org')
    assert planner.get(P+'/me').json()['user']['email']=='first@example.org'
    profile.update(email='second@example.org',password='bad')
    assert admin.patch(endpoint,json=profile).status_code==422
    check_mail('QUEUED','first@example.org')
    assert admin.patch(endpoint,json={'email':' '}).json()['notification_email'] is None
    check_mail('WAITING_EMAIL',None)
    assert planner.get(P+'/me').status_code==200
    with SessionLocal() as db:
        edits=db.scalars(select(Audit).where(Audit.action=='修改通知邮箱')).all()
        assert len(edits)==2 and all('@' not in str(entry.detail) for entry in edits)


def test_optional_bulk_field_bilingual_and_atomic(clients):
    _,_,admin,_=clients
    for lang,header,role in [
        ('zh','姓名,角色,通知邮箱,账号,初始密码','计划员'),
        ('en','Name,Role,Notification email,Username,Initial password','PLANNER'),
    ]:
        table=header+f'\nTest,{role},team@EXAMPLE.ORG,notify-{lang},test-secret'
        row=post(admin,'/users/bulk/preview',{'table':table}).json()['rows'][0]
        assert row['email']=='team@example.org' and not row['issues']
        assert post(admin,'/users/bulk',{'table':table}).json()=={'created':1}
    mixed='bad-test,Test,test-secret,PLANNER,,invalid\nvalid-test,Test,test-secret,PLANNER,,a@example.org'
    assert post(admin,'/users/bulk',{'table':mixed}).status_code==422
    assert not any(u['username']=='valid-test' for u in admin.get(P+'/users').json())
    result=post(admin,'/users',{'username':'Mailbox@EXAMPLE.org','name':'Test','password':'test-secret','roles':['PLANNER'],'warehouses':[]}).json()
    assert result['email'] is None and result['notification_email']=='Mailbox@example.org'
    endpoint=P+'/users/'+result['id']
    assert admin.patch(endpoint,json={'email':'ops@example.org'}).json()['notification_email']=='ops@example.org'
    assert admin.patch(endpoint,json={'email':None}).json()['notification_email']=='Mailbox@example.org'
