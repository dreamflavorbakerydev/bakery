from datetime import time

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group
from django.utils import timezone
from bakery import models as m
from bakery.services.imports import SCHEMAS
from bakery.services.audit import record_change, snapshot
from bakery.services.catalog import product_is_available


class ImportForm(forms.Form):
    kind = forms.ChoiceField(label='Data type', choices=[('nelson', 'Nelson workbook · products + all zone prices')] + [(key, key.replace('_', ' ').title()) for key in SCHEMAS])
    effective_date = forms.DateField(label='Nelson price effective date', required=False, initial=timezone.localdate,
        widget=forms.DateInput(attrs={'type': 'date'}))
    file = forms.FileField(label='CSV or Excel file')
    dry_run = forms.BooleanField(label='Validate only (recommended for the first import)', required=False, initial=True)

    def clean_file(self):
        file = self.cleaned_data['file']
        if file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('File must be 5 MB or smaller.')
        if not file.name.lower().endswith(('.csv', '.xlsx')):
            raise forms.ValidationError('Choose a .csv or .xlsx file.')
        return file

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('kind') == 'nelson' and not cleaned.get('effective_date'):
            self.add_error('effective_date', 'Choose the date these imported prices take effect.')
        return cleaned


class ProductForm(forms.ModelForm):
    class Meta:
        model = m.Product
        fields = ['product_name', 'sku', 'internal_product_code', 'upc', 'category', 'size',
                  'pack_size', 'unit_of_measure', 'units_per_tray', 'production_lead_days', 'sort_order', 'description', 'active']
        labels = {'internal_product_code': 'Master product code', 'pack_size': 'Units per ordering pack',
                  'unit_of_measure': 'Ordering unit', 'size': 'Size as supplied'}
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class CustomerForm(forms.ModelForm):
    class Meta:
        model = m.Customer
        fields = ['customer_name', 'customer_code', 'address', 'city', 'state', 'zip', 'phone', 'pricing_zone', 'active', 'payment_terms', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3}), 'phone': forms.TextInput(attrs={'type': 'tel'})}
        labels = {'customer_code': 'Customer code (optional)', 'pricing_zone': 'Required pricing zone'}
        help_texts = {'customer_code': 'Leave blank if you do not use a customer code. A customer ID is assigned automatically.'}


class LocationForm(forms.ModelForm):
    delivery_days = forms.MultipleChoiceField(choices=list(enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])),
        widget=forms.CheckboxSelectMultiple, required=False, label='Delivery days',
        help_text='Select delivery days to configure this customer. Leave unselected to configure a new calendar later.')
    production_lead_days = forms.IntegerField(min_value=1, required=False, label='Order notice (calendar days)')
    order_cutoff_time = forms.TimeField(required=False, label='Order cutoff time', widget=forms.TimeInput(attrs={'type': 'time'}))
    timezone = forms.CharField(max_length=64, required=False, validators=[m.validate_timezone], label='Delivery timezone')
    late_order_policy = forms.ChoiceField(choices=m.LatePolicy.choices, required=False, label='Late-order policy')

    class Meta:
        model = m.CustomerLocation
        fields = ['customer', 'location_name', 'location_code', 'store_number', 'address', 'city', 'state', 'zip', 'phone', 'active',
                  'delivery_days', 'production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy']
        labels = {'location_name': 'Store name', 'location_code': 'Store code', 'phone': 'Phone number'}

    def __init__(self, *args, edit_delivery=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.edit_delivery = edit_delivery
        self.delivery_rule = getattr(self.instance, 'delivery_rule', None) if self.instance.pk else None
        defaults = {'delivery_days': [], 'production_lead_days': 1, 'order_cutoff_time': time(14),
                    'timezone': 'America/New_York', 'late_order_policy': m.LatePolicy.APPROVAL}
        for field, default in defaults.items():
            if not edit_delivery:
                self.fields.pop(field)
            else:
                self.initial.setdefault(field, getattr(self.delivery_rule, field) if self.delivery_rule else default)
        if edit_delivery and self.delivery_rule:
            self.fields['delivery_days'].required = True
            self.fields['delivery_days'].help_text = 'This calendar applies only to this customer. Deactivate the customer to stop deliveries.'

    def clean_delivery_days(self):
        return [int(day) for day in self.cleaned_data['delivery_days']]

    def clean(self):
        cleaned = super().clean()
        if not self.edit_delivery and self.delivery_rule and cleaned.get('customer') and cleaned['customer'].pk != self.instance.customer_id:
            self.add_error('customer', 'Updating the customer for a configured store requires permission to update its delivery rules.')
        if self.edit_delivery and cleaned.get('delivery_days'):
            for field in ('production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy'):
                if cleaned.get(field) in (None, ''):
                    self.add_error(field, 'Complete this setting for the customer delivery calendar.')
        return cleaned

    def save_delivery_rule(self, actor):
        if not self.edit_delivery or not self.cleaned_data.get('delivery_days'):
            return
        rule = m.CustomerDeliveryRule.objects.select_for_update().filter(location=self.instance).first()
        before = snapshot(rule) if rule else {}
        rule = rule or m.CustomerDeliveryRule(location=self.instance)
        rule.customer = self.instance.customer
        for field in ('delivery_days', 'production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy'):
            setattr(rule, field, self.cleaned_data[field])
        rule.full_clean()
        if before != snapshot(rule):
            from django.core.exceptions import PermissionDenied
            if not actor.has_perm('bakery.change_customerdeliveryrule' if rule.pk else 'bakery.add_customerdeliveryrule'):
                raise PermissionDenied
            rule.save()
            record_change(rule, before, 'workspace:store-delivery', actor)


class CustomerDeliveryForm(LocationForm):
    class Meta:
        model = m.CustomerLocation
        fields = ['delivery_days', 'production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy']


class CustomerAccessChoice(forms.ModelChoiceField):
    def label_from_instance(self, location):
        label = location.customer.customer_name
        if location.customer_locations > 1:
            label += ' - ' + (location.address or location.location_name)
        return label


class CustomerProductForm(forms.ModelForm):
    class Meta:
        model = m.CustomerProduct
        fields = ['customer', 'product', 'vendor_id', 'customer_sku', 'customer_product_name', 'sort_order', 'active']


class CustomerCatalogForm(forms.Form):
    mode = forms.ChoiceField(label='Products this customer can order', required=False,
        choices=[('FULL', 'Full catalog — all active products'), ('CUSTOM', 'Custom product list — only available products below')],
        widget=forms.RadioSelect)


class CustomerCatalogProductForm(forms.ModelForm):
    class Meta:
        model = m.CustomerProduct
        fields = ['product', 'customer_sku', 'vendor_id', 'customer_product_name', 'sort_order', 'active']
        labels = {'active': 'Available in custom list', 'customer_product_name': 'Customer product name (optional)'}


class CustomerCatalogFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            link = form.cleaned_data.get('id')
            if link and link.customer_id != self.instance.pk:
                raise forms.ValidationError('This product setting belongs to another customer.')
            product = form.cleaned_data.get('product')
            if product:
                if product.pk in seen:
                    raise forms.ValidationError('Each product can appear only once. Update its existing setting.')
                seen.add(product.pk)


CustomerCatalogProducts = forms.inlineformset_factory(m.Customer, m.CustomerProduct,
    form=CustomerCatalogProductForm, formset=CustomerCatalogFormSet,
    extra=0, can_delete=False, max_num=2000, validate_max=True)


class OverrideForm(forms.ModelForm):
    class Meta:
        model = m.CustomerPriceOverride
        fields = ['customer', 'product', 'override_price', 'effective_date', 'expiration_date', 'reason', 'notes', 'active']
        widgets = {'effective_date': forms.DateInput(attrs={'type': 'date'}),
                   'expiration_date': forms.DateInput(attrs={'type': 'date'}), 'notes': forms.Textarea(attrs={'rows': 3})}

    def clean(self):
        cleaned = super().clean()
        customer, product = cleaned.get('customer'), cleaned.get('product')
        if customer and product and not product_is_available(customer, product):
            self.add_error('product', 'Choose an active product available in this customer\'s catalog. If the customer has a custom product list, enable the product there first.')
        return cleaned


class DeliveryRuleForm(forms.ModelForm):
    delivery_days = forms.MultipleChoiceField(choices=list(enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])),
        widget=forms.CheckboxSelectMultiple, label='Delivery days')

    class Meta:
        model = m.CustomerDeliveryRule
        fields = ['location', 'delivery_days', 'production_lead_days', 'order_cutoff_time', 'timezone', 'late_order_policy']
        widgets = {'order_cutoff_time': forms.TimeInput(attrs={'type': 'time'})}

    def clean_delivery_days(self):
        return [int(day) for day in self.cleaned_data['delivery_days']]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('location'):
            self.instance.customer = cleaned['location'].customer
        return cleaned


class LoginAccessForm(forms.ModelForm):
    location = CustomerAccessChoice(queryset=m.CustomerLocation.objects.none(), label='Customer')
    class Meta:
        model = m.CustomerAccess
        fields = ['location', 'active']
        labels = {'location': 'Customer', 'active': 'Access active'}
        help_texts = {'location': 'Select a customer this person can access. Add another assignment for another customer.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['location'].required = True
        self.fields['location'].empty_label = 'Select a customer'
        from django.db.models import Count, OuterRef, Subquery
        totals = m.Customer.objects.filter(pk=OuterRef('customer_id')).annotate(total=Count('locations')).values('total')
        self.fields['location'].queryset = m.CustomerLocation.objects.select_related('customer').annotate(
            customer_locations=Subquery(totals[:1])).order_by('customer__customer_name', 'location_name', 'pk')

    def clean(self):
        cleaned = super().clean()
        location = cleaned.get('location')
        if location:
            self.instance.customer = location.customer
        return cleaned


class AccessForm(LoginAccessForm):
    class Meta(LoginAccessForm.Meta):
        fields = ['user', 'location', 'active']


class LoginAccessFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            assignment = form.cleaned_data.get('id')
            if assignment and assignment.user_id != self.instance.pk:
                raise forms.ValidationError('This assignment belongs to another login.')
            location = form.cleaned_data.get('location')
            if not location:
                continue
            key = location.pk
            if key in seen:
                raise forms.ValidationError('Each customer delivery address can appear only once. Edit the existing assignment to reactivate it.')
            seen.add(key)


LoginAccessForms = forms.inlineformset_factory(
    get_user_model(), m.CustomerAccess, form=LoginAccessForm, formset=LoginAccessFormSet,
    extra=1, can_delete=False, max_num=200, validate_max=True)


class ZoneGridForm(forms.Form):
    effective_date = forms.DateField(initial=timezone.localdate, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for zone in range(1, 4):
            for name, label in [('price', 'Ordering'), ('retail_price', 'Retail'), ('return_price', 'Return')]:
                self.fields[f'zone_{zone}_{name}'] = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0,
                    required=name == 'price', label=f'Zone {zone} · {label}',
                    widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}))


class WorkspaceUserForm(UserCreationForm):
    role = forms.ModelChoiceField(queryset=Group.objects.filter(name__in=['ADMINISTRATOR', 'BAKERY OFFICE', 'PRODUCTION', 'CUSTOMER']), empty_label='Choose a role')

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'password1', 'password2']


class WorkspaceUserEditForm(forms.ModelForm):
    role = forms.ModelChoiceField(queryset=Group.objects.filter(name__in=['ADMINISTRATOR', 'BAKERY OFFICE', 'PRODUCTION', 'CUSTOMER']), empty_label='Choose a role')

    class Meta:
        model = get_user_model()
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.is_superuser:
            self.fields['role'].initial = Group.objects.filter(name='ADMINISTRATOR').first()
            self.fields['role'].disabled = True
        else:
            self.fields['role'].initial = self.instance.groups.filter(name__in=['ADMINISTRATOR', 'BAKERY OFFICE', 'PRODUCTION', 'CUSTOMER']).first()
