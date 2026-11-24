"""Markets served by the European planning team and their warehouse registration."""
import json
from pathlib import Path

from sqlalchemy import select

from .db import Warehouse

EUROPE = 'EUROPE'
LEGACY_DEFAULT = 'UK'
EUROPE_RULE_NAME = '欧洲通用标准 · V2'
MARKET_NAMES = {
    'NL': '荷兰', 'UK': '英国', 'DE': '德国', 'IT': '意大利', 'FR': '法国',
    'ES': '西班牙', 'PL': '波兰', 'CH': '瑞士', 'SE': '瑞典', 'UZ': '乌兹别克斯坦',
}
CATALOG = Path(__file__).resolve().parents[1] / 'deploy' / 'warehouses.example.json'


def market_key(market):
    key = str(market).strip().upper()
    return 'UK' if key == 'GB' else key


def applies_to(scope, code, warehouse):
    if scope == 'WAREHOUSE':
        return warehouse.code == code
    if scope == 'MARKET':
        return warehouse.market == code
    return scope == 'DEFAULT' and (code == LEGACY_DEFAULT or
                                   (code == EUROPE and market_key(warehouse.market) in MARKET_NAMES))


def superseded_codes(scope, code, warehouses):
    if scope == 'DEFAULT' and code == EUROPE and all(applies_to(scope, code, w) for w in warehouses):
        return (EUROPE, LEGACY_DEFAULT)
    return (code,)


def rule_scopes(warehouse):
    scopes = [('WAREHOUSE', warehouse.code), ('MARKET', warehouse.market)]
    if applies_to('DEFAULT', EUROPE, warehouse):
        scopes.append(('DEFAULT', EUROPE))
    return [*scopes, ('DEFAULT', LEGACY_DEFAULT)]


def warehouse_config(path=CATALOG):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def register_markets(db, config):
    """Fill unregistered markets. Existing warehouse codes and names belong to the installation."""
    if not isinstance(config, list) or not config:
        raise ValueError('仓库清单不能为空')
    rows = []
    codes = set()
    for entry in config:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('market', 'code', 'name')):
            raise ValueError('仓库需要 code、name 和 market')
        row = {k: entry[k].strip() for k in ('market', 'code', 'name')}
        if row['code'] in codes:
            raise ValueError('仓库编码重复：' + row['code'])
        codes.add(row['code'])
        rows.append(row)
    existing = {w.code: w for w in db.scalars(select(Warehouse))}
    occupied = {market_key(w.market) for w in existing.values()}
    requested = {market_key(w['market']) for w in rows}
    added = []
    for row in rows:
        market, code = market_key(row['market']), row['code']
        if code in existing and market_key(existing[code].market) != market:
            raise ValueError('仓库编码已属于其他市场：' + code)
        if market not in occupied:
            warehouse = Warehouse(**row)
            db.add(warehouse)
            existing[code] = warehouse
            added.append(code)
    db.flush()
    return [w for w in existing.values() if market_key(w.market) in requested], added
