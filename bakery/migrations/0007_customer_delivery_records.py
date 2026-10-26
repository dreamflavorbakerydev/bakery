from django.db import migrations


def create_missing_delivery_records(apps, schema_editor):
    Customer = apps.get_model('bakery', 'Customer')
    Location = apps.get_model('bakery', 'CustomerLocation')
    Audit = apps.get_model('bakery', 'MasterDataChange')
    database = schema_editor.connection.alias
    for customer in Customer.objects.using(database).filter(locations__isnull=True).iterator():
        location = Location.objects.using(database).create(customer_id=customer.pk, location_code='MAIN',
            location_name=customer.customer_name, active=customer.active,
            **{field: getattr(customer, field) for field in ('address', 'city', 'state', 'zip', 'phone')})
        Audit.objects.using(database).create(model_name='bakery.CustomerLocation', record_key=str(location.pk),
            before={}, after={'customer': str(customer.pk), 'location_name': location.location_name,
                'location_code': location.location_code, 'active': str(location.active)},
            source='migration:customer-delivery-record')


class Migration(migrations.Migration):
    dependencies = [('bakery', '0006_store_delivery_rules')]
    operations = [migrations.RunPython(create_missing_delivery_records, migrations.RunPython.noop)]
