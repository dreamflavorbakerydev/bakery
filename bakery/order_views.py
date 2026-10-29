from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from bakery import models as m
from bakery.services.access import locations_for, orders_for, is_office, is_production
from bakery.services.delivery import available_delivery_dates
from bakery.services.orders import create_draft, submit_order, change_status, TRANSITIONS
from bakery.services.pricing import PricingBook
from bakery.services.catalog import catalog_links
from bakery.services.notifications import has_new_orders, mark_orders_seen
from bakery.views import office_required, paginate


class OrderForm(forms.Form):
    delivery_date = forms.ChoiceField(label='Delivery date')
    customer_po_number = forms.CharField(label='Your PO / reference', max_length=100, required=False)
    notes = forms.CharField(label='Delivery notes', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, dates, links, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['delivery_date'].choices = [(item.delivery_date.isoformat(),
            f'{item.delivery_date:%a, %b %d} — order by {item.cutoff_display}' + (' (bakery approval needed)' if item.requires_approval else '')) for item in dates]
        for link in links:
            self.fields[f'qty_{link.product_id}'] = forms.IntegerField(min_value=0, max_value=100000,
                required=False, initial=0, widget=forms.NumberInput(attrs={'min': 0, 'step': 1, 'inputmode': 'numeric', 'class': 'quantity-input'}))


class DateFilter(forms.Form):
    date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


@login_required
def new_order(request):
    locations = locations_for(request.user).filter(active=True, customer__active=True).select_related('customer')
    chosen = request.POST.get('location') if request.method == 'POST' else request.GET.get('location')
    if not chosen:
        if locations.count() == 1:
            return redirect(f'{request.path}?location={locations.first().pk}')
        return render(request, 'bakery/order_locations.html', {'locations': locations})
    location = get_object_or_404(locations, pk=chosen) if str(chosen).isdigit() else None
    if not location:
        raise PermissionDenied
    error = None
    try:
        dates = available_delivery_dates(location.customer, location, horizon=60)
    except ValidationError as exc:
        dates, error = [], '; '.join(exc.messages)
    links = catalog_links(location.customer)
    initial = {}
    reorder = request.GET.get('reorder')
    if reorder:
        if not reorder.isdigit():
            raise Http404
        prior = get_object_or_404(orders_for(request.user), pk=reorder, customer_location=location)
        allowed = {link.product_id for link in links}
        removed = []
        for line in prior.items.all():
            if line.product_id in allowed:
                initial[f'qty_{line.product_id}'] = line.quantity
            else:
                removed.append(line.product_name)
        if removed:
            messages.warning(request, 'Unavailable products omitted from reorder: ' + ', '.join(removed))
    form = OrderForm(request.POST if request.method == 'POST' else None, initial=initial, dates=dates, links=links)
    if request.method == 'POST' and form.is_valid():
        allowed_keys = {f'qty_{link.product_id}' for link in links}
        if any(key.startswith('qty_') and key not in allowed_keys for key in request.POST):
            form.add_error(None, 'A selected product is no longer available. Refresh this page.')
        else:
            try:
                order = create_draft(request.user, location.pk,
                    forms.DateField().clean(form.cleaned_data['delivery_date']),
                    {link.product_id: form.cleaned_data[f'qty_{link.product_id}'] or 0 for link in links},
                    form.cleaned_data['customer_po_number'], form.cleaned_data['notes'])
                return redirect('order-detail', pk=order.pk)
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
    pricing_date = next((item.delivery_date for item in dates if item.delivery_date.isoformat() == form['delivery_date'].value()),
        dates[0].delivery_date if dates else timezone.localdate())
    if request.method != 'POST' and dates:
        form.initial['delivery_date'] = pricing_date.isoformat()
    rows = []
    try:
        book = PricingBook(location.customer, pricing_date, links=links)
        for link in links:
            rows.append((link, book.resolve(link.product), form[f'qty_{link.product_id}']))
    except ValidationError as exc:
        error = '; '.join(exc.messages)
    return render(request, 'bakery/order_form.html', {'form': form, 'rows': rows, 'location': location,
        'setup_error': error, 'has_dates': bool(dates), 'pricing_date': pricing_date,
        'categories': sorted({link.product.category for link in links if link.product.category}),
        'product_count': len(links)})


@login_required
def order_prices(request):
    chosen = request.GET.get('location', '')
    if not chosen.isdecimal():
        raise Http404
    location = get_object_or_404(locations_for(request.user).select_related('customer'),
        pk=chosen, active=True, customer__active=True)
    try:
        day = forms.DateField().clean(request.GET.get('date'))
        dates = available_delivery_dates(location.customer, location, horizon=60)
        if day not in {item.delivery_date for item in dates}:
            raise ValidationError('Choose an available delivery date.')
        book = PricingBook(location.customer, day)
        prices = {str(product_id): (str(int(result.price * 100)) if result.price is not None else None)
                  for product_id, link in book.links.items() for result in [book.resolve(link.product)]}
    except ValidationError as exc:
        return JsonResponse({'error': '; '.join(exc.messages)}, status=400)
    response = JsonResponse({'date': day.isoformat(), 'prices': prices})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def order_list(request):
    opened_at = timezone.now()
    records = orders_for(request.user).select_related('customer', 'customer_location').order_by('requested_delivery_date', '-created_at')
    form = DateFilter(request.GET)
    if form.is_valid() and form.cleaned_data['date']:
        records = records.filter(requested_delivery_date=form.cleaned_data['date'])
    elif form.errors:
        records = records.none()
    office = is_office(request.user)
    status_filter = 'all'
    status_groups = []
    scope = request.GET.get('scope', 'overview' if office else 'all')
    if scope == 'pending':
        records = records.exclude(status__in=[m.OrderStatus.DRAFT, m.OrderStatus.CANCELLED, m.OrderStatus.DELIVERED, m.OrderStatus.INVOICED])
    elif scope == 'approval':
        records = records.filter(status=m.OrderStatus.SUBMITTED, requires_approval=True)
    elif scope == 'overview' and office:
        lifecycle_statuses = [m.OrderStatus.SUBMITTED, m.OrderStatus.CONFIRMED, m.OrderStatus.PRODUCTION,
            m.OrderStatus.READY_TO_PICK, m.OrderStatus.PICKED, m.OrderStatus.LOADED,
            m.OrderStatus.OUT_FOR_DELIVERY, m.OrderStatus.DELIVERED]
        overview_records = records.filter(status__in=lifecycle_statuses)
        status_filter = request.GET.get('status', 'active')
        if status_filter == 'active':
            records = overview_records
        elif status_filter in lifecycle_statuses:
            records = records.filter(status=status_filter)
        else:
            status_filter = 'all'
        status_counts = dict(overview_records.order_by().values('status').annotate(count=Count('pk')).values_list('status', 'count'))
        status_groups = [{'value': status, 'label': label, 'count': status_counts.get(status, 0)}
            for status, label in m.OrderStatus.choices if status in lifecycle_statuses]
    else:
        scope = 'all'
        status_filter = 'all'
        status_groups = []
    totals = records.aggregate(value=Sum('total'))
    if not form.errors and not request.GET.get('date') and not request.GET.get('status') and scope in ('all', 'overview', 'pending'):
        mark_orders_seen(request.user, opened_at)
    return render(request, 'bakery/orders.html', {'page': paginate(request, records), 'filter_form': form,
        'scope': scope, 'status_filter': status_filter, 'status_groups': status_groups,
        'selected_date': form.cleaned_data.get('date') if form.is_valid() else None,
        'order_count': records.count(), 'order_total': totals['value'] or Decimal('0')})


@require_GET
@office_required
def order_notifications(request):
    response = JsonResponse({'has_new_orders': has_new_orders(request.user)})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def order_detail(request, pk):
    order = get_object_or_404(orders_for(request.user).select_related('customer', 'customer_location'), pk=pk)
    actions = [(status, m.OrderStatus(status).label) for status in TRANSITIONS.get(order.status, [])] if is_office(request.user) else []
    return render(request, 'bakery/order_detail.html', {'order': order, 'lines': order.items.select_related('product'),
        'actions': actions, 'changes': order.changes.select_related('user').order_by('-created_at')})


@require_POST
@login_required
def order_submit(request, pk):
    get_object_or_404(orders_for(request.user), pk=pk)
    try:
        order = submit_order(request.user, pk)
        messages.success(request, 'Order submitted. The bakery will review this late order.' if order.requires_approval else 'Order submitted to the bakery.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('order-detail', pk=pk)


@require_POST
@office_required
def order_status(request, pk):
    get_object_or_404(m.Order, pk=pk)
    try:
        change_status(request.user, pk, request.POST.get('status'))
        messages.success(request, 'Order status updated.')
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('order-detail', pk=pk)


@login_required
def bake_plan(request):
    if not (is_office(request.user) or is_production(request.user)):
        raise PermissionDenied
    form = DateFilter(request.GET if request.GET else {'date': timezone.localdate().isoformat()})
    selected = form.cleaned_data.get('date') if form.is_valid() else None
    selected = selected or timezone.localdate()
    basis = 'delivery' if request.GET.get('basis') == 'delivery' else 'production'
    field = 'order__requested_delivery_date' if basis == 'delivery' else 'required_production_date'
    active = [m.OrderStatus.SUBMITTED, m.OrderStatus.CONFIRMED, m.OrderStatus.PRODUCTION, m.OrderStatus.READY_TO_PICK,
        m.OrderStatus.PICKED, m.OrderStatus.LOADED, m.OrderStatus.OUT_FOR_DELIVERY]
    base = m.OrderItem.objects.filter(order__status__in=active)
    items = base.filter(**{field: selected}).select_related('product', 'order') if not form.errors else base.none()
    grouped = {}
    for item in items:
        key = (item.product_id, item.pack_size, item.unit_of_measure, item.units_per_tray)
        row = grouped.setdefault(key, {'product': item.product, 'pack_size': item.pack_size,
            'unit': item.unit_of_measure, 'units_per_tray': item.units_per_tray, 'quantity': 0,
            'approval_quantity': 0, 'units': 0, 'orders': set(), 'customers': set(), 'delivery_dates': set()})
        if item.order.requires_approval:
            row['approval_quantity'] += item.quantity
        else:
            row['quantity'] += item.quantity
            row['units'] += item.quantity * item.pack_size
        row['orders'].add(item.order_id)
        row['customers'].add(item.order.customer_id)
        row['delivery_dates'].add(item.order.requested_delivery_date)
    rows = sorted(grouped.values(), key=lambda row: (row['product'].product_name, row['unit'], row['pack_size']))
    for row in rows:
        row['trays'] = (row['units'] + row['units_per_tray'] - 1) // row['units_per_tray'] if row['units_per_tray'] else None
    upcoming = base.order_by(field).values_list(field, flat=True).distinct()[:30]
    return render(request, 'bakery/bake_plan.html', {'rows': rows, 'filter_form': form, 'selected_date': selected,
        'basis': basis, 'upcoming': upcoming, 'previous_date': selected - timedelta(days=1), 'next_date': selected + timedelta(days=1),
        'units_total': sum(row['units'] for row in rows), 'product_count': len({row['product'].pk for row in rows})})
