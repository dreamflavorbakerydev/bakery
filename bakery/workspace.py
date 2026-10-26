"""Custom administration using the Bakery design and Django's validated forms."""
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from bakery import forms, models as m
from bakery.services.audit import record_change, snapshot
from bakery.services.pricing import current_period
from bakery.services.tables import sort_records
from bakery.services.catalog import uses_custom_catalog
from bakery.views import office_required, paginate

ENTITIES = {
    'customers': (m.Customer, forms.CustomerForm, 'Customers', ['customer_name', 'customer_code']),
    'locations': (m.CustomerLocation, forms.LocationForm, 'Customers', ['location_name', 'location_code', 'customer__customer_name']),
    'products': (m.Product, forms.ProductForm, 'Products', ['product_name', 'sku', 'upc', 'internal_product_code']),
    'availability': (m.CustomerProduct, forms.CustomerProductForm, 'Product availability', ['product__product_name', 'customer__customer_name', 'customer_sku', 'vendor_id']),
    'overrides': (m.CustomerPriceOverride, forms.OverrideForm, 'Special prices', ['product__product_name', 'customer__customer_name', 'product__sku']),
    'delivery': (m.CustomerDeliveryRule, forms.DeliveryRuleForm, 'Delivery rules', ['customer__customer_name', 'location__location_name']),
    'access': (m.CustomerAccess, forms.AccessForm, 'Customer access', ['user__username', 'customer__customer_name', 'location__location_name']),
}


def entity(kind):
    if kind not in ENTITIES:
        raise Http404
    return ENTITIES[kind]


def require_permission(user, action, model):
    if not user.has_perm(f'{model._meta.app_label}.{action}_{model._meta.model_name}'):
        raise PermissionDenied


@office_required
@require_http_methods(['GET', 'POST'])
def special_price_delete(request, pk):
    require_permission(request.user, 'delete', m.CustomerPriceOverride)
    if request.method == 'POST':
        with transaction.atomic():
            price = get_object_or_404(m.CustomerPriceOverride.objects.select_for_update(), pk=pk)
            m.MasterDataChange.objects.create(model_name=price._meta.label, record_key=str(price.pk),
                before=snapshot(price), after={}, source='workspace-delete', actor=request.user)
            price.delete()
        messages.success(request, 'Special price deleted.')
        return redirect('special-prices')
    price = get_object_or_404(m.CustomerPriceOverride.objects.select_related('customer', 'product'), pk=pk)
    return render(request, 'bakery/special_price_delete.html', {'price': price, 'kind': 'overrides'})


@office_required
def administration(request):
    return render(request, 'bakery/administration.html', {
        'can_manage_users': request.user.has_perm('auth.view_user') or request.user.has_perm('bakery.view_customeraccess'),
        'user_count': get_user_model().objects.count(),
        'changes': m.MasterDataChange.objects.select_related('actor').order_by('-created_at')[:8]})


@office_required
def records(request, kind):
    model, _, title, searchable = entity(kind)
    require_permission(request.user, 'view', model)
    if kind == 'availability':
        if request.GET.get('customer'):
            customer = get_object_or_404(m.Customer, pk=request.GET['customer'])
            return redirect(reverse('customer-edit', args=[customer.pk]) + '#customer-products')
        return redirect('customers')
    if kind in ('customers', 'locations', 'delivery'):
        if request.GET.get('customer'):
            return redirect('customer-detail', pk=get_object_or_404(m.Customer, pk=request.GET['customer']).pk)
        target = reverse('customers')
        if request.GET:
            target += '?' + request.GET.urlencode()
        return redirect(target)
    if kind == 'access':
        target = reverse('workspace-users')
        if request.GET:
            target += '?' + request.GET.urlencode()
        return redirect(target)
    if kind == 'delivery':
        target = reverse('workspace-records', args=['locations'])
        if request.GET:
            target += '?' + request.GET.urlencode()
        return redirect(target)
    query = request.GET.get('q', '').strip()
    queryset = model.objects.all().order_by('-pk')
    if kind in ('locations', 'availability', 'overrides', 'delivery', 'access'):
        queryset = queryset.select_related()
    if kind == 'locations':
        queryset = queryset.select_related('customer', 'delivery_rule')
    if query:
        condition = Q()
        for field in searchable:
            condition |= Q(**{field + '__icontains': query})
        queryset = queryset.filter(condition)
    if request.GET.get('customer') and kind in ('locations', 'availability', 'overrides', 'delivery', 'access'):
        if not request.GET['customer'].isdecimal():
            raise Http404
        queryset = queryset.filter(customer_id=request.GET['customer'])
    sorting = {}
    if kind == 'overrides':
        queryset, sorting = sort_records(request, queryset, {
            'product': Lower('product__product_name'), 'customer': Lower('customer__customer_name'),
            'price': 'override_price', 'effective': 'effective_date', 'expires': 'expiration_date', 'status': 'active',
        }, 'customer')
    return render(request, 'bakery/records.html', {'kind': kind, 'title': title, 'page': paginate(request, queryset), **sorting,
        'q': query, 'can_add': request.user.has_perm(f'bakery.add_{model._meta.model_name}')})


@office_required
def record_editor(request, kind, pk=None):
    model, form_class, title, _ = entity(kind)
    require_permission(request.user, 'change' if pk else 'add', model)
    if kind == 'availability' and request.method == 'GET':
        customer_id = get_object_or_404(m.CustomerProduct, pk=pk).customer_id if pk else request.GET.get('customer')
        if customer_id:
            customer = get_object_or_404(m.Customer, pk=customer_id)
            return redirect(reverse('customer-edit', args=[customer.pk]) + '#customer-products')
        return redirect('customers')
    if kind == 'customers':
        if request.method == 'POST':
            return customer_editor(request, pk=pk)
        return redirect('customer-edit', pk=pk) if pk else redirect('customer-new')
    if kind == 'locations':
        if pk:
            location = get_object_or_404(m.CustomerLocation, pk=pk)
            target = reverse('customer-edit', args=[location.customer_id])
            return redirect(target + '?location=' + str(location.pk))
        if request.GET.get('customer'):
            return redirect('customer-edit', pk=get_object_or_404(m.Customer, pk=request.GET['customer']).pk)
        return redirect('customer-new')
    if kind == 'delivery':
        if pk:
            rule = get_object_or_404(m.CustomerDeliveryRule, pk=pk)
            return redirect(reverse('customer-edit', args=[rule.customer_id]) + '?location=' + str(rule.location_id))
        if request.GET.get('location'):
            location = get_object_or_404(m.CustomerLocation, pk=request.GET['location'])
            return redirect(reverse('customer-edit', args=[location.customer_id]) + '?location=' + str(location.pk))
        target = reverse('customers')
        if request.GET.get('customer'):
            target += '?customer=' + request.GET['customer']
        return redirect(target)
    obj = get_object_or_404(model, pk=pk) if pk else None
    initial = {'effective_date': timezone.localdate()}
    if request.GET.get('customer') and 'customer' in form_class._meta.fields:
        initial['customer'] = get_object_or_404(m.Customer, pk=request.GET['customer'])
    if kind == 'access' and request.GET.get('user'):
        initial['user'] = get_object_or_404(get_user_model(), pk=request.GET['user'])
    form_options = {}
    if kind == 'locations':
        has_rule = obj and m.CustomerDeliveryRule.objects.filter(location=obj).exists()
        form_options['edit_delivery'] = request.user.has_perm(
            'bakery.change_customerdeliveryrule' if has_rule else 'bakery.add_customerdeliveryrule')
    form = form_class(request.POST or None, instance=obj, initial=initial, **form_options)
    if kind == 'access' and (obj or initial.get('user')):
        form.fields['user'].disabled = True
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                before = snapshot(model.objects.select_for_update().get(pk=pk)) if pk else {}
                saved = form.save(commit=False)
                if isinstance(saved, m.CustomerPriceOverride) and not saved.created_by_id:
                    saved.created_by = request.user
                saved.full_clean()
                saved.save()
                record_change(saved, before, 'workspace', request.user)
                if kind == 'locations':
                    form.save_delivery_rule(request.user)
            messages.success(request, f'{title.rstrip("s")} saved.')
            if kind == 'products':
                return redirect('product-detail', pk=saved.pk)
            if kind == 'customers':
                return redirect('customer-detail', pk=saved.pk)
            if kind == 'overrides':
                return redirect('special-prices')
            if kind == 'availability':
                return redirect(reverse('customer-edit', args=[saved.customer_id]) + '#customer-products')
            if kind == 'access':
                return redirect('workspace-user-edit', pk=saved.user_id)
            return redirect('workspace-records', kind=kind)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
    return render(request, 'bakery/record_editor.html', {'form': form, 'kind': kind, 'title': 'Customer' if kind == 'locations' else title,
        'editing': obj is not None, 'obj': obj})


@office_required
def customer_editor(request, pk=None):
    require_permission(request.user, 'change' if pk else 'add', m.Customer)
    customer = get_object_or_404(m.Customer, pk=pk) if pk else m.Customer()
    locations = list(customer.locations.select_related('delivery_rule').order_by('pk')) if pk else []
    primary = locations[0] if locations else None
    location = primary
    if request.GET.get('location'):
        if not pk:
            raise Http404
        location = get_object_or_404(m.CustomerLocation, pk=request.GET['location'], customer=customer)
    location = location or m.CustomerLocation(customer=customer, location_code='MAIN')
    require_permission(request.user, 'change' if location.pk else 'add', m.CustomerLocation)
    contact_fields = ('address', 'city', 'state', 'zip', 'phone')
    customer_before = snapshot(customer) if customer.pk else {}
    location_before = snapshot(location) if location.pk else {}
    original_name = customer.customer_name
    original_contacts = {field: getattr(customer, field) for field in contact_fields}
    initial = {field: (getattr(location, field) or getattr(customer, field)) if location.pk == getattr(primary, 'pk', None)
               else getattr(location, field) for field in contact_fields} if location.pk else {}
    if location.pk:
        initial['active'] = customer.active and location.active
    form = forms.CustomerForm(request.POST or None, instance=customer, initial=initial)
    has_rule = bool(location.pk and getattr(location, 'delivery_rule', None))
    delivery_form = forms.CustomerDeliveryForm(request.POST or None, instance=location, edit_delivery=request.user.has_perm(
        'bakery.change_customerdeliveryrule' if has_rule else 'bakery.add_customerdeliveryrule'))
    can_catalog = all(request.user.has_perm('bakery.' + permission + '_customerproduct')
        for permission in ('view', 'add', 'change'))
    if request.method == 'POST' and not can_catalog and any(
            key.startswith(('catalog-', 'products-')) for key in request.POST):
        raise PermissionDenied
    catalog_mode = 'CUSTOM' if customer.pk and uses_custom_catalog(customer) else 'FULL'
    catalog_form = forms.CustomerCatalogForm(request.POST or None, prefix='catalog', initial={'mode': catalog_mode}) if can_catalog else None
    catalog_data = request.POST if request.method == 'POST' and 'products-TOTAL_FORMS' in request.POST else None
    product_forms = forms.CustomerCatalogProducts(catalog_data, instance=customer, prefix='products') if can_catalog else None
    if request.method == 'POST':
        valid_customer = form.is_valid()
        valid_delivery = delivery_form.is_valid()
        valid_catalog = not can_catalog or (catalog_form.is_valid() and (not product_forms.is_bound or product_forms.is_valid()))
        if valid_customer and valid_delivery and valid_catalog:
            try:
                with transaction.atomic():
                    saved = form.save(commit=False)
                    if can_catalog:
                        saved.catalog_mode = catalog_form.cleaned_data.get('mode') or catalog_mode
                    secondary = primary is not None and location.pk != primary.pk
                    if secondary:
                        for field, value in original_contacts.items():
                            setattr(saved, field, value)
                        saved.active = customer_before['active'] == 'True'
                    saved.full_clean()
                    saved.save()
                    record_change(saved, customer_before, 'workspace', request.user)
                    if product_forms and product_forms.is_bound:
                        product_forms.instance = saved
                        for product_form in product_forms:
                            if not product_form.has_changed():
                                continue
                            link = product_form.save(commit=False)
                            before = snapshot(m.CustomerProduct.objects.get(pk=link.pk)) if link.pk else {}
                            link.customer = saved
                            link.full_clean()
                            link.save()
                            record_change(link, before, 'workspace:customer-products', request.user)
                    location.customer = saved
                    if not location.pk or location.location_name == original_name:
                        location.location_name = saved.customer_name
                    for field in contact_fields:
                        setattr(location, field, form.cleaned_data[field])
                    location.active = form.cleaned_data['active']
                    location.full_clean()
                    location.save()
                    record_change(location, location_before, 'workspace:customer-delivery', request.user)
                    delivery_form.save_delivery_rule(request.user)
                messages.success(request, 'Customer details, delivery rules, and product settings saved.')
                return redirect('customer-detail', pk=saved.pk)
            except ValidationError as exc:
                form.add_error(None, '; '.join(exc.messages))
    return render(request, 'bakery/customer_editor.html', {
        'form': form, 'delivery_form': delivery_form, 'customer': customer, 'editing': pk is not None,
        'delivery_locations': locations, 'selected_location': location,
        'catalog_form': catalog_form, 'product_forms': product_forms,
    })


@office_required
def product_detail(request, pk):
    require_permission(request.user, 'view', m.Product)
    product = get_object_or_404(m.Product.objects.select_related('source_record'), pk=pk)
    prices = list(current_period(product.zone_prices.all(), timezone.localdate()).order_by('zone'))
    initial = {'effective_date': timezone.localdate()}
    for price in prices:
        for field in ('price', 'retail_price', 'return_price'):
            initial[f'zone_{price.zone}_{field}'] = getattr(price, field)
    form = forms.ZoneGridForm(initial=initial)
    return render(request, 'bakery/product_detail.html', {'product': product, 'zone_form': form,
        'zone_prices': prices, 'history': product.zone_prices.order_by('-effective_date', 'zone')[:15],
        'can_edit': request.user.has_perm('bakery.change_product'),
        'can_price': request.user.has_perm('bakery.add_productzoneprice') and request.user.has_perm('bakery.change_productzoneprice')})


@office_required
def product_prices(request, pk):
    require_permission(request.user, 'add', m.ProductZonePrice)
    require_permission(request.user, 'change', m.ProductZonePrice)
    product = get_object_or_404(m.Product, pk=pk)
    if request.method != 'POST':
        return redirect('product-detail', pk=pk)
    form = forms.ZoneGridForm(request.POST)
    if form.is_valid():
        try:
            with transaction.atomic():
                m.Product.objects.select_for_update().get(pk=pk)
                effective = form.cleaned_data['effective_date']
                for zone in range(1, 4):
                    previous = list(current_period(product.zone_prices.filter(zone=zone).select_for_update(), effective))
                    price = next((record for record in previous if record.effective_date == effective), None)
                    for record in previous:
                        if record is price:
                            continue
                        before = snapshot(record)
                        record.expiration_date = effective - timedelta(days=1)
                        record.full_clean()
                        record.save()
                        record_change(record, before, 'workspace:price-period-closed', request.user)
                    before = snapshot(price) if price else {}
                    price = price or m.ProductZonePrice(product=product, zone=zone, effective_date=effective)
                    for field in ('price', 'retail_price', 'return_price'):
                        setattr(price, field, form.cleaned_data[f'zone_{zone}_{field}'])
                    price.full_clean()
                    price.save()
                    record_change(price, before, 'workspace:zone-prices', request.user)
            messages.success(request, 'All three zone prices saved. Historical order prices stay unchanged.')
            return redirect('product-detail', pk=pk)
        except ValidationError as exc:
            form.add_error(None, '; '.join(exc.messages))
    return render(request, 'bakery/record_editor.html', {'form': form, 'kind': 'products', 'title': 'Zone prices', 'editing': True, 'obj': product})


@office_required
def customer_detail(request, pk):
    require_permission(request.user, 'view', m.Customer)
    customer = get_object_or_404(m.Customer, pk=pk)
    return render(request, 'bakery/customer_detail.html', {'customer': customer,
        'custom_catalog': uses_custom_catalog(customer),
        'overrides': customer.price_overrides.select_related('product').order_by('-effective_date')[:30],
        'locations': customer.locations.select_related('delivery_rule').all()})


@office_required
def users(request):
    can_view_access = request.user.has_perm('bakery.view_customeraccess')
    if not (request.user.has_perm('auth.view_user') or can_view_access):
        raise PermissionDenied
    query = request.GET.get('q', '').strip()
    queryset = get_user_model().objects.prefetch_related('groups', Prefetch('customer_access',
        queryset=m.CustomerAccess.objects.filter(location__isnull=False).select_related('customer', 'location').order_by('customer__customer_name', 'pk'))).order_by('username')
    if query:
        condition = Q(username__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query)
        if can_view_access:
            condition |= Q(customer_access__customer__customer_name__icontains=query) | Q(customer_access__location__location_name__icontains=query)
        queryset = queryset.filter(condition).distinct()
    if request.GET.get('customer'):
        if not can_view_access:
            raise PermissionDenied
        if not request.GET['customer'].isdecimal():
            raise Http404
        customer = get_object_or_404(m.Customer, pk=request.GET['customer'])
        queryset = queryset.filter(customer_access__customer=customer).distinct()
    return render(request, 'bakery/users.html', {'page': paginate(request, queryset), 'q': query,
        'can_add': request.user.has_perm('auth.add_user') and request.user.has_perm('auth.change_user'),
        'can_manage_access': can_view_access})


@office_required
def user_create(request):
    if not request.user.has_perm('auth.add_user') or not request.user.has_perm('auth.change_user'):
        raise PermissionDenied
    form = forms.WorkspaceUserForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            user.groups.add(form.cleaned_data['role'])
            # Audit only account metadata, never passwords or password hashes.
            m.MasterDataChange.objects.create(model_name='auth.User', record_key=str(user.pk), actor=request.user,
                source='workspace:user-created', after={'username': user.username, 'role': form.cleaned_data['role'].name})
        messages.success(request, f'Login created for {user.username}. Assign customers below if needed.')
        return redirect('workspace-user-edit', pk=user.pk)
    return render(request, 'bakery/record_editor.html', {'form': form, 'kind': 'access', 'title': 'Login', 'editing': False})


@office_required
def user_edit(request, pk):
    can_edit_login = request.user.has_perm('auth.change_user')
    can_view_access = request.user.has_perm('bakery.view_customeraccess')
    can_edit_access = request.user.has_perm('bakery.change_customeraccess')
    can_add_access = request.user.has_perm('bakery.add_customeraccess')
    if not (can_edit_login or can_view_access):
        raise PermissionDenied
    person = get_object_or_404(get_user_model(), pk=pk)
    form = forms.WorkspaceUserEditForm(request.POST or None, instance=person) if can_edit_login else None
    access_submitted = request.method == 'POST' and any(key.startswith('access-') for key in request.POST)
    access_forms = forms.LoginAccessForms(request.POST if access_submitted else None, instance=person, prefix='access',
        queryset=person.customer_access.filter(location__isnull=False).select_related('customer', 'location').order_by('pk')) if can_view_access else None
    if access_forms:
        access_forms.extra = 1 if can_add_access else 0
        if not can_edit_access:
            for access_form in access_forms.initial_forms:
                for field in access_form.visible_fields():
                    field.field.disabled = True
    if request.method == 'POST':
        if not can_edit_login and any(key in request.POST for key in ('username', 'role', 'first_name', 'last_name', 'email', 'is_active')):
            raise PermissionDenied
        login_valid = form.is_valid() if form else True
        access_valid = access_forms.is_valid() if access_submitted and access_forms else not access_submitted
        if form and login_valid and person.pk == request.user.pk and (
                not form.cleaned_data['is_active'] or form.cleaned_data['role'].name != 'ADMINISTRATOR'):
            form.add_error(None, 'Keep your own administrator account active to avoid losing access.')
            login_valid = False
        if login_valid and access_valid:
            try:
                with transaction.atomic():
                    original = get_user_model().objects.select_for_update().get(pk=pk)
                    if form:
                        before = {'username': original.username, 'is_active': original.is_active,
                                  'roles': list(original.groups.values_list('name', flat=True))}
                        person = form.save()
                        role = form.cleaned_data['role']
                        named_roles = person.groups.filter(name__in=['ADMINISTRATOR', 'BAKERY OFFICE', 'PRODUCTION', 'CUSTOMER'])
                        person.groups.remove(*named_roles)
                        person.groups.add(role)
                        m.MasterDataChange.objects.create(model_name='auth.User', record_key=str(person.pk),
                            actor=request.user, source='workspace:user-edited', before=before,
                            after={'username': person.username, 'is_active': person.is_active, 'role': role.name})
                    if access_submitted and access_forms:
                        for assignment in access_forms.save(commit=False):
                            if not (can_edit_access if assignment.pk else can_add_access):
                                raise PermissionDenied
                            before = snapshot(m.CustomerAccess.objects.get(pk=assignment.pk)) if assignment.pk else {}
                            assignment.user = person
                            assignment.full_clean()
                            assignment.save()
                            record_change(assignment, before, 'workspace:login-access', request.user)
                messages.success(request, 'Login and customer access saved.')
                return redirect('workspace-users')
            except ValidationError as exc:
                if access_forms:
                    access_forms._non_form_errors = access_forms.error_class(exc.messages)
                else:
                    form.add_error(None, exc)
    return render(request, 'bakery/user_detail.html', {'form': form, 'person': person, 'access_forms': access_forms,
        'can_edit_access': can_edit_access, 'can_add_access': can_add_access, 'can_edit_login': can_edit_login,
        'assignments': person.customer_access.filter(location__isnull=False).select_related('customer', 'location') if can_view_access else [],
        'can_save': can_edit_login or can_edit_access or can_add_access})


@office_required
def audit_trail(request):
    require_permission(request.user, 'view', m.MasterDataChange)
    return render(request, 'bakery/audit.html', {'page': paginate(request,
        m.MasterDataChange.objects.select_related('actor').order_by('-created_at'))})
