"""Business warnings shown before a plan is submitted or finalized."""
from .rules import FLAG_LABELS, fingerprint
from collections import Counter


def approval_status(result):
    if (result.get('quantity_status') in ('BELOW', 'ABOVE')
            or result.get('delay_replenishment')
            or result.get('data_status') in ('ERROR', 'PENDING')):
        return 'EXCEPTION_APPROVED'
    return 'APPROVED'


def business_warnings(row):
    result = row['result']
    issues = list(result['errors'])
    issues.extend({'field':'data', 'message':message} for message in result.get('warnings', []))
    quantity = {'BELOW':'低于库存下限', 'ABOVE':'高于库存上限'}.get(result['quantity_status'])
    if quantity:
        issues.append({'field':'quantity', 'message':quantity})
    if result.get('delay_replenishment'):
        issues.append({'field':'delay', 'message':'建议延迟补货'})
    if result.get('turnover_warning'):
        issues.append({'field':'turnover_warning', 'message':result['turnover_warning']})
    for flag in result['manual_flags']:
        issues.append({'field':flag, 'message':FLAG_LABELS.get(flag, flag)})
    if result['review_mode']=='MANUAL' and not result.get('basis_pending') and 'MANUAL' not in result['manual_flags']:
        issues.append({'field':'review_mode','message':'需人工判断'})
    return issues


def confirmation(rows,stage,revision,all_rows=False):
    affected=[]
    decisions=Counter()
    pending_exceptions=0
    for row in rows:
        status=(row.get('decision') or {}).get('status')
        decisions[status]+=1
        if not status and approval_status(row['result'])=='EXCEPTION_APPROVED':
            pending_exceptions+=1
        issues=business_warnings(row)
        if issues:affected.append({'id':row['id'],'material_code':row['input']['material_code'],'material_name':row['input'].get('material_name',''),'issues':issues,'flags':row['result']['manual_flags'],'data_error':row['result']['data_status']=='ERROR'})
    rejected=decisions['REJECTED']+decisions['RETURNED']
    reviewed_exception=decisions['EXCEPTION_APPROVED']
    return {'stage':stage,'revision':revision,'total':len(rows),'unreviewed':decisions[None],'affected_count':len(affected),'issue_count':sum(len(r['issues']) for r in affected),
            'rejected':rejected,'approval_blocked':bool(rejected),
            'reviewed_approved':decisions['APPROVED']+decisions['BATCH_APPROVED']+reviewed_exception,
            'reviewed_exception':reviewed_exception,'return_marked':decisions['RETURNED'],
            'unreviewed_exception':0 if rejected else pending_exceptions,
            'exception_approved':0 if rejected else reviewed_exception+pending_exceptions,
            'error_rows':sum(r['data_error'] for r in affected),'air_rows':sum('AIR' in r['flags'] for r in affected),
            'rows':affected if all_rows else affected[:100],'truncated':not all_rows and len(affected)>100,
            'issue_hash':fingerprint({'stage':stage,'revision':revision,'rows':affected})}

def warning_record(data,report,user,at):
    from .services import demand
    if data.get('issue_hash') is not None:
        demand(data['issue_hash']==report['issue_hash'],'提醒内容已变化，请刷新重试',409)
    reason = str(data.get('reason') or '').strip()
    demand(len(reason)<=2000,'备注最多2000字')
    return {'reason':reason,'user_id':user.id,'user_name':user.name,'at':at,'issue_hash':report['issue_hash'],
            'affected_count':report['affected_count'],'stage':report['stage'],'mode':'advisory'}
