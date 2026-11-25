"""Read-only comparisons shared by basis previews and version history."""

from .governance import effective_input


def changed_fields(before, after, skip=()):
    before, after = before or {}, after or {}
    return {
        key: {'before': before.get(key), 'after': after.get(key)}
        for key in sorted((set(before) | set(after)) - set(skip))
        if before.get(key) != after.get(key)
    }


def compare_items(previous, current):
    """Compare business values, leaving original rows and source files untouched."""
    old_rows = {row['input']['material_code']: row for row in previous}
    new_rows = {row['input']['material_code']: row for row in current}
    changes = []
    counts = {'added': 0, 'removed': 0, 'modified': 0, 'quantity_changed': 0,
              'data_changed': 0, 'decision_changed': 0}
    for code in sorted(set(old_rows) | set(new_rows)):
        old, new = old_rows.get(code), new_rows.get(code)
        before, after = effective_input(old) if old else {}, effective_input(new) if new else {}
        old_result, new_result = (old or {}).get('result', {}), (new or {}).get('result', {})
        fields = changed_fields(before, after, ('source', 'source_values', 'source_update', 'plan_source', 'material_code'))
        result_fields = changed_fields(old_result, new_result, ('input_hash',))
        decisions = changed_fields((old or {}).get('decision'), (new or {}).get('decision'), ('issue_hash',))
        overrides = changed_fields((old or {}).get('submission_override'), (new or {}).get('submission_override'), ('issue_hash',))
        if old is None:
            change = '新增'; counts['added'] += 1
        elif new is None:
            change = '删除'; counts['removed'] += 1
        elif fields or result_fields or decisions or overrides:
            change = '修改'; counts['modified'] += 1
        else:
            continue
        if 'quantity_status' in result_fields:
            counts['quantity_changed'] += 1
        if 'data_status' in result_fields:
            counts['data_changed'] += 1
        if decisions or overrides:
            counts['decision_changed'] += 1
        changes.append({
            'id': (new or old).get('id'), 'material_code': code,
            'material_name': after.get('material_name') or before.get('material_name') or '',
            'change': change, 'fields': fields, 'result_fields': result_fields,
            'decision_fields': decisions, 'override_fields': overrides,
        })
    return {'items': changes, 'summary': {**counts, 'total': len(changes)}}
