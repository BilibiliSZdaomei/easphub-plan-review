"""Read-only HTTP smoke test. Use only an explicitly authorized URL."""
import argparse
from http.cookiejar import CookieJar
import json
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import build_opener, HTTPCookieProcessor, HTTPSHandler, HTTPRedirectHandler

APP_ID = 'plan-review'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Full application URL, including its prefix and trailing slash')
    parser.add_argument('--ca-file', help='Optional CA for an isolated TLS fixture')
    parser.add_argument('--gateway', action='store_true', help='Do not request container-only root health paths')
    args = parser.parse_args()
    base = args.url
    parts = urlsplit(base)
    prefix = '/apps/'+APP_ID+'/'
    if parts.path != prefix or parts.query or parts.fragment or parts.username:
        raise SystemExit('Use a clean full application URL with the registered prefix')
    tls = ssl.create_default_context(cafile=args.ca_file)
    jar = CookieJar()
    client = build_opener(HTTPSHandler(context=tls), HTTPCookieProcessor(jar))
    direct = build_opener(HTTPSHandler(context=tls), NoRedirect())
    checks = []
    query = '?next=%2Fspace%20value&x=1'
    try:
        direct.open(base.rstrip('/')+query, timeout=10)
        raise AssertionError('Missing slash redirect was not returned')
    except HTTPError as response:
        assert response.code in (307,308)
        assert response.headers['Location'] == prefix+query
    checks.append('slash_redirect_preserves_query')
    with client.open(base,timeout=10) as response:
        assert response.status == 200
        html = response.read().decode('utf-8')
    resources = re.findall(r'(?:src|href)=["\']([^"\']+)["\']',html)
    resources = [url for url in resources if '/assets/' in url or url.endswith(('.svg','.png','.ico'))]
    assert resources and any('/assets/' in url for url in resources)
    for url in resources:
        assert url.startswith(prefix), url
        with client.open(urljoin(base,url),timeout=10) as response:
            assert response.status == 200 and response.read()
            assert 'text/html' not in response.headers.get('Content-Type','')
    checks.append('html_and_real_assets')
    with client.open(base+'acceptance-refresh?view=test',timeout=10) as response:
        assert response.status == 200 and response.read().decode('utf-8') == html
    checks.append('nested_refresh')
    api = 'api/v1/session-state' if APP_ID=='plan-review' else 'api/bootstrap'
    with client.open(base+api,timeout=10) as response:
        payload = json.load(response)
        assert response.status == 200
        assert 'user' in payload if APP_ID=='plan-review' else payload['app_version']=='2.3.0'
    checks.append('prefixed_api')
    for cookie in jar:
        assert cookie.path == prefix.rstrip('/')
    if not args.gateway:
        origin = parts.scheme+'://'+parts.netloc
        for mode in ('live','ready'):
            with client.open(origin+'/health/'+mode,timeout=10) as response:
                assert response.status == 200 and json.load(response)=={'status':'ok','app':APP_ID}
        checks.append('internal_liveness_and_readiness')
    print(json.dumps({'status':'PASS','app':APP_ID,'checks':checks,'internal_health':'NOT_RUN' if args.gateway else 'PASS','identity_authentication':'NOT_RUN' if APP_ID=='plan-review' else 'N/A: existing server mode has no identity authentication'},ensure_ascii=False))


if __name__ == '__main__':
    main()
