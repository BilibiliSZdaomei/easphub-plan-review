"""Undo and redo a bounded sequence of detail edits within one operator's workflow step."""
import json
import zlib
from dataclasses import dataclass

from sqlalchemy import delete, select, update

from .db import PlanRedo, PlanUndo, audit, now
from .roles import has_role


@dataclass
class BeforeEdit:
    revision: int
    rows: list
    basis: dict


def capture(version):
    # The mutation services replace items or edit a deep copy.
    return BeforeEdit(version.revision, version.items,
                      {'rule_id': version.rule_id, 'snapshot_id': version.snapshot_id})


def forget(db, version_id):
    for stack in (PlanUndo, PlanRedo):
        db.execute(delete(stack).where(stack.version_id == version_id))


def make_entry(stack, actor_id, version, before, label):
    """Encode the change from version back to before, retaining the 0009 payload format."""
    old = {row['id']: row for row in before.rows}
    new = {row['id']: row for row in version.items}
    changed = {}
    for id_ in old.keys() & new.keys():
        prior, current = old[id_], new[id_]
        if prior != current:
            fields = {k: v for k, v in prior.items() if k not in current or current[k] != v}
            changed[id_] = [fields, list(current.keys() - prior.keys())]
    removed = [old[k] for k in old.keys() - new.keys()]
    created = list(new.keys() - old.keys())
    basis = {key: val for key, val in before.basis.items() if getattr(version, key) != val}
    order = None if list(old) == list(new) else list(old)
    if not (changed or removed or created or basis or order is not None):
        return None
    inverse = dict(changed=changed, removed=removed, created=created, basis=basis, order=order)
    compressed = zlib.compress(json.dumps(inverse, ensure_ascii=False, separators=(',', ':')).encode(), 1)
    return stack(version_id=version.id, revision=version.revision, actor_id=actor_id, label=label,
                 row_count=len(changed) + len(removed) + len(created), payload=compressed)


def record(db, user, version, before, label):
    if version.revision == before.revision:
        return
    entry = make_entry(PlanUndo, user.id, version, before, label)
    if entry is None:
        return
    version_scope = PlanUndo.version_id == version.id
    previous = db.scalar(select(PlanUndo.actor_id).where(version_scope, PlanUndo.revision == before.revision))
    if previous != user.id:
        db.execute(delete(PlanUndo).where(version_scope))
    db.execute(delete(PlanRedo).where(PlanRedo.version_id == version.id))
    db.add(entry)
    # Undo and redo move an entry between stacks. Only a new edit increases their combined depth.
    cutoff = db.scalar(select(PlanUndo.revision).where(version_scope)
                       .order_by(PlanUndo.revision.desc()).offset(19).limit(1))
    if cutoff is not None:
        db.execute(delete(PlanUndo).where(version_scope, PlanUndo.revision < cutoff))


def hints(db, user, batch, version):
    result = {'undo': None, 'redo': None}
    if batch.current_id != version.id:
        return result
    owner = version.state == 'DRAFT' and batch.owner == user.id and has_role(user, 'PLANNER')
    reviewer = (version.state == 'IN_REVIEW' and version.reviewer_id == user.id
                and batch.owner != user.id and has_role(user, 'REVIEWER'))
    if owner or reviewer:
        for key, stack in (('undo', PlanUndo), ('redo', PlanRedo)):
            head = db.execute(select(stack.label, stack.row_count)
                              .where(stack.version_id == version.id, stack.revision == version.revision,
                                     stack.actor_id == user.id)).one_or_none()
            if head:
                result[key] = {'label': head.label, 'count': head.row_count}
    return result


def apply_entry(version, entry):
    inverse = json.loads(zlib.decompress(entry.payload))
    rows = {row['id']: row for row in version.items}
    for id_ in inverse['created']:
        del rows[id_]
    for row in inverse['removed']:
        rows[row['id']] = row
    for id_, (old_fields, new_keys) in inverse['changed'].items():
        restored = dict(rows[id_])
        restored.update(old_fields)
        for key in new_keys:
            restored.pop(key)
        rows[id_] = restored
    order = inverse['order']
    version.items = list(rows.values()) if order is None else [rows[k] for k in order]
    for key, value in inverse['basis'].items():
        setattr(version, key, value)
    affected = set(inverse['changed']) | {row['id'] for row in inverse['removed']}
    return [row['id'] for row in version.items if row['id'] in affected]


def move_entry(db, user, version_id, data, source, target, action):
    from . import services as svc
    batch, version = svc.version_access(db, user, version_id)
    if version.state == 'DRAFT':
        svc.editable(user, batch, version, data.get('revision'))
    else:
        svc.review_access(db, user, version_id, data.get('revision'))
    entry = db.get(source, (version_id, version.revision))
    svc.demand(entry is not None and entry.actor_id == user.id, '当前已没有可'+action+'的操作', 409)
    before = capture(version)
    affected = apply_entry(version, entry)
    label = entry.label
    revision_key = 'undo_revision' if source is PlanUndo else 'redo_revision'
    audit(db, user, action+'明细操作', batch.warehouse, batch.id, version.id, operation=label,
          count=entry.row_count, **{revision_key: entry.revision})
    batch.updated_at = now()
    db.delete(entry)
    db.flush()
    # Preserve the exact opposite transition, including decision authors/times, sources and basis.
    opposite = make_entry(target, user.id, version, before, label)
    svc.demand(opposite is not None, '操作记录与当前版本不符，请刷新', 409)
    db.add(opposite)
    prior_rev = db.scalar(select(source.revision).where(source.version_id == version_id,
                         source.actor_id == user.id).order_by(source.revision.desc()).limit(1))
    if prior_rev is not None:
        db.execute(update(source).where(source.version_id == version_id, source.revision == prior_rev)
                   .values(revision=version.revision))
    return {'revision': version.revision, 'affected_ids': affected}


def undo(db, user, version_id, data):
    return move_entry(db, user, version_id, data, PlanUndo, PlanRedo, '撤销')


def redo(db, user, version_id, data):
    return move_entry(db, user, version_id, data, PlanRedo, PlanUndo, '重做')

