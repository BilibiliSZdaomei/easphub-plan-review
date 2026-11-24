"""Production launcher; migrations and account bootstrap are explicit jobs."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn

if __name__ == '__main__':
    os.umask(0o077)
    if os.environ.get('DEPLOY_ENV') not in ('home','company','test'):
        sys.exit('DEPLOY_ENV must be home, company or test')
    if os.environ.get('PLAN_REVIEW_DEMO','0') != '0':
        sys.exit('The container launcher does not allow demo mode')
    if not os.environ.get('TZ'):
        sys.exit('TZ is required')
    from backend.api import app
    uvicorn.run(app, host=os.environ.get('HOST','0.0.0.0'), port=int(os.environ.get('PORT','3350')), workers=1, access_log=False, proxy_headers=False, timeout_graceful_shutdown=30)
