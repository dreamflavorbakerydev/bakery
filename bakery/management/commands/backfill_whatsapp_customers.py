"""Backfill reviewed contact transcriptions without replacing existing contact data."""
import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bakery import models as m
from bakery.services.audit import record_change, snapshot


CONTACT_FIELDS = ('address', 'city', 'state', 'zip', 'phone')


def fill_contact(obj, row):
    for field in CONTACT_FIELDS:
        existing = getattr(obj, field)
        if existing and existing != row[field]:
            raise CommandError(f'{obj}: {field} conflicts with the photo transcription; no records committed.')
        setattr(obj, field, row[field])


class Command(BaseCommand):
    help = 'Backfill customer and delivery-location contacts from the reviewed WhatsApp transcription.'

    def add_arguments(self, parser):
        parser.add_argument('--source', type=Path, default=settings.BASE_DIR / 'docs/data/whatsapp-customers.json')
        parser.add_argument('--zone', type=int, choices=(1, 2, 3), default=1)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            rows = json.loads(options['source'].read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        created = updated = skipped = locations_created = 0
        seen = set()
        with transaction.atomic():
            for row in rows:
                for field in ('customer_name', 'source_image', 'source_entry', *CONTACT_FIELDS):
                    if not row.get(field):
                        raise CommandError(f'Missing {field} in transcription; no records committed.')
                name = row['customer_name']
                if name in seen:
                    raise CommandError(f'Duplicate source customer: {name}; no records committed.')
                seen.add(name)
                matches = list(m.Customer.objects.select_for_update().filter(customer_name=name))
                if len(matches) > 1:
                    raise CommandError(f'Multiple customers named {name}; no records committed.')
                customer = matches[0] if matches else m.Customer(customer_name=name, pricing_zone=options['zone'])
                before = snapshot(customer) if customer.pk else {}
                fill_contact(customer, row)
                source_note = f"Contact source: {row['source_image']} (entry {row['source_entry']})."
                if row.get('review_note'):
                    source_note += ' ' + row['review_note']
                if source_note not in customer.notes:
                    customer.notes = '\n'.join(filter(None, (customer.notes, source_note)))
                try:
                    customer.full_clean()
                    if before != snapshot(customer):
                        customer.save()
                        record_change(customer, before, 'backfill:whatsapp-customers')
                        if before:
                            updated += 1
                        else:
                            created += 1
                    else:
                        skipped += 1
                    locations = list(customer.locations.select_for_update().filter(address=row['address']))
                    if len(locations) > 1:
                        raise CommandError(f'Multiple locations at {name}, {row["address"]}; no records committed.')
                    location = locations[0] if locations else customer.locations.filter(location_code='MAIN').first()
                    location = location or m.CustomerLocation(customer=customer, location_code='MAIN', location_name=name)
                    location_before = snapshot(location) if location.pk else {}
                    fill_contact(location, row)
                    location.full_clean()
                    if location_before != snapshot(location):
                        location.save()
                        record_change(location, location_before, 'backfill:whatsapp-customers')
                        if not location_before:
                            locations_created += 1
                except ValidationError as exc:
                    raise CommandError(f'{name}: {exc}; no records committed.') from exc
                self.stdout.write(f'Customer ID {customer.pk}: {name}')
            if options['dry_run']:
                transaction.set_rollback(True)
        action = 'Validated without saving' if options['dry_run'] else 'Backfilled'
        self.stdout.write(self.style.SUCCESS(
            f'{action}: {created} customers created, {updated} updated, {skipped} unchanged; '
            f'{locations_created} delivery locations created. New customers use Zone {options["zone"]}.'))
