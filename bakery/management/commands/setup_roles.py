from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create repeatable role groups without creating users or assigning credentials.'

    def handle(self, *args, **options):
        master_models = ['customer', 'customerlocation', 'customeraccess', 'product', 'customerproduct',
                         'productzoneprice', 'customerpriceoverride', 'customerdeliveryrule']
        office_codes = [f'{action}_{model}' for model in master_models for action in ('add', 'change', 'view')]
        office_codes += ['office_access', 'production_access', 'view_masterdatachange', 'delete_customerpriceoverride']
        mappings = {
            'ADMINISTRATOR': Permission.objects.all(),
            'BAKERY OFFICE': Permission.objects.filter(content_type__app_label='bakery', codename__in=office_codes),
            'PRODUCTION': Permission.objects.filter(content_type__app_label='bakery', codename='production_access'),
            'CUSTOMER': Permission.objects.none(),
        }
        for name, permissions in mappings.items():
            group, _ = Group.objects.get_or_create(name=name)
            group.permissions.set(permissions)
            self.stdout.write(f'{name}: {group.permissions.count()} permissions')
