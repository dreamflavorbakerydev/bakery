from django.core.management.base import BaseCommand, CommandError
from bakery.services.imports import ImportFailure, import_master_data


class MasterImportCommand(BaseCommand):
    kind = None

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--dry-run', action='store_true', help='Validate without committing any records.')

    def handle(self, *args, **options):
        try:
            report = import_master_data(self.kind, options['file'], options['dry_run'])
        except (ImportFailure, OSError) as exc:
            raise CommandError(str(exc)) from exc
        prefix = 'Validated (dry run)' if options['dry_run'] else 'Committed'
        self.stdout.write(self.style.SUCCESS(f'{prefix}: {report.inserted} inserted, {report.updated} updated, {report.skipped} skipped.'))
