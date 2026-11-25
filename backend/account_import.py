"""Read the administrator's pasted Excel cells or CSV without persisting the source."""
from collections import Counter
import csv
from io import StringIO
import re

from fastapi import HTTPException
from sqlalchemy import select

from .db import User, Warehouse
from .auth import valid_password
from .roles import ROLE_NAMES
from .account_email import normalize_email

HEADERS = ['账号', '姓名', '初始密码', '角色', '授权仓库']
ENGLISH_HEADERS = ['Username', 'Name', 'Initial password', 'Role', 'Authorized warehouses']
HEADER_ALIASES = {name.casefold(): key for key, name in zip(HEADERS, ENGLISH_HEADERS)}
EMAIL_HEADER = '通知邮箱'
HEADER_ALIASES.update(dict.fromkeys(('notification email','email','email address','邮箱','收件邮箱'),EMAIL_HEADER))
REQUIRED_HEADERS = frozenset(HEADERS[:-1])
OPTIONAL_HEADERS = {'授权仓库',EMAIL_HEADER}
MAX_ACCOUNTS = 100


def read_accounts(table):
    if not isinstance(table, str) or not table.lstrip('\ufeff').strip():
        raise HTTPException(422, '请粘贴账号表或选择文件')
    if len(table) > 256_000:
        raise HTTPException(422, '账号表过大，每批最多 100 人')
    table = table.lstrip('\ufeff')
    first_line = next(line for line in table.splitlines() if line.strip())
    reader = csv.reader(StringIO(table, newline=''), delimiter='\t' if '\t' in first_line else ',',
                        strict=True)
    result = []
    columns = None
    first = True
    try:
        for fields in reader:
            if not any(cell.strip() for cell in fields):
                continue
            if first:
                first = False
                titles = [HEADER_ALIASES.get(cell.strip().casefold(), cell.strip()) for cell in fields]
                columns_present = set(titles)
                if len(columns_present) == len(titles) and REQUIRED_HEADERS <= columns_present <= (REQUIRED_HEADERS|OPTIONAL_HEADERS):
                    columns = titles
                    continue
            if len(result) >= MAX_ACCOUNTS:
                raise HTTPException(422, '每批最多创建 100 个账号')
            # A headerless row follows the template order. Old files have four or five columns.
            order = columns or [*HEADERS,EMAIL_HEADER]
            missing = order[len(fields):]
            if len(fields)>len(order) or not set(missing)<=OPTIONAL_HEADERS:
                result.append((reader.line_num, None))
            else:
                cells = dict(zip(order, fields))
                values = [cells.get(column, '') for column in HEADERS]
                if EMAIL_HEADER in cells or (columns and EMAIL_HEADER in columns):
                    values.append(cells.get(EMAIL_HEADER,''))
                result.append((reader.line_num, values))
    except csv.Error as exc:
        raise HTTPException(422, f'第 {reader.line_num} 行格式有误，请核对分隔符或引号') from exc
    if not result:
        raise HTTPException(422, '账号表中没有人员')
    return result


def grant_values(value, aliases):
    tokens = [t.strip() for t in re.split(r'[,，、;；|\n]', value) if t.strip()]
    matches = [aliases.get(t, aliases.get(t.upper())) for t in tokens]
    valid = bool(matches) and all(matches)
    return list(dict.fromkeys(m for m in matches if m)), valid


def inspect_accounts(db, admin, table):
    rows = read_accounts(table)
    allowed = db.scalars(select(Warehouse).where(Warehouse.code.in_(admin.warehouses))).all()
    names = Counter(w.name for w in allowed)
    warehouse_aliases = {w.name:w.code for w in allowed if names[w.name] == 1}
    warehouse_aliases.update({w.code:w.code for w in allowed})
    roles = {**{v:k for k,v in ROLE_NAMES.items()}, **{k:k for k in ROLE_NAMES}, '复审':'REVIEWER', '复审人员':'REVIEWER', '系统管理':'ADMIN', 'ADMINISTRATOR':'ADMIN'}
    logins = Counter(fields[0].strip() for _,fields in rows if fields)
    existing = set(db.scalars(select(User.username).where(User.username.in_([n for n in logins if len(n)<=80]))))
    preview, accounts = [], []
    for line,fields in rows:
        if fields is None:
            preview.append({'line':line,'username':'','name':'','roles':[],'warehouses':[],
                            'issues':['请填写账号、姓名、初始密码和角色，授权仓库可留空']})
            continue
        username, name, password, role_text, warehouse_text, *email_cell = fields
        username, name = username.strip(), name.strip()
        role_ids, valid_roles = grant_values(role_text, roles)
        warehouse_ids, valid_warehouses = grant_values(warehouse_text, warehouse_aliases)
        issues = []
        if not 1 <= len(username) <= 80 or not username.isprintable():
            issues.append('账号需为 1–80 个可见字符')
        if username in existing:
            issues.append('账号已占用')
        if logins[username] > 1:
            issues.append('表内账号重复')
        if not 1 <= len(name) <= 255 or not name.isprintable():
            issues.append('请填写有效姓名（最多 255 字）')
        if not valid_password(password):
            issues.append('初始密码需为 6–200 位')
        if not valid_roles or len(role_ids)!=1:
            issues.append('请选择一个角色：计划员、复审员或管理员')
        if warehouse_text.strip() and not valid_warehouses:
            issues.append('请填写授权范围内的仓库名称或编码')
        public = {'username':username,'name':name,'roles':role_ids,'warehouses':warehouse_ids}
        if email_cell:
            try:
                public['email'] = normalize_email(email_cell[0])
            except ValueError as exc:
                issues.append(str(exc))
        preview.append({**public, 'line':line, 'issues':issues})
        if not issues:
            accounts.append({**public, 'password':password})
    return preview, accounts
