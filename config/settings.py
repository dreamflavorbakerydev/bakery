import os
import secrets
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
env_file = BASE_DIR / ('.env' if (BASE_DIR / '.env').exists() else '.env.local')
load_dotenv(env_file)
IS_VERCEL = os.environ.get('VERCEL') == '1' or any(
    os.environ.get(name) for name in ('VERCEL_ENV', 'VERCEL_URL')
)
DEBUG = os.environ.get('DJANGO_DEBUG', '0' if IS_VERCEL else '1') == '1'
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('Set DJANGO_SECRET_KEY when DJANGO_DEBUG=0.')
    # Stable for this local checkout, without embedding a shared secret in code.
    secret_file = BASE_DIR / '.django-secret'
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(64), encoding='utf-8')
    SECRET_KEY = secret_file.read_text(encoding='utf-8').strip()
ALLOWED_HOSTS = [host.strip() for host in os.environ.get(
    'DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],bakery.elaineanderic.com'
).split(',') if host.strip()]
for vercel_host in (
    os.environ.get('VERCEL_URL'),
    os.environ.get('VERCEL_PROJECT_PRODUCTION_URL'),
    '.dream-flavor-bakery.vercel.app',
    'bakery-tau-brown.vercel.app',
):
    if vercel_host and vercel_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(vercel_host)
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get(
    'DJANGO_CSRF_TRUSTED_ORIGINS', 'https://bakery.elaineanderic.com'
).split(',') if origin.strip()]
INSTALLED_APPS = [
    'django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes',
    'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles',
    'bakery.apps.BakeryConfig',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True, 'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages', 'bakery.context_processors.navigation',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    raise ImproperlyConfigured('Set DATABASE_URL to the Neon PostgreSQL connection string.')
DATABASES = {'default': dj_database_url.parse(
    DATABASE_URL,
    conn_max_age=600,
    conn_health_checks=True,
)}
if DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise ImproperlyConfigured('DATABASE_URL must use PostgreSQL; SQLite is not supported.')
if os.environ.get('DJANGO_TEST_DATABASE_NAME'):
    DATABASES['default'].setdefault('TEST', {})['NAME'] = os.environ['DJANGO_TEST_DATABASE_NAME']
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
