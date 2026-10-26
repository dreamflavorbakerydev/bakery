from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from bakery.models import CustomerPriceOverride, ProductZonePrice
from bakery.services.catalog import catalog_links


@dataclass(frozen=True)
class PriceResult:
    price: Decimal | None
    price_source: str
    standard_price: Decimal | None
    override: Decimal | None
    description: str

    @property
    def price_cents(self):
        return str(int(self.price * 100)) if self.price is not None else None


def current_period(queryset, pricing_date):
    return queryset.filter(active=True, effective_date__lte=pricing_date).filter(
        Q(expiration_date__isnull=True) | Q(expiration_date__gte=pricing_date)
    )


class PricingBook:
    """One date/account and three queries, independent of catalog size."""

    def __init__(self, customer, pricing_date, *, links=None):
        if not isinstance(pricing_date, date):
            raise ValidationError('An explicit pricing date is required.')
        if not customer.active:
            raise PermissionDenied('Customer account is inactive.')
        self.customer = customer
        self.links = {link.product_id: link for link in (catalog_links(customer) if links is None else links)}
        self.zone_prices = self._unique(current_period(ProductZonePrice.objects.filter(
            product_id__in=self.links, zone=customer.pricing_zone), pricing_date))
        self.overrides = self._unique(current_period(CustomerPriceOverride.objects.filter(
            customer=customer, product_id__in=self.links), pricing_date))

    @staticmethod
    def _unique(rows):
        result = {}
        for row in rows:
            if row.product_id in result:
                raise ValidationError('Overlapping prices detected. Office review is required.')
            result[row.product_id] = row
        return result

    def resolve(self, product):
        link = self.links.get(product.pk)
        if not link:
            raise PermissionDenied('Product is not available to this customer.')
        standard_record = self.zone_prices.get(product.pk)
        override_record = self.overrides.get(product.pk)
        standard = standard_record.price if standard_record else None
        override = override_record.override_price if override_record else None
        description = link.customer_product_name or link.product.product_name
        if override is not None:
            return PriceResult(override, 'CUSTOMER_OVERRIDE', standard, override, description)
        if standard is not None:
            return PriceResult(standard, f'ZONE_{self.customer.pricing_zone}', standard, None, description)
        return PriceResult(None, 'MISSING', None, None, description)


def resolve_price(customer, product, pricing_date):
    return PricingBook(customer, pricing_date).resolve(product)
