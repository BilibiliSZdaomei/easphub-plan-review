"""Whole-draft warnings with a read-only overlay for the quantities being edited."""
from collections import OrderedDict
from threading import Lock

from .exceptions import business_warnings
from .rules import MODEL_V3, corrected_v3, sales_input_errors
from .services import demand, plan_result


# Published rules are immutable and a saved draft edit advances its revision.
# Cache only warning text for saved inputs. Previewing an unsaved edit never updates the cache.
_saved_warnings = OrderedDict()
_cache_lock = Lock()


def row_warnings(source, rule, snapshot_id):
    required = sales_input_errors(source) if corrected_v3(rule.package) else []
    required_fields = {err['field'] for err in required}
    result = plan_result(source, rule, snapshot_id)
    advisory = [issue for issue in business_warnings({'result': result}) if issue['field'] not in required_fields]
    return required, advisory


def saved_warnings(version, rule):
    key = (version.id, version.revision, rule.id, version.snapshot_id)
    with _cache_lock:
        if key in _saved_warnings:
            _saved_warnings.move_to_end(key)
            return _saved_warnings[key]
    warnings = {row['id']: row_warnings(row['input'], rule, version.snapshot_id) for row in version.items}
    with _cache_lock:
        _saved_warnings[key] = warnings
        if len(_saved_warnings) > 8:
            _saved_warnings.popitem(last=False)
    return warnings


def issue_preview(version, rule, edits, group='all', page=1):
    groups = ('required', 'returned', 'advisory')
    demand(group in ('all', *groups), '未知的问题类型')
    demand(isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= 10000, '页码无效')
    demand(isinstance(edits, dict) and len(edits) <= 10000, '数量预览格式无效')
    row_ids = {row['id'] for row in version.items}
    demand(edits.keys() <= row_ids, '部分计划行已变更，请刷新后重试', 409)
    for values in edits.values():
        demand(isinstance(values, dict) and set(values) <= {'sea_plan_qty', 'air_plan_qty'}
               and all(isinstance(v, str) and len(v) <= 80 for v in values.values()), '仅可预览本期海空计划数量')

    package = rule.package
    current_v3 = corrected_v3(package)
    counts = dict.fromkeys(groups, 0)
    baseline = saved_warnings(version, rule)
    affected = 0
    matches = []
    for row in version.items:
        source = row['input']
        if row['id'] in edits:
            source = {**source, **edits[row['id']]}
            required, advisory = row_warnings(source, rule, version.snapshot_id)
        else:
            required, advisory = baseline[row['id']]
        returned = bool(row.get('return_requested'))
        kinds = [key for key, present in (('returned', returned), ('required', required), ('advisory', advisory)) if present]
        if not kinds:
            continue
        affected += 1
        for key in kinds:
            counts[key] += 1
        if group != 'all' and group not in kinds:
            continue
        return_note = ('上轮要求修改' + (' · ' + row['return_reason'] if row.get('return_reason') else '')) if returned else None
        messages = list(dict.fromkeys(filter(None, [return_note, *(i['message'] for i in required+advisory)])))
        matches.append({'id':row['id'], 'material_code':source['material_code'],
                        'material_name':source.get('material_name',''), 'groups':kinds, 'messages':messages})
    order = {'returned':0, 'required':1, 'advisory':2}
    matches.sort(key=lambda r:(order[r['groups'][0]], r['material_code']))
    size = 8
    last = max(1,(len(matches)+size-1)//size)
    page = min(page,last)
    return {'revision':version.revision, 'total':len(version.items), 'affected':affected, 'counts':counts,
            'change_rule':package.get('model')==MODEL_V3 and not current_v3,
            'page':page, 'pages':last, 'matched':len(matches), 'rows':matches[(page-1)*size:page*size]}
