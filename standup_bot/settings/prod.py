import dj_database_url
from .base import *

DEBUG = False

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

DATABASES = {
    'default': dj_database_url.config(
        default=config('DATABASE_URL'),
        conn_max_age=60,
    )
}

CELERY_BROKER_URL = config('REDIS_URL', default='redis://localhost:6379/0')

# Railway handles SSL at the proxy level — do not redirect internally
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
