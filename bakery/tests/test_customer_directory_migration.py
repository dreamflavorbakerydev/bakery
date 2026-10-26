from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CustomerDirectoryMigrationTests(TransactionTestCase):
    def test_missing_delivery_record_is_created_without_calendar_or_access_grants(self):
        old = ('bakery', '0006_store_delivery_rules')
        new = ('bakery', '0007_customer_delivery_records')
        executor = MigrationExecutor(connection)
        executor.migrate([old])
        try:
            apps = executor.loader.project_state([old]).apps
            Customer = apps.get_model('bakery', 'Customer')
            Location = apps.get_model('bakery', 'CustomerLocation')
            customer = Customer.objects.create(customer_name='Missing delivery', pricing_zone=1,
                address='10 Main St', zip='07105', phone='9735550101')
            existing = Customer.objects.create(customer_name='Existing delivery', pricing_zone=1)
            location = Location.objects.create(customer=existing, location_name='Keep this record', location_code='ORIGINAL')
            executor = MigrationExecutor(connection)
            executor.migrate([new])
            apps = executor.loader.project_state([new]).apps
            Location = apps.get_model('bakery', 'CustomerLocation')
            new_location = Location.objects.get(customer_id=customer.pk)
            self.assertEqual((new_location.address, new_location.zip, new_location.phone), ('10 Main St', '07105', '9735550101'))
            self.assertEqual(Location.objects.get(customer_id=existing.pk).pk, location.pk)
            self.assertEqual(Location.objects.get(pk=location.pk).location_code, 'ORIGINAL')
            self.assertFalse(apps.get_model('bakery', 'CustomerDeliveryRule').objects.exists())
            self.assertFalse(apps.get_model('bakery', 'CustomerAccess').objects.exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
