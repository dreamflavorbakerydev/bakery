"""Customer catalogs: the complete active catalog unless a custom list is configured."""
from bakery.models import CustomerProduct, Product


def uses_custom_catalog(customer, configured=None):
    if customer.catalog_mode != 'AUTO':
        return customer.catalog_mode == 'CUSTOM'
    return bool(configured) if configured is not None else CustomerProduct.objects.filter(customer=customer).exists()


def product_is_available(customer, product):
    """Use the same default/full-catalog and custom-list rules as ordering."""
    if not customer.active or not product.active:
        return False
    return not uses_custom_catalog(customer) or CustomerProduct.objects.filter(
        customer=customer, product=product, active=True).exists()


def catalog_links(customer):
    if not customer.active:
        return []
    configured = list(CustomerProduct.objects.filter(customer=customer).select_related('product'))
    if uses_custom_catalog(customer, configured):
        # Inactive rows still mean this customer has an explicitly configured list.
        return [link for link in configured if link.active and link.product.active]
    by_product = {link.product_id: link for link in configured}
    return [by_product.get(product.pk) or CustomerProduct(customer=customer, product=product)
            for product in Product.objects.filter(active=True).order_by('product_name', 'pk')]
