from datetime import time

import bakery.models
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def materialize_store_rules(apps, schema_editor):
    Customer = apps.get_model('bakery', 'Customer')
    Rule = apps.get_model('bakery', 'CustomerDeliveryRule')
    Audit = apps.get_model('bakery', 'MasterDataChange')
    database = schema_editor.connection.alias
    fields = ('delivery_days', 'production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy')

    def snapshot(rule):
        return {'customer': str(rule.customer_id), 'location': str(rule.location_id) if rule.location_id else None,
                **{field: str(getattr(rule, field)) if getattr(rule, field) is not None else None for field in fields}}

    def audit(rule, before, after):
        Audit.objects.using(database).create(model_name='bakery.CustomerDeliveryRule', record_key=str(rule.pk),
            before=before, after=after, source='migration:store-delivery')

    for customer in Customer.objects.using(database).all().iterator():
        parent = Rule.objects.using(database).filter(customer_id=customer.pk, location__isnull=True).first()
        for location in customer.locations.using(database).all():
            local = Rule.objects.using(database).filter(location_id=location.pk).first()
            selected = local or parent
            if selected is None:
                continue
            before = snapshot(local) if local else {}
            rule = local or Rule(customer_id=customer.pk, location_id=location.pk)
            rule.delivery_days = selected.delivery_days
            fallback = {'production_lead_days': customer.default_lead_days,
                        'order_cutoff_time': customer.default_cutoff_time,
                        'timezone': customer.timezone, 'late_order_policy': customer.late_order_policy}
            for field in fields[1:]:
                value = next((getattr(source, field) for source in (local, parent)
                              if source is not None and getattr(source, field) not in (None, '')), fallback[field])
                setattr(rule, field, value)
            after = snapshot(rule)
            if before != after:
                rule.save(using=database)
                audit(rule, before, after)
        if parent:
            audit(parent, snapshot(parent), {})
            parent.delete(using=database)


class Migration(migrations.Migration):
    dependencies = [('bakery', '0005_customeraccess_active_access_requires_store')]

    operations = [
        migrations.RunPython(materialize_store_rules, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='customerdeliveryrule', name='unique_customer_delivery_default'),
        migrations.RemoveField(model_name='customer', name='default_lead_days'),
        migrations.RemoveField(model_name='customer', name='default_cutoff_time'),
        migrations.RemoveField(model_name='customer', name='late_order_policy'),
        migrations.AlterField(model_name='customerdeliveryrule', name='location',
            field=models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='delivery_rule', to='bakery.customerlocation')),
        migrations.AlterField(model_name='customerdeliveryrule', name='production_lead_days',
            field=models.PositiveSmallIntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)])),
        migrations.AlterField(model_name='customerdeliveryrule', name='order_cutoff_time', field=models.TimeField(default=time(14))),
        migrations.AlterField(model_name='customerdeliveryrule', name='timezone',
            field=models.CharField(default='America/New_York', max_length=64, validators=[bakery.models.validate_timezone])),
        migrations.AlterField(model_name='customerdeliveryrule', name='late_order_policy',
            field=models.CharField(choices=[('ALLOW', 'Allow automatically'), ('APPROVAL', 'Require bakery approval'),
                ('PROHIBIT', 'Prohibit late orders')], default='APPROVAL', max_length=10)),
    ]
