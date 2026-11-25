"""Optional server-to-server events for a company-operated Umami instance."""
import http.client
import json
import logging
import os
from urllib.parse import urlsplit
from uuid import UUID


def _destination():
    address = os.environ.get('PLAN_REVIEW_UMAMI_URL', '').strip()
    website = os.environ.get('PLAN_REVIEW_UMAMI_WEBSITE_ID', '').strip()
    if not address or not website:
        return None
    try:
        url = urlsplit(address)
        website = str(UUID(website))
        if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
            return None
        return url.scheme, url.hostname, url.port, url.path.rstrip('/') + '/api/batch', website
    except ValueError:
        return None


def umami_enabled():
    return _destination() is not None


def forward_usage(events):
    destination = _destination()
    if not destination:
        return
    scheme, host, port, path, website = destination
    batch = []
    for event in events:
        if event.kind == 'pulse':
            continue
        payload = {'website': website, 'hostname': 'plan-review', 'url': '/plan-review/' + event.page}
        if event.kind != 'view':
            payload['name'] = event.kind + '.' + event.target
            payload['data'] = {'device': event.device}
            if event.kind == 'click':
                payload['data'].update(column=event.x, row=event.y)
        batch.append({'type': 'event', 'payload': payload})
    if not batch:
        return
    connection_type = http.client.HTTPSConnection if scheme == 'https' else http.client.HTTPConnection
    connection = connection_type(host, port=port, timeout=2)
    try:
        connection.request('POST', path, body=json.dumps(batch).encode('utf-8'),
                           headers={'Content-Type': 'application/json', 'User-Agent': 'EASPhub-PlanReview/2.2'})
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            logging.getLogger(__name__).warning('Umami event delivery returned HTTP %s', response.status)
        else:
            result = json.loads(response.read(65536))
            if not isinstance(result, dict) or result.get('processed') != len(batch) or result.get('errors'):
                logging.getLogger(__name__).warning('Umami did not acknowledge all %s product events', len(batch))
    except (OSError, ValueError, http.client.HTTPException):
        logging.getLogger(__name__).warning('Umami collector unavailable')
    finally:
        connection.close()
