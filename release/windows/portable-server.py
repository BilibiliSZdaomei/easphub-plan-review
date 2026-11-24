"""Run one managed desktop instance on loopback."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn


def open_when_ready(url):
    for _ in range(100):
        try:
            with urlopen(url + 'api/v1/health', timeout=1) as response:
                if json.load(response).get('status') == 'ok':
                    webbrowser.open(url)
                    return
        except (OSError, URLError, ValueError):
            pass
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    for key in ('PLAN_REVIEW_DATABASE_URL', 'PLAN_REVIEW_DATABASE_URL_FILE', 'PLAN_REVIEW_DB_PASSWORD_FILE'):
        os.environ.pop(key, None)
    os.environ.update(APP_DATA_DIR=str(args.data.resolve()), PLAN_REVIEW_DATA=str(args.data.resolve()),
                      PLAN_REVIEW_DEMO='0', PLAN_REVIEW_WORKER='1', PLAN_REVIEW_DESKTOP_LOOPBACK='1',
                      DEPLOY_ENV='local', APP_BASE_PATH='/plan-review', PLAN_REVIEW_UI_DIR=str(root/'frontend'/'dist'))
    config = uvicorn.Config('backend.api:app', host='127.0.0.1', port=args.port, access_log=False)
    with config.bind_socket() as listener:
        if not args.no_browser:
            url = f'http://127.0.0.1:{args.port}/plan-review/'
            threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
        uvicorn.Server(config).run(sockets=[listener])


if __name__ == '__main__':
    main()
