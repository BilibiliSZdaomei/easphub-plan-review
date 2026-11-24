"""Synthetic acceptance fixture. Never use this script to serve business data."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from artifact_paths import artifact_root

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP_ID = 'plan-review'


def prepare(ui):
    work = artifact_root(ROOT, APP_ID)
    work.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(prefix='synthetic-', dir=work)
    directory = Path(temporary.name)
    data = directory/'data'
    data.mkdir()
    shutil.copytree(Path(ui).resolve(), directory/'ui')
    for name in list(os.environ):
        if name.startswith(('PLAN_REVIEW_', 'DELAY_')):
            os.environ.pop(name)
    os.environ.update(APP_BASE_PATH='/apps/'+APP_ID, APP_DATA_DIR=str(data), DEPLOY_ENV='test', TZ='Europe/Budapest')
    if APP_ID == 'plan-review':
        os.environ.update(PLAN_REVIEW_DEMO='0', PLAN_REVIEW_WORKER='0', PLAN_REVIEW_UI_DIR=str(directory/'ui'), PLAN_REVIEW_DATABASE_URL='sqlite:///'+str(data/'synthetic.sqlite3'), PLAN_REVIEW_HEARTBEAT_FILE=str(directory/'worker.json'))
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'], cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        from backend.db import transaction
        from backend.demo import seed_demo
        with transaction() as database:
            seed_demo(database)
        from backend.api import app
    else:
        token = directory/'session-token'
        token.write_text(secrets.token_urlsafe(48), encoding='utf-8')
        os.environ.update(DELAY_SESSION_TOKEN_FILE=str(token), DELAY_UI_DIR=str(directory/'ui'))
        from order_processing.deployment import create_server_app
        app = create_server_app()
    return app, temporary, directory


def certificate(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic localhost acceptance')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()))
    key_file, cert_file = directory/'test-key.pem', directory/'test-ca.pem'
    key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key_file, cert_file


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui-dir', required=True)
    parser.add_argument('--state-file', required=True)
    args = parser.parse_args()
    app, temporary, directory = prepare(args.ui_dir)
    key, cert = certificate(directory)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1',0))
        port = reservation.getsockname()[1]
    state = {'app':APP_ID,'url':f'https://127.0.0.1:{port}/apps/{APP_ID}/','ca_file':str(cert),'synthetic_data':str(directory),'pid':os.getpid()}
    state_path = Path(args.state_file).resolve()
    if not state_path.is_relative_to(artifact_root(ROOT, APP_ID)):
        raise SystemExit('The test state file must stay inside the external artifact workspace')
    state_path.write_text(json.dumps(state,ensure_ascii=False), encoding='utf-8')
    print(json.dumps(state,ensure_ascii=False),flush=True)
    import uvicorn
    try:
        uvicorn.run(app,host='127.0.0.1',port=port,ssl_keyfile=str(key),ssl_certfile=str(cert),access_log=False,proxy_headers=False)
    finally:
        if APP_ID == 'plan-review':
            from backend.db import engine
            engine.dispose()
        temporary.cleanup()
