import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

from backend.usage import UsageEvent
from backend.usage_umami import forward_usage, umami_enabled


def test_optional_umami_posts_only_product_dimensions(monkeypatch):
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, json.loads(self.rfile.read(int(self.headers['content-length'])))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'processed':len(received[-1][1]),'errors':0}).encode())

        def log_message(self, *args):
            pass

    monkeypatch.delenv('PLAN_REVIEW_UMAMI_URL', raising=False)
    monkeypatch.delenv('PLAN_REVIEW_UMAMI_WEBSITE_ID', raising=False)
    assert not umami_enabled()
    website = str(uuid4())
    with HTTPServer(('127.0.0.1', 0), Receiver) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setenv('PLAN_REVIEW_UMAMI_URL', f'http://127.0.0.1:{server.server_port}/stats')
            monkeypatch.setenv('PLAN_REVIEW_UMAMI_WEBSITE_ID', website)
            assert umami_enabled()
            events = [UsageEvent(kind='view', page='detail', device='desktop'),
                      UsageEvent(kind='pulse', page='detail', device='desktop'),
                      UsageEvent(kind='click', page='detail', device='desktop', target='submit', x=2, y=4)]
            forward_usage(events)
        finally:
            server.shutdown()
            thread.join()
    common = {'website': website, 'hostname': 'plan-review', 'url': '/plan-review/detail'}
    assert received == [('/stats/api/batch', [
        {'type': 'event', 'payload': common},
        {'type': 'event', 'payload': {**common, 'name': 'click.submit', 'data': {'device': 'desktop', 'column': 2, 'row': 4}}}])]
