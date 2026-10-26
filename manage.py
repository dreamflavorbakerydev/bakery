import os
from pathlib import Path
import subprocess
import sys


def main():
    # A bare `python manage.py` should use this checkout's dependencies.
    # Respect an explicitly activated environment instead of replacing it.
    project_dir = Path(__file__).resolve().parent
    project_python = project_dir / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if sys.prefix == sys.base_prefix and project_python.is_file():
        child_environment = os.environ.copy()
        # Global path overrides must not inject a different Django into .venv.
        child_environment.pop('PYTHONHOME', None)
        child_environment.pop('PYTHONPATH', None)
        try:
            return subprocess.call([str(project_python), '-u', str(project_dir / 'manage.py'), *sys.argv[1:]],
                                   env=child_environment)
        except KeyboardInterrupt:
            return 130

    try:
        import django
    except ImportError:
        sys.stderr.write('Django is missing. Install the project dependencies:\n'
                         '  python -m pip install -r requirements.txt\n')
        return 1
    if django.VERSION[:2] != (5, 2):
        sys.stderr.write(f'Bakery requires Django 5.2; this interpreter has Django {django.get_version()}.\n'
                         'Install requirements.txt into the project environment:\n'
                         '  .venv\\Scripts\\python.exe -m pip install -r requirements.txt\n')
        return 1

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver' and os.environ.get('RUN_MAIN') != 'true':
        print(f'Bakery runtime: Django {django.get_version()} | {sys.executable}', flush=True)
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
