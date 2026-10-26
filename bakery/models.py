from datetime import time
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError('Use an IANA timezone such as America/New_York.')


def validate_weekdays(value):
    if not isinstance(value, list) or not value or any(type(d) is not int or d not in range(7) for d in value):
        raise ValidationError('Delivery days must be a nonempty list of integers: Monday=0 through Sunday=6.')
    if len(set(value)) != len(value):
        raise ValidationError('Delivery days cannot be duplicated.')


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class LatePolicy(models.TextChoices):
    ALLOW = 'ALLOW', 'Allow automatically'
    APPROVAL = 'APPROVAL', 'Require bakery approval'
    PROHIBIT = 'PROHIBIT', 'Prohibit late orders'


class Customer(Timestamped):
    customer_code = models.CharField(max_length=50, unique=True, blank=True, null=True)
    customer_name = models.CharField(max_length=200)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    zip = models.CharField('ZIP code', max_length=20, blank=True)
    phone = models.CharField('Phone number', max_length=40, blank=True)
    pricing_zone = models.PositiveSmallIntegerField(choices=[(1, 'Zone 1'), (2, 'Zone 2'), (3, 'Zone 3')])
    catalog_mode = models.CharField(max_length=6, default='AUTO', choices=[
        ('AUTO', 'Automatic'), ('FULL', 'Full catalog'), ('CUSTOM', 'Custom product list')])
    active = models.BooleanField(default=True)
    timezone = models.CharField(max_length=64, default='America/New_York', validators=[validate_timezone])
    payment_terms = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['customer_name']
        constraints = [models.CheckConstraint(condition=Q(pricing_zone__in=[1, 2, 3]), name='valid_customer_zone')]
        permissions = [('office_access', 'Access bakery office'), ('production_access', 'Access production requirements')]

    def __str__(self):
        return f'{self.customer_name} ({self.customer_code or "ID " + str(self.pk)})'

    def clean(self):
        if not self.customer_code:
            self.customer_code = None


class CustomerLocation(Timestamped):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='locations')
    location_code = models.CharField(max_length=50)
    location_name = models.CharField(max_length=200)
    store_number = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    zip = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['location_name']
        constraints = [models.UniqueConstraint(fields=['customer', 'location_code'], name='unique_customer_location')]

    def __str__(self):
        return str(self.customer) if self.location_name == self.customer.customer_name else f'{self.customer} / {self.location_name}'


class CustomerAccess(Timestamped):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='customer_access')
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    location = models.ForeignKey(CustomerLocation, null=True, blank=True, on_delete=models.PROTECT)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['user', 'customer', 'location'], name='unique_location_access'),
            models.UniqueConstraint(fields=['user', 'customer'], condition=Q(location__isnull=True), name='unique_account_access'),
            models.CheckConstraint(condition=Q(active=False) | Q(location__isnull=False), name='active_access_requires_store'),
        ]

    def clean(self):
        if self.active and not self.location_id:
            raise ValidationError({'location': 'Select a customer for this login.'})
        if self.location_id and self.location.customer_id != self.customer_id:
            raise ValidationError({'location': 'Location must belong to the assigned customer.'})

    def __str__(self):
        return f'{self.user} → {self.location or "Retired customer assignment"}'


class Product(Timestamped):
    internal_product_code = models.CharField(max_length=50, unique=True)
    sku = models.CharField('SKU', max_length=64, blank=True, db_index=True)
    product_name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    upc = models.CharField('UPC', max_length=32, blank=True)
    category = models.CharField(max_length=100, blank=True, db_index=True)
    size = models.CharField(max_length=64, blank=True)
    units_per_tray = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    pack_size = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    unit_of_measure = models.CharField(max_length=30, default='case')
    production_lead_days = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'product_name']

    def __str__(self):
        return f'{self.product_name} ({self.internal_product_code})'


class ProductSourceRecord(Timestamped):
    product = models.OneToOneField(Product, on_delete=models.PROTECT, related_name='source_record')
    source_key = models.CharField(max_length=200, unique=True)
    workbook = models.CharField(max_length=200)
    sheet = models.CharField(max_length=100)
    row_number = models.PositiveIntegerField()
    values = models.JSONField(default=dict)
    review_notes = models.TextField(blank=True)


class CustomerProduct(Timestamped):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='product_links')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='customer_links')
    vendor_id = models.CharField('VendorID', max_length=64, blank=True)
    customer_sku = models.CharField(max_length=64, blank=True)
    customer_product_name = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'product__product_name']
        constraints = [models.UniqueConstraint(fields=['customer', 'product'], name='unique_customer_product')]

    def __str__(self):
        return f'{self.customer} / {self.product.product_name}'


class DatedPrice(Timestamped):
    effective_date = models.DateField()
    expiration_date = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.expiration_date and self.expiration_date < self.effective_date:
            raise ValidationError({'expiration_date': 'Expiration cannot precede the effective date.'})
        if not self.active or not self.product_id:
            return
        lookup = {'product_id': self.product_id, 'active': True}
        lookup.update({'zone': self.zone} if isinstance(self, ProductZonePrice) else {'customer_id': self.customer_id})
        others = type(self).objects.filter(**lookup).exclude(pk=self.pk)
        others = others.filter(Q(expiration_date__isnull=True) | Q(expiration_date__gte=self.effective_date))
        if self.expiration_date:
            others = others.filter(effective_date__lte=self.expiration_date)
        if others.exists():
            raise ValidationError('Active price periods overlap. Close the previous period first.')


class ProductZonePrice(DatedPrice):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='zone_prices')
    zone = models.PositiveSmallIntegerField(choices=[(1, 'Zone 1'), (2, 'Zone 2'), (3, 'Zone 3')])
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    retail_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])
    return_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['product', 'zone', 'effective_date'], name='unique_zone_price_start'),
            models.CheckConstraint(condition=Q(price__gte=0) & Q(zone__in=[1, 2, 3]), name='valid_zone_price'),
            models.CheckConstraint(condition=Q(expiration_date__isnull=True) | Q(expiration_date__gte=models.F('effective_date')), name='valid_zone_price_dates'),
        ]
        indexes = [models.Index(fields=['product', 'zone', 'active', 'effective_date'])]

    def __str__(self):
        return f'{self.product} · Zone {self.zone} · ${self.price}'


class CustomerPriceOverride(DatedPrice):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='price_overrides')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    override_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0'))])
    reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['customer', 'product', 'effective_date'], name='unique_override_start'),
            models.CheckConstraint(condition=Q(override_price__gte=0), name='nonnegative_override'),
            models.CheckConstraint(condition=Q(expiration_date__isnull=True) | Q(expiration_date__gte=models.F('effective_date')), name='valid_override_dates'),
        ]
        indexes = [models.Index(fields=['customer', 'product', 'active', 'effective_date'])]


class CustomerDeliveryRule(Timestamped):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='delivery_rules')
    location = models.OneToOneField(CustomerLocation, on_delete=models.PROTECT, related_name='delivery_rule')
    delivery_days = models.JSONField(validators=[validate_weekdays])
    production_lead_days = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    order_cutoff_time = models.TimeField(default=time(14))
    timezone = models.CharField(max_length=64, default='America/New_York', validators=[validate_timezone])
    late_order_policy = models.CharField(max_length=10, choices=LatePolicy.choices, default=LatePolicy.APPROVAL)

    def clean(self):
        if self.location_id and self.location.customer_id != self.customer_id:
            raise ValidationError({'location': 'Location must belong to this customer.'})

    @property
    def delivery_days_display(self):
        return ', '.join(('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')[day] for day in self.delivery_days)


class OrderStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SUBMITTED = 'SUBMITTED', 'Submitted'
    CONFIRMED = 'CONFIRMED', 'Confirmed'
    PRODUCTION = 'PRODUCTION', 'Preparing'
    READY_TO_PICK = 'READY_TO_PICK', 'Ready to pick'
    PICKED = 'PICKED', 'Picked'
    LOADED = 'LOADED', 'Loaded'
    OUT_FOR_DELIVERY = 'OUT_FOR_DELIVERY', 'Out for delivery'
    DELIVERED = 'DELIVERED', 'Delivered'
    INVOICED = 'INVOICED', 'Invoiced'
    CANCELLED = 'CANCELLED', 'Cancelled'


class Order(Timestamped):
    order_number = models.CharField(max_length=32, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='orders')
    customer_location = models.ForeignKey(CustomerLocation, on_delete=models.PROTECT, related_name='orders')
    order_date = models.DateField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    requested_delivery_date = models.DateField(db_index=True)
    required_production_date = models.DateField(null=True, blank=True, db_index=True)
    customer_po_number = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.DRAFT, db_index=True)
    late_order = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)

    class Meta:
        indexes = [models.Index(fields=['customer', 'customer_location', 'requested_delivery_date', 'status'])]

    def clean(self):
        if self.customer_location_id and self.customer_location.customer_id != self.customer_id:
            raise ValidationError({'customer_location': 'Location must belong to this customer.'})


class OrderInboxState(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='order_inbox_state')
    last_seen_at = models.DateTimeField()


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=14, decimal_places=2)
    price_source = models.CharField(max_length=24)
    vendor_id = models.CharField(max_length=64, blank=True)
    customer_sku = models.CharField(max_length=64, blank=True)
    upc = models.CharField(max_length=32, blank=True)
    product_name = models.CharField(max_length=200)
    pack_size = models.PositiveIntegerField(default=1)
    units_per_tray = models.PositiveIntegerField(null=True, blank=True)
    unit_of_measure = models.CharField(max_length=30)
    required_production_date = models.DateField(db_index=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['order', 'product'], name='unique_order_product')]
        indexes = [models.Index(fields=['product', 'required_production_date'])]


class OrderChangeLog(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name='changes')
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    original_quantity = models.PositiveIntegerField(null=True, blank=True)
    new_quantity = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ProductionPlan(Timestamped):
    production_date = models.DateField(unique=True)
    status = models.CharField(max_length=20, choices=[('OPEN', 'Open'), ('STARTED', 'Started'), ('COMPLETE', 'Complete')], default='OPEN')


class ProductionPlanItem(Timestamped):
    production_plan = models.ForeignKey(ProductionPlan, on_delete=models.PROTECT, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    confirmed_quantity = models.PositiveIntegerField(default=0)
    forecast_quantity = models.PositiveIntegerField(default=0)
    planned_quantity = models.PositiveIntegerField(default=0)
    produced_quantity = models.PositiveIntegerField(default=0)
    derived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['production_plan', 'product'], name='unique_plan_product')]


class ProductionBatch(Timestamped):
    plan_item = models.ForeignKey(ProductionPlanItem, on_delete=models.PROTECT, related_name='batches')
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    notes = models.TextField(blank=True)


class ForecastSnapshot(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT)
    location = models.ForeignKey(CustomerLocation, on_delete=models.PROTECT)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    delivery_date = models.DateField(db_index=True)
    production_date = models.DateField(db_index=True)
    forecast_quantity = models.PositiveIntegerField()
    confirmed_at_snapshot = models.PositiveIntegerField(default=0)
    sample_size = models.PositiveSmallIntegerField()
    confidence = models.CharField(max_length=20)
    method = models.CharField(max_length=100)
    evidence = models.JSONField(default=dict)
    actual_quantity = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['location', 'product', 'delivery_date', 'created_at'])]


class MasterDataChange(models.Model):
    model_name = models.CharField(max_length=100)
    record_key = models.CharField(max_length=200)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_name(self):
        return {
            'Product': 'Product', 'ProductSourceRecord': 'Workbook source', 'ProductZonePrice': 'Zone price',
            'Customer': 'Customer', 'CustomerLocation': 'Customer delivery details', 'CustomerProduct': 'Customer product settings',
            'CustomerPriceOverride': 'Special price', 'CustomerDeliveryRule': 'Delivery rule',
            'CustomerAccess': 'Customer access', 'User': 'Login',
        }.get(self.model_name.rsplit('.', 1)[-1], 'Record')

    @property
    def source_label(self):
        if self.source.startswith('nelson:'):
            return 'Workbook import · ' + self.source.split(':', 1)[1]
        if self.source.startswith('import:'):
            return 'Data import · ' + self.source.rsplit(':', 1)[-1]
        return {
            'workspace': 'Administration edit', 'admin': 'Administration edit',
            'workspace-delete': 'Special price deleted',
            'workspace:zone-prices': 'Zone prices updated',
            'workspace:price-period-closed': 'Previous price period closed',
            'workspace:user-created': 'Login created', 'workspace:user-edited': 'Login updated',
            'migration:store-only-access': 'Access converted to stores',
            'workspace:store-delivery': 'Customer delivery rules updated',
            'migration:store-delivery': 'Delivery rules consolidated',
            'workspace:customer-delivery': 'Customer delivery details updated',
            'workspace:customer-products': 'Customer product settings updated',
            'migration:customer-delivery-record': 'Customer delivery record created',
        }.get(self.source, self.source)
