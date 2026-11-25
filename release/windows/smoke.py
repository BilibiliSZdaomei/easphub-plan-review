"""Exercise a freshly extracted offline release, using a new workspace and port."""
import argparse
from hashlib import sha256
from http.cookiejar import CookieJar
from io import BytesIO
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import time
from urllib.error import URLError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from xml.etree import ElementTree
import zipfile


def smoke(archive, workdir):
    archive = archive.resolve()
    workdir = workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Damaged ZIP')
        for name in z.namelist():
            if (not name.startswith('PlanReview-Windows-x64/') or '..' in Path(name).parts or
                    name.lower().endswith(('.db','.sqlite3','.clixml','.env','.log','.pem','.key','.pyc','.pyo'))):
                raise ValueError(f'Unexpected archive entry {name}')
        z.extractall(workdir/'解压 smoke')
    app = workdir/'解压 smoke'/'PlanReview-Windows-x64'
    data = workdir/'业务数据'
    data.mkdir()
    system_root = Path(os.environ['SystemRoot'])
    shell = system_root/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    # Restrict PATH and point all desktop writes to this test workspace.
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(('PYTHON','PLAN_REVIEW','VIRTUAL_ENV','APP_BASE_PATH','DEPLOY_ENV')):
            env.pop(key)
    env['PATH'] = os.pathsep.join([str(shell.parent),str(system_root/'System32'),str(system_root)])
    env['PSMODULEPATH'] = str(shell.parent/'Modules')
    env['PLAN_REVIEW_DESKTOP_DATA'] = str(data)
    versions = json.loads((app/'versions.json').read_text(encoding='utf-8'))
    check_script = app/'scripts'/'verify-package.ps1'
    template = app/'backend'/'templates'/'replenishment-plan.xlsx'
    withheld = workdir/'withheld-for-integrity-test.xlsx'
    template.rename(withheld)
    try:
        incomplete = subprocess.run([str(shell),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(check_script)],
                                    env=env,capture_output=True,timeout=45)
        assert incomplete.returncode != 0 and b'replenishment-plan.xlsx' in incomplete.stderr
    finally:
        withheld.rename(template)
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0))
        port = probe.getsockname()[1]
    if port == 3350:
        raise RuntimeError('Smoke port must differ from the working environment')
    env['PLAN_REVIEW_PORT'] = str(port)
    url = f'http://127.0.0.1:{port}/plan-review/'
    client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))

    def fetch(path, body=None, headers=None, method=None):
        req = Request(url+path, json.dumps(body).encode() if body is not None else None,
                      headers or {}, method=method)
        with client.open(req, timeout=4) as result:
            return result.read()

    # Exercise the same CMD entry point that an operator double-clicks.
    for trial in range(2):
        with (workdir/f'run-{trial}.log').open('wb') as log:
            process = subprocess.Popen([str(system_root/'System32'/'cmd.exe'), '/D','/C','Start.cmd','-NoBrowser'],
                                        cwd=app, env=env, stdin=subprocess.DEVNULL,
                                        stdout=log, stderr=log, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            try:
                for _ in range(180):
                    if process.poll() is not None:
                        raise RuntimeError(f'Launcher exited ({process.returncode}); inspect run-{trial}.log')
                    try:
                        health = json.loads(fetch('api/v1/health'))
                        if health.get('status') == 'ok':
                            break
                    except (OSError,URLError):
                        pass
                    time.sleep(.25)
                else:
                    raise TimeoutError('Desktop health endpoint did not become ready')
                assert health['version'] == versions['version'] and not health['demo'] and health['database']=='sqlite'
                ui_manifest = json.loads((app/'frontend'/'dist'/'app-build.json').read_text(encoding='utf-8'))
                assert ui_manifest['version'] == versions['version']
                page = fetch('').decode()
                assets = re.findall(r'(?:src|href)="(/plan-review/[^"]+)"',page)
                assert len(assets)>=2
                assert all(fetch(a.removeprefix('/plan-review/')) for a in assets)
                card = data/'initial-admin.clixml'
                assert card.is_file()
                if trial == 0:
                    saved_card = sha256(card.read_bytes()).digest()
                else:
                    assert sha256(card.read_bytes()).digest() == saved_card
                cmd = '$c=Import-Clixml -LiteralPath $env:SMOKE_CARD; @{username=$c.UserName;password=$c.GetNetworkCredential().Password}|ConvertTo-Json -Compress'
                login_body = json.loads(subprocess.check_output([str(shell),'-NoProfile','-Command',cmd],
                                           env={**env,'SMOKE_CARD':str(card)}))
                session = json.loads(fetch('api/v1/sessions',login_body,{'Content-Type':'application/json'}))
                assert session['user']['roles'] == ['ADMIN']
                assert len(json.loads(fetch('api/v1/warehouses'))) == 10
                assert json.loads(fetch('api/v1/snapshots')) == []
                assert json.loads(fetch('api/v1/batches')) == []
                for kind, name in [('plan','replenishment-plan.xlsx'),('v2','plan-review-v2.xlsx')]:
                    payload = fetch('api/v1/template?kind='+kind)
                    assert payload == (app/'backend'/'templates'/name).read_bytes()
                    with zipfile.ZipFile(BytesIO(payload)) as xlsx:
                        assert xlsx.testzip() is None
                        assert 'xl/workbook.xml' in xlsx.namelist()
                        if kind == 'plan':
                            for comments in ('xl/comments/comment1.xml','xl/comments/comment2.xml'):
                                assert len(ElementTree.fromstring(xlsx.read(comments)).findall('.//{*}comment')) == 7
                payload = fetch('api/v1/template?kind=v3&period=2026-02')
                with zipfile.ZipFile(BytesIO(payload)) as xlsx:
                    assert xlsx.testzip() is None
                    with xlsx.open('xl/worksheets/sheet1.xml') as sheet:
                        header = next(element for _, element in ElementTree.iterparse(sheet) if element.tag.endswith('}row'))
                    header_text = {cell.get('r'): ''.join(cell.itertext()) for cell in header}
                    months = ('2025-08','2025-09','2025-10','2025-11','2025-12','2026-01')
                    assert [header_text[column+'1'] for column in 'NOPQRS'] == [month+' 销量' for month in months]
                    assert len(ElementTree.fromstring(xlsx.read('xl/comments/comment1.xml')).findall('.//{*}comment')) == 43
                assert '物料号' in fetch('api/v1/template?kind=standard').decode('utf-8-sig')
                with zipfile.ZipFile(BytesIO(fetch('api/v1/template?kind=v3&period=2026-02&lang=en'))) as english:
                    assert english.testzip() is None
                    with english.open('xl/worksheets/sheet1.xml') as sheet:
                        header = next(node for _, node in ElementTree.iterparse(sheet) if node.tag.endswith('}row'))
                    assert 'Material number' in ''.join(header.itertext())
                assert len(json.loads(fetch('api/v1/usage/insights?scope=team'))['trend']) == 7
                assert json.loads(fetch('api/v1/mail-delivery/status'))['smtp_configured'] is False
                fetch('api/v1/sessions/current',headers={'X-CSRF-Token':session['csrf']},method='DELETE')
                with sqlite3.connect((data/'plan-review.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                    assert db.execute('SELECT count(*) FROM users').fetchone()[0] == 1
                    assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('0013',)
                    assert db.execute('SELECT count(*) FROM workflow_mail').fetchone() == (0,)
                    assert db.execute("SELECT json_extract(package,'$.model') FROM rules WHERE active=1").fetchall() == [('V3',)]
            finally:
                if process.poll() is None:
                    try:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                        process.wait(7)
                    except (OSError,subprocess.TimeoutExpired):
                        # This PID was launched above solely for the test.
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,check=False)
                        process.wait(5)
            for _ in range(50):
                with socket.socket() as check:
                    if check.connect_ex(('127.0.0.1',port)) != 0:
                        break
                time.sleep(.1)
            else:
                raise RuntimeError('Smoke server did not stop')
    # Use only the account created by the isolated two-launch test above.
    recovered = workdir/'restored-workspace'
    bundle = workdir/'synthetic-accounts.easphub'
    key = workdir/'synthetic-accounts.key'
    subprocess.run([str(app/'runtime'/'python.exe'), '-B', str(app/'scripts'/'restore_accounts.py'),
                    'export', '--sqlite', str(data/'plan-review.sqlite3'), '--bundle', str(bundle),
                    '--key-file', str(key)], env=env, cwd=app, check=True, capture_output=True)
    for _ in range(2):
        subprocess.run([str(shell), '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                        str(app/'scripts'/'restore-accounts.ps1'), '-DataDirectory', str(recovered),
                        '-Bundle', str(bundle), '-KeyFile', str(key)], env=env, cwd=app, check=True, capture_output=True)
    def account_rows(directory):
        with sqlite3.connect((directory/'plan-review.sqlite3').as_uri()+'?mode=ro',uri=True) as conn:
            return conn.execute('SELECT id, username, password_hash, roles, warehouses FROM users ORDER BY id').fetchall()
    assert account_rows(data) == account_rows(recovered)
    print(json.dumps({'two_launches': True,'empty_snapshot_list': True,'warehouses':10,'accounts':1,
                      'version':health['version'],'python':json.loads((app/'versions.json').read_text())['python'],
                      'template_and_assets':'plan,v2,v3,standard,v3-en','schema':'0013','fresh_rule':'V3',
                      'admin_usage': True,'smtp_status': True,'account_restore':'two imports matched original',
                      'port':port,'size':archive.stat().st_size,
                      'sha256':sha256(archive.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('new_workdir',type=Path)
    args = parser.parse_args()
    smoke(args.archive,args.new_workdir)
