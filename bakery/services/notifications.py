from bakery.models import Order, OrderInboxState
from bakery.services.access import is_office


def has_new_orders(user):
    if not is_office(user):
        return False
    last_seen = OrderInboxState.objects.filter(user=user).values_list('last_seen_at', flat=True).first()
    orders = Order.objects.filter(submitted_at__isnull=False)
    if last_seen is not None:
        orders = orders.filter(submitted_at__gt=last_seen)
    return orders.exists()


def mark_orders_seen(user, through):
    if not is_office(user):
        return
    state, _ = OrderInboxState.objects.get_or_create(user=user, defaults={'last_seen_at': through})
    # A slower request must never move the user's read time backwards.
    OrderInboxState.objects.filter(pk=state.pk, last_seen_at__lt=through).update(last_seen_at=through)
