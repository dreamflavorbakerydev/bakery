from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.urls import reverse

from bakery import models as m
from bakery.services.catalog import catalog_links, product_is_available
from bakery.tests.test_foundation import FoundationFixture


class CustomerProductSettingsTests(FoundationFixture):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser('catalog-settings-admin')
        self.client.force_login(self.admin)
        self.url = reverse('customer-edit', args=[self.customer.pk])

    def row(self, link=None, product=None, **values):
        result = {'id': link.pk if link else '', 'product': (product or self.product).pk,
            'customer_sku': '', 'vendor_id': '', 'customer_product_name': '', 'sort_order': 0, 'active': 'on'}
        result.update(values)
        return result

    def payload(self, mode, rows):
        data = {'customer_name': self.customer.customer_name, 'customer_code': self.customer.customer_code,
            'pricing_zone': self.customer.pricing_zone, 'active': 'on',
            'delivery_days': ['1', '3', '5'], 'production_lead_days': 1, 'order_cutoff_time': '14:00',
            'timezone': 'America/New_York', 'late_order_policy': 'APPROVAL', 'catalog-mode': mode,
            'products-TOTAL_FORMS': len(rows), 'products-INITIAL_FORMS': self.customer.product_links.count(),
            'products-MIN_NUM_FORMS': 0, 'products-MAX_NUM_FORMS': 2000}
        for index, row in enumerate(rows):
            data.update({f'products-{index}-{key}': value for key, value in row.items()})
        return data

    def test_administration_contains_only_access_and_change_trail(self):
        response = self.client.get(reverse('administration'))
        self.assertContains(response, '<h2>Logins &amp; access</h2>')
        self.assertContains(response, '<h2>Change trail</h2>')
        for title in ('Customers', 'Products', 'Special prices', 'Product availability'):
            self.assertNotContains(response, f'<h2>{title}</h2>')

    def test_full_catalog_retains_customer_sku_metadata(self):
        response = self.client.post(self.url, self.payload('FULL', [self.row(self.link,
            customer_sku='CUSTOM-123', vendor_id='VENDOR', customer_product_name='Customer bread')]))
        self.assertRedirects(response, reverse('customer-detail', args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.catalog_mode, 'FULL')
        links = {link.product_id: link for link in catalog_links(self.customer)}
        self.assertEqual(set(links), {self.product.pk, self.restricted.pk})
        self.assertEqual(links[self.product.pk].customer_sku, 'CUSTOM-123')
        self.assertEqual(links[self.product.pk].vendor_id, 'VENDOR')
        self.assertTrue(product_is_available(self.customer, self.restricted))
        self.assertTrue(m.MasterDataChange.objects.filter(source='workspace:customer-products').exists())

    def test_custom_catalog_only_includes_available_rows(self):
        rows = [self.row(self.link, active=''), self.row(product=self.restricted)]
        response = self.client.post(self.url, self.payload('CUSTOM', rows))
        self.assertRedirects(response, reverse('customer-detail', args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertEqual({link.product_id for link in catalog_links(self.customer)}, {self.restricted.pk})
        self.assertFalse(product_is_available(self.customer, self.product))
        self.assertTrue(product_is_available(self.customer, self.restricted))

    def test_explicit_empty_custom_catalog_stays_empty(self):
        self.link.delete()
        response = self.client.post(self.url, self.payload('CUSTOM', []))
        self.assertRedirects(response, reverse('customer-detail', args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertEqual(catalog_links(self.customer), [])
        self.assertFalse(product_is_available(self.customer, self.product))
        response = self.client.post(self.url, self.payload('FULL', []))
        self.assertEqual(response.status_code, 302)
        self.customer.refresh_from_db()
        self.assertEqual(len(catalog_links(self.customer)), 2)

    def test_bad_product_settings_roll_back_customer_and_delivery_edits(self):
        data = self.payload('CUSTOM', [self.row(self.link), self.row(product=self.product)])
        data['customer_name'] = 'Must not be saved'
        data['production_lead_days'] = 9
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.customer.refresh_from_db()
        self.rule.refresh_from_db()
        self.assertEqual(self.customer.customer_name, 'Test account A')
        self.assertEqual(self.rule.production_lead_days, 1)
        self.assertEqual(self.customer.product_links.count(), 1)
        self.assertFalse(m.MasterDataChange.objects.exists())

    def test_foreign_mapping_cannot_be_edited(self):
        foreign = self.other.product_links.get()
        response = self.client.post(self.url, self.payload('CUSTOM', [self.row(foreign,
            product=self.restricted, customer_sku='TAMPERED')]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'belongs to another customer')
        foreign.refresh_from_db()
        self.assertNotEqual(foreign.customer_sku, 'TAMPERED')
        self.assertEqual(foreign.customer_id, self.other.pk)

    def test_product_settings_require_add_change_and_view_permissions(self):
        user = get_user_model().objects.create_user('contact-editor-only')
        user.user_permissions.add(*Permission.objects.filter(codename__in=[
            'office_access', 'change_customer', 'change_customerlocation']))
        self.client.force_login(user)
        self.assertNotContains(self.client.get(self.url), 'id="customer-products"')
        self.assertEqual(self.client.post(self.url, self.payload('FULL', [])).status_code, 403)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.catalog_mode, 'AUTO')

    def test_old_product_availability_links_open_customer_editor(self):
        target = self.url + '#customer-products'
        self.assertRedirects(self.client.get(reverse('workspace-records', args=['availability']),
            {'customer': self.customer.pk}), target)
        self.assertRedirects(self.client.get(reverse('workspace-record-edit', args=['availability', self.link.pk])), target)
        self.assertRedirects(self.client.get(reverse('workspace-record-new', args=['availability']),
            {'customer': self.customer.pk}), target)

    def test_new_customer_can_save_product_settings_in_same_editor(self):
        data = self.payload('CUSTOM', [self.row(product=self.restricted, customer_sku='NEW-SKU')])
        data.update(customer_name='New customer with catalog', customer_code='', **{'products-INITIAL_FORMS': 0})
        response = self.client.post(reverse('customer-new'), data)
        created = m.Customer.objects.get(customer_name='New customer with catalog')
        self.assertRedirects(response, reverse('customer-detail', args=[created.pk]))
        self.assertEqual(created.catalog_mode, 'CUSTOM')
        self.assertEqual(created.product_links.get().customer_sku, 'NEW-SKU')
        self.assertEqual({link.product_id for link in catalog_links(created)}, {self.restricted.pk})


class CatalogModeMigrationTests(TransactionTestCase):
    def test_migration_preserves_full_and_custom_catalogs_and_metadata(self):
        old = ('bakery', '0009_special_price_delete_permission')
        new = ('bakery', '0010_customer_catalog_mode')
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([old])
            apps = executor.loader.project_state([old]).apps
            Customer = apps.get_model('bakery', 'Customer')
            Product = apps.get_model('bakery', 'Product')
            Link = apps.get_model('bakery', 'CustomerProduct')
            full = Customer.objects.create(customer_name='Full catalog', pricing_zone=1)
            custom = Customer.objects.create(customer_name='Custom catalog', pricing_zone=1)
            product = Product.objects.create(internal_product_code='MIGRATION-CATALOG', product_name='Bread')
            link = Link.objects.create(customer=custom, product=product, active=False,
                customer_sku='00123', vendor_id='000VENDOR')
            executor = MigrationExecutor(connection)
            executor.migrate([new])
            apps = executor.loader.project_state([new]).apps
            Customer = apps.get_model('bakery', 'Customer')
            Link = apps.get_model('bakery', 'CustomerProduct')
            self.assertEqual(Customer.objects.get(pk=full.pk).catalog_mode, 'FULL')
            self.assertEqual(Customer.objects.get(pk=custom.pk).catalog_mode, 'CUSTOM')
            preserved = Link.objects.get(pk=link.pk)
            self.assertEqual((preserved.customer_sku, preserved.vendor_id, preserved.active),
                ('00123', '000VENDOR', False))
            self.assertFalse(Link.objects.filter(customer_id=full.pk).exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
