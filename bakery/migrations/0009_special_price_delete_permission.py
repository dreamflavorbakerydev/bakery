from django.db import migrations


def grant_office_delete(apps, schema_editor):
    database = schema_editor.connection.alias
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    group = Group.objects.using(database).filter(name='BAKERY OFFICE').first()
    permission = Permission.objects.using(database).filter(
        content_type__app_label='bakery', codename='delete_customerpriceoverride').first()
    if group and permission:
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [('bakery', '0008_orderinboxstate')]
    operations = [migrations.RunPython(grant_office_delete, migrations.RunPython.noop)]
