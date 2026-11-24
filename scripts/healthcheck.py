"""Exit nonzero for an unavailable HTTP dependency or stalled worker."""
import json
import os
from pathlib import Path
import sys
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else 'ready'
        if mode == 'worker':
            from backend.health import check_database, check_files
            check_database()
            check_files()
            heartbeat = Path(os.environ.get('PLAN_REVIEW_HEARTBEAT_FILE', '/tmp/plan-review-worker.json'))
            payload = json.loads(heartbeat.read_text(encoding='utf-8'))
            current = time.time()
            assert 0 <= current - payload['written_at'] < 10
            assert len(payload['workers']) == 2
            assert all(worker['alive'] and 0 <= current - worker['progress'] < 360 for worker in payload['workers'])
        else:
            assert mode in ('live', 'ready')
            port = int(os.environ.get('PORT', '3350'))
            with urlopen(f'http://127.0.0.1:{port}/health/{mode}', timeout=4) as response:
                payload = json.load(response)
                assert response.status == 200 and payload == {'status':'ok', 'app':'plan-review'}
        return 0
    except Exception:
        print('healthcheck failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
