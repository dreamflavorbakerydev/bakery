from datetime import time
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from bakery import models as m
from bakery.tests.test_foundation import FoundationFixture


class StoreDeliveryTests(FoundationFixture):
    def setUp(self):
        call_command('setup_roles', stdout=StringIO())
        self.admin = get_user_model().objects.create_superuser('store-calendar-admin', password='Store-calendar-test-339!')
        self.client.force_login(self.admin)

    def store_post(self):
        return {'customer_name': self.customer.customer_name, 'customer_code': self.customer.customer_code, 'pricing_zone': self.customer.pricing_zone,
                'address': '15 Main St', 'active': 'on', 'delivery_days': ['0', '2', '4'],
                'production_lead_days': 2, 'order_cutoff_time': '11:30', 'timezone': 'America/Chicago',
                'late_order_policy': 'PROHIBIT'}

    def test_store_contacts_and_calendar_save_together(self):
        response = self.client.post(reverse('customer-edit', args=[self.customer.pk]), self.store_post())
        self.assertRedirects(response, reverse('customer-detail', args=[self.customer.pk]))
        self.location.refresh_from_db()
        self.rule.refresh_from_db()
        self.assertEqual(self.location.address, '15 Main St')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.address, '15 Main St')
        self.assertEqual(self.rule.delivery_days, [0, 2, 4])
        self.assertEqual(self.rule.order_cutoff_time, time(11, 30))
        self.assertEqual(self.rule.timezone, 'America/Chicago')
        self.assertEqual(self.rule.production_lead_days, 2)
        self.assertFalse(m.CustomerDeliveryRule.objects.filter(location=self.second_location).exists())
        self.assertTrue(m.MasterDataChange.objects.filter(source='workspace:store-delivery').exists())

    def test_invalid_calendar_does_not_save_contact_changes(self):
        response = self.client.post(reverse('customer-edit', args=[self.customer.pk]),
                                   {**self.store_post(), 'production_lead_days': 0})
        self.assertEqual(response.status_code, 200)
        self.location.refresh_from_db()
        self.rule.refresh_from_db()
        self.assertEqual(self.location.address, '')
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.address, '')
        self.assertEqual(self.rule.delivery_days, [1, 3, 5])
        self.assertFalse(m.MasterDataChange.objects.exists())

    def test_additional_delivery_address_keeps_primary_contacts_and_access_ids(self):
        original_access = self.user.customer_access.get()
        response = self.client.post(reverse('customer-edit', args=[self.customer.pk]) + f'?location={self.second_location.pk}',
                                   {**self.store_post(), 'address': 'Second delivery address'})
        self.assertRedirects(response, reverse('customer-detail', args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.location.refresh_from_db()
        self.second_location.refresh_from_db()
        original_access.refresh_from_db()
        self.assertEqual(self.customer.address, '')
        self.assertEqual(self.location.address, '')
        self.assertEqual(self.second_location.address, 'Second delivery address')
        self.assertEqual(original_access.location_id, self.location.pk)
        self.assertEqual(self.customer.locations.count(), 2)
        response = self.client.get(reverse('customer-edit', args=[self.customer.pk]) + f'?location={self.other_location.pk}')
        self.assertEqual(response.status_code, 404)

    def test_unconfigured_store_can_save_contacts_without_inventing_calendar(self):
        payload = {'customer_name': 'New customer', 'pricing_zone': 1,
                   'address': '20 Main St', 'active': 'on'}
        response = self.client.post(reverse('customer-new'), payload)
        customer = m.Customer.objects.get(customer_name='New customer')
        self.assertRedirects(response, reverse('customer-detail', args=[customer.pk]))
        store = customer.locations.get()
        self.assertFalse(m.CustomerDeliveryRule.objects.filter(location=store).exists())

    def test_delivery_links_open_stores_and_customer_form_has_no_delivery_defaults(self):
        response = self.client.get(reverse('customer-edit', args=[self.customer.pk]))
        for field in ('default_lead_days', 'default_cutoff_time'):
            self.assertNotContains(response, f'name="{field}"')
        self.assertContains(response, 'Customer details')
        self.assertContains(response, 'Delivery rules')
        self.assertRedirects(self.client.get(reverse('workspace-records', args=['delivery'])), reverse('customers'))
        self.assertRedirects(self.client.get(reverse('workspace-record-edit', args=['delivery', self.rule.pk])),
                             reverse('customer-edit', args=[self.customer.pk]) + f'?location={self.location.pk}')


class StoreDeliveryMigrationTests(TransactionTestCase):
    def test_customer_inheritance_is_materialized_per_store(self):
        old = ('bakery', '0005_customeraccess_active_access_requires_store')
        new = ('bakery', '0006_store_delivery_rules')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        try:
            apps = executor.loader.project_state([old]).apps
            Customer = apps.get_model('bakery', 'Customer')
            Location = apps.get_model('bakery', 'CustomerLocation')
            Rule = apps.get_model('bakery', 'CustomerDeliveryRule')
            customer = Customer.objects.create(customer_name='Calendar legacy', pricing_zone=1,
                default_lead_days=3, default_cutoff_time=time(13), timezone='America/Chicago', late_order_policy='PROHIBIT')
            first = Location.objects.create(customer=customer, location_name='First', location_code='FIRST')
            second = Location.objects.create(customer=customer, location_name='Second', location_code='SECOND')
            unconfigured = Customer.objects.create(customer_name='No calendar', pricing_zone=1)
            third = Location.objects.create(customer=unconfigured, location_name='Third', location_code='THIRD')
            Rule.objects.create(customer=customer, delivery_days=[1, 3], order_cutoff_time=time(12))
            local = Rule.objects.create(customer=customer, location=first, delivery_days=[5], production_lead_days=2)
            executor = MigrationExecutor(connection)
            executor.migrate([new])
            apps = executor.loader.project_state([new]).apps
            Rule = apps.get_model('bakery', 'CustomerDeliveryRule')
            local = Rule.objects.get(pk=local.pk)
            inherited = Rule.objects.get(location_id=second.pk)
            self.assertEqual((local.delivery_days, local.production_lead_days, local.order_cutoff_time), ([5], 2, time(12)))
            self.assertEqual((inherited.delivery_days, inherited.production_lead_days), ([1, 3], 3))
            self.assertEqual((inherited.timezone, inherited.late_order_policy), ('America/Chicago', 'PROHIBIT'))
            self.assertFalse(Rule.objects.filter(location_id=third.pk).exists())
            self.assertFalse(Rule.objects.filter(location__isnull=True).exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
