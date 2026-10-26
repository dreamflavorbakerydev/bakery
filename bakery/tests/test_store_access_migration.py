from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StoreAccessMigrationTests(TransactionTestCase):
    old_target = ('bakery', '0004_customer_address_customer_city_customer_phone_and_more')
    new_target = ('bakery', '0005_customeraccess_active_access_requires_store')

    def test_account_grants_become_explicit_stores_without_widening_access(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.old_target])
        try:
            apps = executor.loader.project_state([self.old_target]).apps
            User = apps.get_model('auth', 'User')
            Customer = apps.get_model('bakery', 'Customer')
            Location = apps.get_model('bakery', 'CustomerLocation')
            Access = apps.get_model('bakery', 'CustomerAccess')
            user = User.objects.create(username='legacy-store-access')
            customer = Customer.objects.create(customer_name='Legacy account', pricing_zone=1)
            empty = Customer.objects.create(customer_name='No stores account', pricing_zone=1)
            store = Location.objects.create(customer=customer, location_code='ONE', location_name='Existing store')
            disabled = Location.objects.create(customer=customer, location_code='TWO', location_name='Disabled assignment')
            inactive = Location.objects.create(customer=customer, location_code='THREE', location_name='Inactive store', active=False)
            wide = Access.objects.create(user=user, customer=customer)
            empty_wide = Access.objects.create(user=user, customer=empty)
            explicit = Access.objects.create(user=user, customer=customer, location=disabled, active=False)
            executor = MigrationExecutor(connection)
            executor.migrate([self.new_target])
            apps = executor.loader.project_state([self.new_target]).apps
            Access = apps.get_model('bakery', 'CustomerAccess')
            Audit = apps.get_model('bakery', 'MasterDataChange')
            self.assertFalse(Access.objects.get(pk=wide.pk).active)
            self.assertFalse(Access.objects.get(pk=empty_wide.pk).active)
            self.assertFalse(Access.objects.get(pk=explicit.pk).active)
            self.assertEqual(list(Access.objects.filter(user_id=user.pk, active=True).values_list('location_id', flat=True)), [store.pk])
            self.assertFalse(Access.objects.filter(location_id=inactive.pk).exists())
            self.assertEqual(Audit.objects.filter(source='migration:store-only-access').count(), 3)
        finally:
            MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
