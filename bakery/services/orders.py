import uuid
import time
from functools import wraps
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, OperationalError
from django.utils import timezone

from bakery import models as m
from bakery.services.access import locations_for, orders_for, is_office
from bakery.services.delivery import validate_delivery_date, required_production_date
from bakery.services.pricing import PricingBook


def retry_locked(view):
    """Retry an entire rolled-back transaction when SQLite's writer is busy."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        for attempt in range(5):
            try:
                return view(*args, **kwargs)
            except OperationalError as exc:
                if 'locked' not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise ValidationError('The bakery is processing another order. Please try again.') from exc
                time.sleep(0.05 * (attempt + 1))
    return wrapped


def order_lines(customer, delivery_date, quantities):
    book = PricingBook(customer, delivery_date)
    lines = []
    for product_id, quantity in quantities.items():
        if type(quantity) is not int or quantity < 0 or quantity > 100000:
            raise ValidationError('Quantities must be whole numbers from 0 to 100,000.')
        if not quantity:
            continue
        link = book.links.get(product_id)
        if not link:
            raise ValidationError('A selected product is no longer available. Start a new order with the current catalog.')
        product = link.product
        price = book.resolve(product)
        if price.price is None:
            raise ValidationError(f'{product.product_name} has no price for this delivery date. Contact the bakery.')
        lines.append(m.OrderItem(product=product, quantity=quantity, unit_price=price.price,
            line_total=price.price * quantity, price_source=price.price_source,
            vendor_id=link.vendor_id, customer_sku=link.customer_sku, upc=product.upc,
            product_name=price.description, pack_size=product.pack_size, units_per_tray=product.units_per_tray,
            unit_of_measure=product.unit_of_measure,
            required_production_date=required_production_date(product, delivery_date)))
    if not lines:
        raise ValidationError('Add a quantity to at least one product.')
    return lines


@retry_locked
@transaction.atomic
def create_draft(user, location_id, delivery_date, quantities, po='', notes=''):
    location = locations_for(user).select_related('customer').filter(pk=location_id, active=True, customer__active=True).first()
    if not location:
        raise PermissionDenied
    eligibility = validate_delivery_date(location.customer, location, delivery_date)
    lines = order_lines(location.customer, delivery_date, quantities)
    total = sum((line.line_total for line in lines), Decimal('0'))
    if total > Decimal('999999999999.99'):
        raise ValidationError('This order total is too large. Reduce the quantities or contact the bakery.')
    order = m.Order.objects.create(order_number='B-' + uuid.uuid4().hex[:24].upper(),
        customer=location.customer, customer_location=location, created_by=user,
        order_date=timezone.localdate(timezone=ZoneInfo(location.customer.timezone)),
        requested_delivery_date=delivery_date, required_production_date=min(line.required_production_date for line in lines),
        customer_po_number=po, notes=notes, subtotal=total, total=total,
        late_order=eligibility.late, requires_approval=eligibility.requires_approval)
    # Allocate from the database ID, so simultaneous orders cannot share a
    # number. The temporary unique value above never leaves this transaction.
    order.order_number = f'B-{order.pk:06d}'
    order.save(update_fields=['order_number'])
    for line in lines:
        line.order = order
    m.OrderItem.objects.bulk_create(lines)
    m.OrderChangeLog.objects.create(order=order, user=user, details={'action': 'draft_created'})
    return order


@retry_locked
@transaction.atomic
def submit_order(user, pk):
    order = orders_for(user).select_for_update().select_related('customer', 'customer_location').get(pk=pk)
    if order.status != m.OrderStatus.DRAFT:
        return order  # Repeating the same submission never creates another order.
    eligibility = validate_delivery_date(order.customer, order.customer_location, order.requested_delivery_date)
    old_lines = list(order.items.all())
    lines = order_lines(order.customer, order.requested_delivery_date, {line.product_id: line.quantity for line in old_lines})
    before = {line.product_id: (line.unit_price, line.product_name, line.vendor_id, line.customer_sku, line.pack_size,
        line.unit_of_measure, line.units_per_tray, line.required_production_date, line.upc, line.price_source) for line in old_lines}
    after = {line.product_id: (line.unit_price, line.product_name, line.vendor_id, line.customer_sku, line.pack_size,
        line.unit_of_measure, line.units_per_tray, line.required_production_date, line.upc, line.price_source) for line in lines}
    if before != after:
        raise ValidationError('Product details or prices changed since your review. Start a new order to review the updated amounts.')
    now = timezone.now()
    updated = m.Order.objects.filter(pk=pk, status=m.OrderStatus.DRAFT).update(status=m.OrderStatus.SUBMITTED,
        submitted_at=now, updated_at=now, late_order=eligibility.late, requires_approval=eligibility.requires_approval)
    if updated:
        m.OrderChangeLog.objects.create(order=order, user=user, details={'action': 'submitted', 'requires_approval': eligibility.requires_approval})
    order.refresh_from_db()
    return order


TRANSITIONS = {
    m.OrderStatus.SUBMITTED: [m.OrderStatus.CONFIRMED, m.OrderStatus.CANCELLED],
    m.OrderStatus.CONFIRMED: [m.OrderStatus.PRODUCTION, m.OrderStatus.CANCELLED],
    m.OrderStatus.PRODUCTION: [m.OrderStatus.READY_TO_PICK, m.OrderStatus.CANCELLED],
    m.OrderStatus.READY_TO_PICK: [m.OrderStatus.DELIVERED, m.OrderStatus.CANCELLED],
}


@retry_locked
@transaction.atomic
def change_status(user, pk, target):
    if not is_office(user):
        raise PermissionDenied
    order = m.Order.objects.select_for_update().get(pk=pk)
    if target not in TRANSITIONS.get(order.status, []):
        raise ValidationError('This status change is no longer available. Refresh the order.')
    original = order.status
    changed = m.Order.objects.filter(pk=pk, status=original).update(status=target,
        requires_approval=False, updated_at=timezone.now())
    if not changed:
        raise ValidationError('The order changed. Refresh and try again.')
    m.OrderChangeLog.objects.create(order=order, user=user,
        details={'action': 'status_changed', 'from': original, 'to': target, 'approved_late_order': order.requires_approval})
    order.refresh_from_db()
    return order
