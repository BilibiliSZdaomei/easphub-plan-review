"""Run the existing workers with progress-based health and bounded shutdown."""
import json
import os
from pathlib import Path
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import init_db
from backend.jobs import start_workers, WORKER_PROGRESS


def main():
    os.umask(0o077)
    init_db()
    heartbeat = Path(os.environ.get('PLAN_REVIEW_HEARTBEAT_FILE', '/tmp/plan-review-worker.json'))
    stop, threads = start_workers()
    job_threads = [thread for thread in threads if thread.name != 'workflow-smtp']
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: stop.set())
    try:
        while not stop.is_set():
            payload = {'pid': os.getpid(), 'written_at': time.time(), 'workers': [
                {'alive': thread.is_alive(), 'progress': WORKER_PROGRESS.get(thread.ident, 0)}
                for thread in job_threads]}
            temporary = heartbeat.with_suffix('.tmp')
            temporary.write_text(json.dumps(payload), encoding='utf-8')
            temporary.replace(heartbeat)
            if not all(thread.is_alive() for thread in threads):
                stop.set()
            stop.wait(1)
    finally:
        stop.set()
        deadline = time.monotonic() + 25
        for thread in threads:
            thread.join(max(0, deadline - time.monotonic()))
        heartbeat.unlink(missing_ok=True)
    return int(any(thread.is_alive() for thread in threads))


if __name__ == '__main__':
    sys.exit(main())
