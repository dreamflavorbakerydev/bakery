from django.core.exceptions import PermissionDenied
from django.db.models import F
from bakery.models import Customer, CustomerAccess, CustomerLocation, Order
from bakery.services.catalog import catalog_links


def is_office(user):
    return user.is_authenticated and user.is_active and user.has_perm('bakery.office_access')


def is_production(user):
    return user.is_authenticated and user.is_active and user.has_perm('bakery.production_access')


def assignments(user):
    if not user.is_authenticated or not user.is_active:
        return CustomerAccess.objects.none()
    return CustomerAccess.objects.filter(user=user, active=True, customer__active=True,
        location__active=True, location__customer_id=F('customer_id'))


def customers_for(user):
    if is_office(user):
        return Customer.objects.all()
    return Customer.objects.filter(pk__in=assignments(user).values('customer_id'))


def locations_for(user):
    if is_office(user):
        return CustomerLocation.objects.all()
    return CustomerLocation.objects.filter(active=True, customer__active=True,
        pk__in=assignments(user).values('location_id'))


def products_for(user, customer):
    if not customers_for(user).filter(pk=customer.pk).exists():
        raise PermissionDenied('This account is not assigned to your login.')
    return catalog_links(customer)


def orders_for(user):
    if is_office(user):
        return Order.objects.all()
    return Order.objects.filter(customer_location__in=locations_for(user), customer_id__in=customers_for(user).values('pk'))
