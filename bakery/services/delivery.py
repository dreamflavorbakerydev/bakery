from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.utils import timezone
from bakery.models import CustomerDeliveryRule, LatePolicy


@dataclass(frozen=True)
class DeliveryOptions:
    days: tuple
    lead_days: int
    cutoff_time: object
    timezone_name: str
    late_policy: str


@dataclass(frozen=True)
class DeliveryDate:
    delivery_date: date
    cutoff: datetime
    late: bool
    requires_approval: bool

    @property
    def cutoff_display(self):
        return self.cutoff.strftime('%b %d, %I:%M %p %Z')


def rules_for(customer, location):
    if location.customer_id != customer.pk or not location.active or not customer.active:
        raise ValidationError('Select an active location belonging to this customer.')
    rule = CustomerDeliveryRule.objects.filter(customer=customer, location=location).first()
    if not rule:
        raise ValidationError('Delivery calendar has not been configured. Contact the bakery office.')
    return DeliveryOptions(tuple(rule.delivery_days), rule.production_lead_days,
        rule.order_cutoff_time, rule.timezone, rule.late_order_policy)


def evaluate_date(options, delivery_date, now):
    if timezone.is_naive(now):
        raise ValidationError('Current time must include a timezone.')
    local_now = now.astimezone(ZoneInfo(options.timezone_name))
    if delivery_date <= local_now.date() or delivery_date.weekday() not in options.days:
        raise ValidationError('This date is not an available future delivery day.')
    cutoff = datetime.combine(delivery_date - timedelta(days=options.lead_days), options.cutoff_time,
                              tzinfo=ZoneInfo(options.timezone_name))
    late = local_now >= cutoff
    if late and options.late_policy == LatePolicy.PROHIBIT:
        raise ValidationError('The ordering cutoff for this delivery has passed.')
    return DeliveryDate(delivery_date, cutoff, late, late and options.late_policy == LatePolicy.APPROVAL)


def validate_delivery_date(customer, location, delivery_date, now=None):
    return evaluate_date(rules_for(customer, location), delivery_date, now or timezone.now())


def available_delivery_dates(customer, location, now=None, horizon=21):
    now = now or timezone.now()
    if timezone.is_naive(now):
        raise ValidationError('Current time must include a timezone.')
    options = rules_for(customer, location)
    today = now.astimezone(ZoneInfo(options.timezone_name)).date()
    result = []
    for offset in range(1, horizon + 1):
        try:
            result.append(evaluate_date(options, today + timedelta(days=offset), now))
        except ValidationError:
            continue
    return result


def required_production_date(product, delivery_date):
    return delivery_date - timedelta(days=product.production_lead_days)
