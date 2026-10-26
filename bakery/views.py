import csv
import tempfile
from functools import wraps
from pathlib import Path
from zipfile import BadZipFile
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery, Value
from django.db.models.functions import Coalesce, Lower, NullIf
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from bakery import models as m
from bakery.forms import ImportForm
from bakery.services.access import customers_for, is_office, is_production, locations_for, products_for
from bakery.services.delivery import available_delivery_dates
from bakery.services.imports import ImportFailure, SCHEMAS, import_master_data
from bakery.services.pricing import PricingBook, current_period
from bakery.services.nelson import import_nelson
from bakery.services.tables import sort_records


def office_required(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_office(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def paginate(request, records):
    return Paginator(records, 30).get_page(request.GET.get('page'))


@login_required
def dashboard(request):
    if is_office(request.user):
        counts = {
            'customers': m.Customer.objects.filter(active=True).count(),
            'locations': m.CustomerLocation.objects.filter(active=True, customer__active=True).count(),
            'products': m.Product.objects.filter(active=True).count(),
            'links': m.CustomerProduct.objects.filter(active=True, customer__active=True, product__active=True).count(),
        }
        checks = [
            ('Customer accounts', 'Bring your customer list into one place.', counts['customers'] > 0, 'customers'),
            ('Customer delivery details', 'Keep customer contact and delivery details together.', counts['locations'] > 0, 'customers'),
            ('Product catalog', 'Preserve product codes, packs, and familiar names.', counts['products'] > 0, 'products'),
            ('Customer product access', 'Assign permitted products and customer item numbers.', counts['links'] > 0, 'imports'),
            ('Zone pricing', 'Add effective dates and each zone’s prices.', m.ProductZonePrice.objects.filter(active=True).exists(), 'products'),
            ('Customer delivery calendars', 'Set each customer’s delivery days, deadlines, and late-order rules.', m.CustomerDeliveryRule.objects.exists(), 'administration'),
            ('Logins & access', 'Manage logins, roles, and customer assignments.', m.CustomerAccess.objects.filter(active=True).exists(), 'workspace-users'),
        ]
        completed = sum(check[2] for check in checks)
        return render(request, 'bakery/operations_dashboard.html', {'counts': counts, 'checks': checks,
            'pending_count': m.Order.objects.exclude(status__in=[m.OrderStatus.DRAFT, m.OrderStatus.CANCELLED, m.OrderStatus.DELIVERED, m.OrderStatus.INVOICED]).count(),
            'approval_count': m.Order.objects.filter(status=m.OrderStatus.SUBMITTED, requires_approval=True).count(),
            'completed': completed, 'progress': round(completed / len(checks) * 100),
            'changes': m.MasterDataChange.objects.select_related('actor').order_by('-created_at')[:5], 'today': timezone.localdate()})
    if is_production(request.user):
        return redirect('bake-plan')
    from bakery.services.access import orders_for
    return render(request, 'bakery/order_home.html', {'customers': customers_for(request.user),
        'recent_orders': orders_for(request.user).exclude(status=m.OrderStatus.DRAFT).select_related('customer_location').order_by('-submitted_at')[:8],
        'locations': locations_for(request.user).select_related('customer')})


@office_required
def customers(request):
    query = request.GET.get('q', '').strip()
    records = m.Customer.objects.annotate(location_count=Count('locations', distinct=True)).prefetch_related(
        Prefetch('locations', queryset=m.CustomerLocation.objects.select_related('delivery_rule').order_by('pk'),
                 to_attr='delivery_locations')).order_by('customer_name')
    if query:
        condition = (Q(customer_name__icontains=query) | Q(customer_code__icontains=query) |
                     Q(address__icontains=query) | Q(city__icontains=query) | Q(phone__icontains=query))
        if query.isdecimal():
            condition |= Q(pk=int(query))
        records = records.filter(condition)
    if request.GET.get('sort') == 'delivery':
        rules = m.CustomerDeliveryRule.objects.filter(location_id=OuterRef('pk')).values('delivery_days')
        addresses = m.CustomerLocation.objects.filter(customer_id=OuterRef('pk')).annotate(
            days=Subquery(rules[:1])).order_by('pk').values('days')
        records = records.annotate(delivery_days_sort=Subquery(addresses[:1]))
    records, sorting = sort_records(request, records, {
        'id': 'pk', 'customer': Lower('customer_name'), 'phone': NullIf('phone', Value('')),
        'address': (Lower(NullIf('address', Value(''))), Lower('city')),
        'zone': 'pricing_zone', 'locations': 'location_count', 'delivery': 'delivery_days_sort', 'status': 'active',
    }, 'customer')
    return render(request, 'bakery/customers.html', {'page': paginate(request, records), 'q': query, **sorting})


@office_required
def products(request):
    query = request.GET.get('q', '').strip()
    records = m.Product.objects.select_related('source_record').prefetch_related(Prefetch('zone_prices',
        queryset=current_period(m.ProductZonePrice.objects.all(), timezone.localdate()).order_by('zone'), to_attr='current_prices'))
    category = request.GET.get('category', '')
    if category:
        records = records.filter(category=category)
    if request.GET.get('review') == '1':
        records = records.exclude(source_record__review_notes='').filter(source_record__isnull=False)
    if query:
        records = records.filter(Q(product_name__icontains=query) | Q(internal_product_code__icontains=query) | Q(upc__icontains=query) | Q(sku__icontains=query))
    columns = {
        'product': Lower('product_name'),
        'sku': Coalesce(NullIf('sku', Value('')), NullIf('upc', Value('')), 'internal_product_code'),
        'size': Lower(NullIf('size', Value(''))), 'tray': 'units_per_tray',
        'zone1': 'sort_price', 'zone2': 'sort_price', 'zone3': 'sort_price',
    }
    if request.GET.get('sort') in ('zone1', 'zone2', 'zone3'):
        zone = int(request.GET['sort'][-1])
        prices = current_period(m.ProductZonePrice.objects.filter(product_id=OuterRef('pk'), zone=zone), timezone.localdate())
        records = records.annotate(sort_price=Subquery(prices.order_by('-effective_date', '-pk').values('price')[:1]))
    records, sorting = sort_records(request, records, columns, 'product')
    page = paginate(request, records)
    for product in page:
        by_zone = {price.zone: price.price for price in product.current_prices}
        product.display_prices = [by_zone.get(zone) for zone in range(1, 4)]
    return render(request, 'bakery/products.html', {'page': page, 'q': query, **sorting,
        'categories': m.Product.objects.order_by('category').values_list('category', flat=True).distinct(),
        'category': category, 'product_count': m.Product.objects.count(),
        'review_count': m.ProductSourceRecord.objects.exclude(review_notes='').count()})


@login_required
def catalog(request, pk):
    customer = get_object_or_404(customers_for(request.user), pk=pk, active=True)
    links = products_for(request.user, customer)
    query = request.GET.get('q', '').strip()
    if query:
        links = [link for link in links if query.casefold() in ' '.join((link.product.product_name,
            link.product.upc, link.product.internal_product_code, link.customer_sku, link.vendor_id,
            link.customer_product_name, link.product.sku)).casefold()]
    page = paginate(request, links)
    try:
        book = PricingBook(customer, timezone.localdate(timezone=ZoneInfo(customer.timezone)), links=links)
    except ValidationError:
        messages.error(request, 'Your pricing needs bakery office review. Please contact the office.')
        return redirect('dashboard')
    rows = [(link, book.resolve(link.product)) for link in page]
    delivery = []
    for location in locations_for(request.user).filter(customer=customer):
        try:
            delivery.append((location, available_delivery_dates(customer, location)[:3], None))
        except ValidationError as exc:
            delivery.append((location, [], '; '.join(exc.messages)))
    return render(request, 'bakery/catalog.html', {'customer': customer, 'rows': rows, 'page': page, 'q': query, 'delivery': delivery})


@office_required
def pricing(request):
    target = reverse('price-records')
    if request.GET:
        target += '?' + request.GET.urlencode()
    return redirect(target)


@office_required
def price_records(request):
    query = request.GET.get('q', '').strip()
    prices = m.ProductZonePrice.objects.select_related('product').order_by('product__product_name', 'zone', '-effective_date')
    if query:
        prices = prices.filter(Q(product__product_name__icontains=query) | Q(product__internal_product_code__icontains=query) | Q(product__sku__icontains=query))
    prices, sorting = sort_records(request, prices, {
        'product': Lower('product__product_name'), 'zone': 'zone', 'ordering': 'price',
        'retail': 'retail_price', 'return': 'return_price', 'effective': 'effective_date', 'expires': 'expiration_date',
    }, 'product')
    return render(request, 'bakery/pricing.html', {'page': paginate(request, prices), 'q': query, **sorting})


@office_required
def import_data(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    report = None
    if request.method == 'POST' and form.is_valid():
        upload = form.cleaned_data['file']
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(upload.name).suffix) as target:
                temporary = Path(target.name)
                for chunk in upload.chunks():
                    target.write(chunk)
            if form.cleaned_data['kind'] == 'nelson':
                report, duplicates = import_nelson(temporary, form.cleaned_data['effective_date'],
                    form.cleaned_data['dry_run'], source_name=upload.name, actor=request.user)
                if duplicates:
                    messages.warning(request, f'Duplicate SKU preserved as separate products: {", ".join(duplicates)}')
            else:
                report = import_master_data(form.cleaned_data['kind'], temporary, form.cleaned_data['dry_run'], source_name=upload.name)
            action = 'Validated without saving' if form.cleaned_data['dry_run'] else 'Imported successfully'
            messages.success(request, f'{action}: {report.inserted} new, {report.updated} changed, {report.skipped} unchanged.')
        except (ImportFailure, ValidationError, OSError, BadZipFile, UnicodeError) as exc:
            form.add_error('file', str(exc))
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return render(request, 'bakery/imports.html', {'form': form, 'schemas': SCHEMAS})


@office_required
def import_template(request, kind):
    if kind not in SCHEMAS:
        raise Http404
    _, required, optional = SCHEMAS[kind]
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{kind}.csv"'
    csv.writer(response).writerow(required + optional)
    return response


@login_required
def account(request):
    return render(request, 'bakery/account.html', {'assigned_customers': customers_for(request.user) if not is_office(request.user) else [],
        'assigned_locations': locations_for(request.user).select_related('customer') if not is_office(request.user) else []})
