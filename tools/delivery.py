"""CI deployment entry points. No branch deletion, database reset, or rollback."""

import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATION_LOCK = 734917238123
# Unknown, data, destructive, and non-atomic operations require a separate review.
SAFE_OPERATIONS = {
    'CreateModel', 'AddField', 'AddIndex', 'AddConstraint',
    'AlterModelOptions', 'AlterModelManagers', 'AlterModelTableComment',
}


def require(*names):
    missing = [name for name in names if not os.environ.get(name, '').strip()]
    if missing:
        raise ValueError('Missing configuration names: ' + ', '.join(missing))


def database_identity(value, *, direct=False):
    parsed = urlsplit(value)
    if parsed.scheme not in {'postgres', 'postgresql'} or not parsed.hostname:
        raise ValueError('Expected a PostgreSQL connection URL.')
    if parsed.fragment or '\n' in value or '\r' in value:
        raise ValueError('Invalid database URL.')
    query = parse_qs(parsed.query, keep_blank_values=True)
    # Reject libpq options that could override the reviewed target/transport.
    if set(query) - {'sslmode', 'channel_binding', 'connect_timeout', 'sslrootcert'}:
        raise ValueError('Database URL contains unsupported connection options.')
    if any(len(values) != 1 for values in query.values()):
        raise ValueError('Repeated database connection options are forbidden.')
    if query.get('sslmode', [''])[0] not in {
        'require', 'verify-ca', 'verify-full',
    }:
        raise ValueError('Remote database connections must require TLS.')
    if direct and '-pooler.' in parsed.hostname:
        raise ValueError('Migrations require the direct, unpooled endpoint.')
    database = unquote(parsed.path.removeprefix('/'))
    if not database or '/' in database:
        raise ValueError('Expected an explicit database name.')
    return parsed.hostname.replace('-pooler.', '.'), database


def preflight_preview():
    require('VERCEL_ORG_ID', 'VERCEL_PROJECT_ID', 'VERCEL_TOKEN',
            'VERCEL_PRODUCTION_PROJECT_ID',
            'DJANGO_SECRET_KEY', 'NEON_PREVIEW_PROJECT_ID',
            'NEON_PRODUCTION_PROJECT_ID', 'NEON_PREVIEW_PARENT_BRANCH_ID',
            'NEON_DATABASE', 'NEON_ROLE')
    if os.environ['NEON_PREVIEW_PROJECT_ID'] == os.environ['NEON_PRODUCTION_PROJECT_ID']:
        raise ValueError('Preview and production must use separate Neon projects.')
    if os.environ['VERCEL_PROJECT_ID'] == os.environ['VERCEL_PRODUCTION_PROJECT_ID']:
        raise ValueError('Preview and production must use separate Vercel projects.')


def preflight_production():
    require('VERCEL_ORG_ID', 'VERCEL_PROJECT_ID', 'VERCEL_TOKEN',
            'DJANGO_SECRET_KEY', 'DATABASE_URL', 'DATABASE_URL_DIRECT',
            'PRODUCTION_DATABASE_HOST', 'PRODUCTION_DATABASE_NAME')
    expected = (os.environ['PRODUCTION_DATABASE_HOST'],
                os.environ['PRODUCTION_DATABASE_NAME'])
    runtime = database_identity(os.environ['DATABASE_URL'])
    migration = database_identity(os.environ['DATABASE_URL_DIRECT'], direct=True)
    if runtime != expected or migration != expected:
        raise ValueError('Production endpoints do not match the approved host/database.')


def validate_plan(plan):
    """Fail closed before any migration executes; only additive schema changes."""
    from django.db.migrations import operations as django_operations
    allowed_types = {getattr(django_operations, name) for name in SAFE_OPERATIONS}
    rejected = []
    for migration, backwards in plan:
        name = f'{migration.app_label}.{migration.name}'
        if backwards or not migration.atomic:
            rejected.append(name + ': backwards or non-atomic migration')
        for operation in migration.operations:
            if type(operation) not in allowed_types:
                rejected.append(name + ': ' + type(operation).__name__)
    if rejected:
        raise ValueError('Production migration requires separate review; blocked: '
                         + '; '.join(rejected))


def migrate(production):
    if production:
        if os.environ.get('ALLOW_PRODUCTION_MIGRATIONS') != 'approved':
            raise ValueError('Production migrations are disabled.')
        preflight_production()
        os.environ['DATABASE_URL'] = os.environ['DATABASE_URL_DIRECT']
    else:
        preflight_preview()
        require('DATABASE_URL', 'PREVIEW_BRANCH_ID', 'PREVIEW_BRANCH_CREATED')
        if (os.environ['PREVIEW_BRANCH_ID'] == os.environ['NEON_PREVIEW_PARENT_BRANCH_ID']
                or os.environ['PREVIEW_BRANCH_CREATED'] != 'true'):
            raise ValueError('Preview migrations require a newly created child branch.')
        database_identity(os.environ['DATABASE_URL'], direct=True)

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.core.management import call_command

    locked = False
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_lock(%s)', [MIGRATION_LOCK])
            locked = cursor.fetchone()[0]
            if not locked:
                raise ValueError('Another migration owns the database lock; retry later.')
            cursor.execute("SET lock_timeout = '10s'")
            cursor.execute("SET statement_timeout = '5min'")
            cursor.execute('SELECT current_database()')
            if cursor.fetchone()[0] != database_identity(os.environ['DATABASE_URL'])[1]:
                raise ValueError('Connected database does not match the requested database.')
        executor = MigrationExecutor(connection)
        executor.loader.check_consistent_history(connection)
        if executor.loader.detect_conflicts():
            raise ValueError('Conflicting migration graph; resolve before deployment.')
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if production:
            validate_plan(plan)
        for migration, backwards in plan:
            if backwards:
                raise ValueError('Backwards migrations are forbidden.')
            print(f'Applying {migration.app_label}.{migration.name}', flush=True)
        call_command('migrate', interactive=False, verbosity=1)
    finally:
        if locked:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [MIGRATION_LOCK])
        connection.close()


def deployment_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.vercel.app')
            or parsed.username or parsed.password or parsed.port
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
        raise ValueError('Expected a Vercel deployment HTTPS URL.')
    return value.rstrip('/')


def vercel(arguments):
    require('VERCEL_TOKEN', 'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID')
    result = subprocess.run(
        ['vercel', *arguments, '--token', os.environ['VERCEL_TOKEN']],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if result.returncode:
        # CLI failures can echo command arguments. Redact all configured secrets.
        message = result.stdout + result.stderr
        for name, value in os.environ.items():
            if value and any(word in name for word in ('TOKEN', 'SECRET', 'DATABASE_URL')):
                message = message.replace(value, '[REDACTED]')
        print(message, file=sys.stderr)
        raise ValueError(f'Vercel command failed (exit {result.returncode}).')
    return result.stdout


def deploy(production):
    if production:
        preflight_production()
    else:
        preflight_preview()
        require('DATABASE_URL')
        database_identity(os.environ['DATABASE_URL'])
    arguments = ['deploy', '--yes']
    if production:
        arguments.extend(['--prod', '--skip-domain'])
    # Explicit overrides prevent an inherited project/branch DATABASE_URL from
    # connecting this deployment to the wrong database. No migration in builds.
    for name, value in {
        'DATABASE_URL': os.environ['DATABASE_URL'],
        'DJANGO_SECRET_KEY': os.environ['DJANGO_SECRET_KEY'],
        'DJANGO_DEBUG': '0',
    }.items():
        arguments.extend(['--env', f'{name}={value}', '--build-env', f'{name}={value}'])
    output = vercel(arguments)
    candidates = re.findall(r'https://[a-zA-Z0-9.-]+\.vercel\.app/?', output)
    if len(candidates) != 1:
        raise ValueError('Vercel did not return exactly one deployment URL.')
    url = deployment_url(candidates[0])
    require('GITHUB_OUTPUT')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as target:
        target.write(f'url={url}\n')
    print('Deployment built successfully: ' + url)


def smoke():
    require('DEPLOYMENT_URL')
    base = deployment_url(os.environ['DEPLOYMENT_URL'])
    headers = {}
    if os.environ.get('VERCEL_AUTOMATION_BYPASS_SECRET'):
        headers['x-vercel-protection-bypass'] = os.environ['VERCEL_AUTOMATION_BYPASS_SECRET']
    class SameOriginRedirects(HTTPRedirectHandler):
        def redirect_request(self, request, file, code, message, response_headers, new_url):
            # Never forward a protection-bypass secret to a different origin.
            if urlsplit(new_url).netloc != urlsplit(base).netloc or urlsplit(new_url).scheme != 'https':
                raise ValueError('Smoke request redirected outside the deployment.')
            return super().redirect_request(request, file, code, message, response_headers, new_url)

    opener = build_opener(SameOriginRedirects())
    for path, content_type, markers in [
        ('/accounts/login/', 'text/html', [b'csrfmiddlewaretoken', b'name="username"', b'name="password"']),
        ('/static/bakery/app.css', 'text/css', [b'{', b'}']),
    ]:
        for attempt in range(5):
            try:
                with opener.open(Request(base + path, headers=headers), timeout=30) as response:
                    body = response.read(2_000_000)
                    if (response.status != 200 or content_type not in response.headers.get('Content-Type', '')
                            or not all(marker in body for marker in markers)):
                        raise ValueError('Unexpected application response: ' + path)
                break
            except (HTTPError, URLError):
                if attempt == 4:
                    raise ValueError('HTTPS smoke request failed: ' + path) from None
                time.sleep(2)
        print('HTTPS smoke passed: ' + path)


def main():
    commands = {
        'preflight-preview': preflight_preview,
        'preflight-production': preflight_production,
        'migrate-preview': lambda: migrate(False),
        'migrate-production': lambda: migrate(True),
        'deploy-preview': lambda: deploy(False),
        'stage-production': lambda: deploy(True),
        'smoke': smoke,
        'promote-production': lambda: (
            preflight_production(),
            vercel(['promote', deployment_url(os.environ.get('DEPLOYMENT_URL', '')), '--yes']),
        ),
    }
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise ValueError('Choose one of: ' + ', '.join(commands))
    commands[sys.argv[1]]()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Database exceptions may include connection information; keep them out
        # of shared CI logs. Known validation errors contain configuration names.
        print(str(error) if isinstance(error, ValueError)
              else f'{type(error).__name__}: delivery failed; inspect privately.', file=sys.stderr)
        raise SystemExit(1)
