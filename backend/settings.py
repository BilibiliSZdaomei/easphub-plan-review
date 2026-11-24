"""Deployment configuration; local defaults remain compatible with the launcher."""
import os
import re
from pathlib import Path


def base_path(value=None):
    value = os.environ.get('APP_BASE_PATH', '/plan-review') if value is None else value
    if not re.fullmatch(r'/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*', value):
        raise ValueError('APP_BASE_PATH must be an absolute prefix without a trailing slash')
    return value


BASE_PATH = base_path()
API_PREFIX = BASE_PATH + '/api/v1'
DEPLOY_ENV = os.environ.get('DEPLOY_ENV', 'local')


def read_secret(name):
    filename = os.environ.get(name)
    if not filename:
        raise ValueError(name + ' is required')
    try:
        value = Path(filename).read_text(encoding='utf-8').rstrip('\r\n')
    except OSError:
        raise ValueError(name + ' cannot be read') from None
    if not value or '\n' in value or '\r' in value:
        raise ValueError(name + ' must contain one nonempty line')
    return value


def data_directory():
    value = os.environ.get('APP_DATA_DIR') or os.environ.get('PLAN_REVIEW_DATA')
    if DEPLOY_ENV in ('home', 'company') and not value:
        raise ValueError('APP_DATA_DIR is required')
    return Path(value) if value else Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share')))/'PlanReview'/'data'


def database_url(data):
    choices = [key for key in ('PLAN_REVIEW_DATABASE_URL', 'PLAN_REVIEW_DATABASE_URL_FILE', 'PLAN_REVIEW_DB_PASSWORD_FILE') if os.environ.get(key)]
    if len(choices) > 1:
        raise ValueError('Configure only one database connection source')
    if os.environ.get('PLAN_REVIEW_DATABASE_URL_FILE'):
        return read_secret('PLAN_REVIEW_DATABASE_URL_FILE')
    if os.environ.get('PLAN_REVIEW_DATABASE_URL'):
        return os.environ['PLAN_REVIEW_DATABASE_URL']
    if os.environ.get('PLAN_REVIEW_DB_PASSWORD_FILE'):
        from sqlalchemy.engine import URL
        values = {}
        for name in ('HOST', 'NAME', 'USER'):
            value = os.environ.get('PLAN_REVIEW_DB_' + name)
            if not value:
                raise ValueError('PLAN_REVIEW_DB_' + name + ' is required')
            values[name] = value
        return URL.create('mysql+pymysql', username=values['USER'], password=read_secret('PLAN_REVIEW_DB_PASSWORD_FILE'), host=values['HOST'], port=3306, database=values['NAME'], query={'charset':'utf8mb4'}).render_as_string(hide_password=False)
    if DEPLOY_ENV in ('home', 'company'):
        raise ValueError('An explicit database connection is required; no production fallback')
    return 'sqlite:///' + str(data/'plan-review.sqlite3')
