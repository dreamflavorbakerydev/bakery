import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TestCase
from django.urls import reverse

from bakery import models as m
from bakery.services.imports import ImportFailure, import_master_data


class CustomerContactTests(TestCase):
    def test_customer_form_assigns_distinct_ids_without_codes(self):
        user = get_user_model().objects.create_superuser('contacts-admin', password='Test-only-contacts-339!')
        self.client.force_login(user)
        for name in ('First account', 'Second account'):
            response = self.client.post(reverse('workspace-record-new', args=['customers']), {
                'customer_name': name, 'customer_code': '', 'address': '1 Main St', 'city': 'Newark',
                'state': 'NJ', 'zip': '07105', 'phone': '9735550101', 'pricing_zone': 1,
                'active': 'on', 'default_lead_days': 1, 'default_cutoff_time': '14:00',
                'timezone': 'America/New_York', 'late_order_policy': 'APPROVAL'})
            customer = m.Customer.objects.get(customer_name=name)
            self.assertRedirects(response, reverse('customer-detail', args=[customer.pk]))
            self.assertIsNone(customer.customer_code)
            self.assertEqual(customer.zip, '07105')
            self.assertContains(self.client.get(reverse('customer-detail', args=[customer.pk])), '9735550101')
            self.assertContains(self.client.get(reverse('customer-detail', args=[customer.pk])), '(973) 555-0101')
            self.assertContains(self.client.get(reverse('customers'), {'q': customer.pk}), name)
        self.assertEqual(m.Customer.objects.count(), 2)

    def test_code_less_customer_can_be_updated_and_referenced_by_id(self):
        customer = m.Customer.objects.create(customer_name='No code', pricing_zone=1)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'customers.csv'
            source.write_text(f'customer_id,customer_name,pricing_zone,phone\n{customer.pk},No code,1,9735550101\n')
            report = import_master_data('customers', source)
            self.assertEqual(report.updated, 1)
            self.assertEqual(import_master_data('customers', source).skipped, 1)
            source.write_text(f'customer_id,location_code,location_name\n{customer.pk},MAIN,Main store\n')
            import_master_data('locations', source)
            self.assertEqual(customer.locations.get().location_name, 'Main store')
            source.write_text('customer_name,pricing_zone\nMissing identity,1\n')
            with self.assertRaisesRegex(ImportFailure, 'Supply customer_id'):
                import_master_data('customers', source)
        customer.refresh_from_db()
        self.assertEqual(customer.phone, '9735550101')
        self.assertEqual(m.Customer.objects.count(), 1)

    def test_backfill_dry_run_and_repeat_are_safe(self):
        # Keep regression tests independent of private customer transcriptions.
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'customers.json'
            source.write_text(json.dumps([
                {'customer_name': f'Sample bakery customer {index:02d}', 'address': f'{index} Example Street',
                 'city': 'Sample City', 'state': 'NY', 'zip': '10001', 'phone': f'20255501{index:02d}',
                 'source_image': 'example.jpeg', 'source_entry': index}
                for index in range(1, 19)
            ]), encoding='utf-8')
            self.check_backfill_source(source)

    def check_backfill_source(self, source):
        call_command('backfill_whatsapp_customers', source=source, dry_run=True, stdout=StringIO())
        self.assertFalse(m.Customer.objects.exists())
        self.assertFalse(m.CustomerLocation.objects.exists())
        self.assertFalse(m.MasterDataChange.objects.exists())
        call_command('backfill_whatsapp_customers', source=source, stdout=StringIO())
        self.assertEqual(m.Customer.objects.count(), 18)
        self.assertEqual(m.CustomerLocation.objects.count(), 18)
        before = list(m.Customer.objects.values())
        audit_count = m.MasterDataChange.objects.count()
        call_command('backfill_whatsapp_customers', source=source, stdout=StringIO())
        self.assertEqual(list(m.Customer.objects.values()), before)
        self.assertEqual(m.MasterDataChange.objects.count(), audit_count)
        self.assertFalse(m.Customer.objects.exclude(pricing_zone=1).exists())
        self.assertFalse(m.Customer.objects.exclude(customer_code=None).exists())

    def test_backfill_conflict_rolls_back_all_rows(self):
        customer = m.Customer.objects.create(customer_name='Existing account', pricing_zone=2, phone='9735550102')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'contacts.json'
            row = {'customer_name': 'New account', 'address': '1 Main St', 'city': 'Newark',
                   'state': 'NJ', 'zip': '07105', 'phone': '9735550101', 'source_image': 'source.jpeg', 'source_entry': 1}
            source.write_text(json.dumps([row, {**row, 'customer_name': customer.customer_name}]))
            with self.assertRaisesRegex(CommandError, 'phone conflicts'):
                call_command('backfill_whatsapp_customers', source=source, stdout=StringIO())
        self.assertEqual(m.Customer.objects.count(), 1)
        self.assertFalse(m.CustomerLocation.objects.exists())
        self.assertFalse(m.MasterDataChange.objects.exists())
        customer.refresh_from_db()
        self.assertEqual(customer.phone, '9735550102')
        self.assertEqual(customer.pricing_zone, 2)
