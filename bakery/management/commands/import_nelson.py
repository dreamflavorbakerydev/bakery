from datetime import date
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from bakery.services.imports import ImportFailure
from bakery.services.nelson import import_nelson


class Command(BaseCommand):
    help = 'Import products and all nine zone price fields from the verified Nelson workbook.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--effective-date', required=True, type=date.fromisoformat)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            report, duplicates = import_nelson(options['file'], options['effective_date'], options['dry_run'])
        except (ImportFailure, ValidationError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{'Validated' if options['dry_run'] else 'Imported'}: {report.inserted} new, {report.updated} updated, {report.skipped} unchanged products.")
        if duplicates:
            self.stdout.write(self.style.WARNING(f'Duplicate SKU retained as separate products: {", ".join(duplicates)}'))
