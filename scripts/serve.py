"""Detached, loopback-only local entry point; normal data persists across launches."""
import argparse,os,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--desktop',action='store_true',required=True);p.add_argument('--data',required=True);args=p.parse_args()
root=Path(__file__).resolve().parents[1];os.chdir(root);sys.path.insert(0,str(root))
data=Path(args.data).resolve();data.mkdir(parents=True,exist_ok=True)
os.environ.update(APP_DATA_DIR=str(data), PLAN_REVIEW_DATA=str(data), PLAN_REVIEW_DEMO='0',
                  PLAN_REVIEW_WORKER='1', PLAN_REVIEW_DESKTOP_LOOPBACK='1', DEPLOY_ENV='local', APP_BASE_PATH='/plan-review')
for key in ('PLAN_REVIEW_DATABASE_URL', 'PLAN_REVIEW_DATABASE_URL_FILE', 'PLAN_REVIEW_DB_PASSWORD_FILE'):
    os.environ.pop(key,None)
sys.stdout=open(data/'server.stdout.log','a',encoding='utf-8',buffering=1)
sys.stderr=open(data/'server.stderr.log','a',encoding='utf-8',buffering=1)
import uvicorn
uvicorn.run('backend.api:app',host='127.0.0.1',port=3350,access_log=False)
