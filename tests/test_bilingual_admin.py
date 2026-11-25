import csv
from io import StringIO

from backend.account_import import read_accounts
from backend.adapters import ENGLISH_FIELDS, FIELDS, parse_file
from backend.governance import MASTER_FIELDS
from backend.master_import import collect_master, read_master
from backend.workbook_language import HEADERS
from test_api import P, clients


def test_english_accounts_accept_reordered_headers():
    entries = read_accounts('Role,Username,Authorized warehouses,Initial password,Name\nPLANNER,planner-test,UK_MAIN,initial-test,姓名原文')
    assert entries == [(2, ['planner-test', '姓名原文', 'initial-test', 'PLANNER', 'UK_MAIN'])]


def test_admin_csv_templates_round_trip_in_both_languages(clients):
    _, reviewer, _, _ = clients
    for language in ('zh','en'):
        english = language == 'en'
        for path, keys in [('/rules/master-template', ['material_code',*MASTER_FIELDS]), ('/template?kind=standard', list(FIELDS))]:
            response = reviewer.get(P + path, params={'lang':language, **({'kind':'standard'} if path.startswith('/template') else {})})
            assert response.status_code == 200
            header, = csv.reader(StringIO(response.content.decode('utf-8-sig')))
            assert len(header) == len(keys) and len(set(header)) == len(keys)
            assert header[0] == ('Material number' if english else '物料号')
            supplied = {'material_code':'P-512', 'material_name':'保留原文', 'replacement_rate':'0.1'}
            data = StringIO()
            writer = csv.writer(data)
            writer.writerow(header)
            writer.writerow(supplied.get(key,'') for key in keys)
            if path.startswith('/rules'):
                assert read_master(data.getvalue().encode(), 'master.csv') == {'P-512':{'material_name':'保留原文','replacement_rate':'0.1'}}
            else:
                parsed = parse_file(data.getvalue().encode(),'standard.csv')
                assert not parsed['issues']
                assert all(parsed['items'][0][key] == value for key,value in supplied.items())


def test_custom_mapping_takes_precedence_over_english_template_label():
    english_header = ENGLISH_FIELDS['material_code']
    parsed = parse_file((english_header+',SKU\nwrong,correct').encode(),'custom.csv',mapping={'material_code':'SKU'})
    assert parsed['items'][0]['material_code'] == 'correct'


def test_master_import_recognizes_bilingual_v3_headers():
    keys = ('物料号', '物料名称', '目标库存-稳态更换率')
    headers = [HEADERS[zh]+'\n'+zh for zh in keys]
    items = collect_master(iter([headers, ['01A', '原文', 2]]))
    assert items == {'01A':{'material_name':'原文', 'replacement_target':'2'}}
