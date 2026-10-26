from django.contrib import admin
from bakery import models as m
from bakery.forms import AccessForm, DeliveryRuleForm, LocationForm
from bakery.services.access import is_office
from bakery.services.audit import record_change, snapshot

admin.site.site_header = 'Bakery · Administration'
admin.site.site_title = 'Bakery'
admin.site.index_title = 'Master data & access'


class OfficeAdmin(admin.ModelAdmin):
    list_per_page = 40
    save_on_top = True

    def has_module_permission(self, request):
        return is_office(request.user) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return is_office(request.user) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return is_office(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return is_office(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Deactivate master records rather than deleting business history.
        return False

    def save_model(self, request, obj, form, change):
        before = snapshot(type(obj).objects.get(pk=obj.pk)) if change else {}
        if isinstance(obj, m.CustomerPriceOverride) and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        record_change(obj, before, 'admin', request.user)


@admin.register(m.Customer)
class CustomerAdmin(OfficeAdmin):
    list_display = ['id', 'customer_name', 'customer_code', 'phone', 'city', 'pricing_zone', 'active']
    search_fields = ['=id', 'customer_code', 'customer_name', 'address', 'city', 'phone']
    readonly_fields = ['id']
    list_filter = ['active', 'pricing_zone']


@admin.register(m.CustomerLocation)
class LocationAdmin(OfficeAdmin):
    form = LocationForm
    list_display = ['location_code', 'location_name', 'customer', 'city', 'active']
    search_fields = ['location_code', 'location_name', 'customer__customer_name']
    list_filter = ['active', 'state']
    autocomplete_fields = ['customer']
    list_select_related = ['customer']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        form.save_delivery_rule(request.user)


@admin.register(m.Product)
class ProductAdmin(OfficeAdmin):
    list_display = ['internal_product_code', 'product_name', 'category', 'pack_size', 'unit_of_measure', 'active']
    search_fields = ['internal_product_code', 'product_name', 'upc']
    list_filter = ['active', 'category']


@admin.register(m.CustomerProduct)
class CustomerProductAdmin(OfficeAdmin):
    list_display = ['customer', 'product', 'vendor_id', 'customer_sku', 'active']
    search_fields = ['customer__customer_name', 'product__product_name', 'vendor_id', 'customer_sku']
    list_filter = ['active']
    autocomplete_fields = ['customer', 'product']
    list_select_related = ['customer', 'product']


@admin.register(m.ProductZonePrice)
class ZonePriceAdmin(OfficeAdmin):
    list_display = ['product', 'zone', 'price', 'effective_date', 'expiration_date', 'active']
    search_fields = ['product__product_name', 'product__internal_product_code']
    list_filter = ['zone', 'active']
    autocomplete_fields = ['product']
    list_select_related = ['product']


@admin.register(m.CustomerPriceOverride)
class OverrideAdmin(OfficeAdmin):
    list_display = ['customer', 'product', 'override_price', 'effective_date', 'expiration_date', 'active']
    search_fields = ['customer__customer_name', 'product__product_name']
    list_filter = ['active']
    autocomplete_fields = ['customer', 'product']
    list_select_related = ['customer', 'product']
    readonly_fields = ['created_by']


@admin.register(m.CustomerAccess)
class AccessAdmin(OfficeAdmin):
    form = AccessForm
    list_display = ['user', 'customer', 'location', 'active']
    autocomplete_fields = ['user', 'location']
    list_select_related = ['user', 'customer', 'location']


@admin.register(m.CustomerDeliveryRule)
class DeliveryRuleAdmin(OfficeAdmin):
    form = DeliveryRuleForm
    list_display = ['customer', 'location', 'delivery_days', 'production_lead_days', 'late_order_policy']
    autocomplete_fields = ['location']
    list_select_related = ['customer', 'location']


@admin.register(m.MasterDataChange)
class AuditAdmin(OfficeAdmin):
    list_display = ['created_at', 'model_name', 'record_key', 'source', 'actor']
    list_filter = ['model_name']
    readonly_fields = [field.name for field in m.MasterDataChange._meta.fields]
    list_select_related = ['actor']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# Order and production schemas are deliberately not editable through admin.
# Their transactional services and interfaces belong to subsequent phases.
