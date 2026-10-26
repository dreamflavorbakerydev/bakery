"""Optional local browser QA. Creates and removes one temporary QA login.

Run against manage.py runserver at 127.0.0.1:8765. Never points at remote sites.
Business records are not created. Screenshots are written to ignored artifacts/.
"""
import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from playwright.sync_api import sync_playwright
from bakery.models import Customer


def verify():
    output = ROOT / 'artifacts'
    output.mkdir(exist_ok=True)
    sample_customer = Customer.objects.exclude(phone='').exclude(address='').order_by('pk').first()
    if sample_customer is None:
        raise RuntimeError('Visual QA requires locally imported customers with contact details.')
    first_id = Customer.objects.order_by('pk').values_list('pk', flat=True).first()
    last_id = Customer.objects.order_by('-pk').values_list('pk', flat=True).first()
    username = 'visual-qa-' + secrets.token_hex(5)
    password = secrets.token_urlsafe(24)
    user = get_user_model().objects.create_superuser(username=username, password=password,
        first_name='Bakery', last_name='Administrator')
    user_id = str(user.pk)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            desktop = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = desktop.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            response = page.goto('http://127.0.0.1:8765/')
            assert response.status == 200
            assert '/accounts/login/' in page.url
            page.get_by_label('Username:', exact=True).fill(username)
            page.get_by_label('Password:', exact=True).fill(password)
            page.get_by_role('button', name='Sign in →', exact=True).click()
            page.get_by_role('heading', name='Good things start here.', exact=True).wait_for()
            assert not errors, errors
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / 'dashboard-desktop.png'), full_page=True)
            for name, heading in [('Customers', 'Every account, connected.'), ('Products & Pricing', 'Everything you bake.'),
                                  ('Price records', 'Zone price records.'), ('Customer special prices', 'Special prices.'), ('Import data', 'A familiar starting point.')]:
                page.get_by_role('link', name=name, exact=True).click()
                page.get_by_role('heading', name=heading, exact=True).wait_for()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                if name in ('Products & Pricing', 'Price records', 'Customer special prices'):
                    navigation = page.get_by_role('navigation', name='Main navigation', exact=True)
                    assert navigation.get_by_role('link', name='Products & Pricing', exact=True).get_attribute('class') == 'active'
                    assert navigation.get_by_role('link', name='Pricing', exact=True).count() == 0
                    page.screenshot(path=str(output / (name.lower().replace(' & ', '-').replace(' ', '-') + '-desktop.png')), full_page=True)
            page.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Customers', exact=True).click()
            assert page.get_by_role('link', name='ID: sort ascending', exact=True).is_visible()
            page.get_by_role('link', name='Delivery schedule: sort ascending', exact=True).click()
            page.get_by_role('link', name='ID: sort ascending', exact=True).click()
            assert page.locator('tbody tr').first.locator('td').first.inner_text() == f'#{first_id}'
            page.get_by_role('link', name='ID: sort descending', exact=True).click()
            assert page.locator('tbody tr').first.locator('td').first.inner_text() == f'#{last_id}'
            page.screenshot(path=str(output / 'customers-contacts-desktop.png'), full_page=True)
            page.get_by_role('link', name='Products & Pricing', exact=True).click()
            page.get_by_role('link', name='Zone 1: sort ascending', exact=True).click()
            prices = page.locator('tbody tr td:nth-child(5)').all_inner_texts()
            values = [float(value.replace('$', '')) for value in prices if value != 'Missing']
            assert values == sorted(values)
            page.get_by_role('link', name='Zone 1: sort descending', exact=True).click()
            prices = page.locator('tbody tr td:nth-child(5)').all_inner_texts()
            values = [float(value.replace('$', '')) for value in prices if value != 'Missing']
            assert values == sorted(values, reverse=True)
            page.screenshot(path=str(output / 'products-sorted-desktop.png'), full_page=True)
            page.get_by_role('link', name='Next', exact=False).click()
            assert 'sort=zone1' in page.url and 'direction=desc' in page.url and 'page=2' in page.url
            page.get_by_role('link', name='Price records', exact=True).click()
            page.get_by_role('link', name='Ordering: sort ascending', exact=True).click()
            prices = page.locator('tbody tr td:nth-child(3)').all_inner_texts()
            values = [float(value.replace('$', '')) for value in prices]
            assert values == sorted(values)
            page.get_by_role('link', name='Customers', exact=True).click()
            page.goto(f'http://127.0.0.1:8765/customers/{sample_customer.pk}/')
            page.get_by_role('heading', name='Contact details', exact=True).wait_for()
            assert page.get_by_text(sample_customer.address, exact=False).count() > 0
            page.screenshot(path=str(output / 'customer-contact-desktop.png'), full_page=True)
            page.get_by_role('link', name='Edit customer', exact=False).first.click()
            assert not page.get_by_label('Customer code (optional)', exact=False).evaluate('(field) => field.required')
            assert page.get_by_label('Phone number', exact=False).input_value() == sample_customer.phone
            page.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Import data', exact=True).click()
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory) / 'header-only.csv'
                file.write_text('internal_product_code,product_name,pack_size,unit_of_measure\n', encoding='utf-8')
                page.get_by_label('Data type').select_option('products')
                page.get_by_label('CSV or Excel file').set_input_files(str(file))
                page.get_by_role('button', name='Process file →').click()
                page.get_by_role('status').filter(has_text='Validated without saving: 0 new').wait_for()
            page.screenshot(path=str(output / 'imports-desktop.png'), full_page=True)
            page.get_by_role('link', name='Administration', exact=True).click()
            page.get_by_role('heading', name='A home for the details.', exact=True).wait_for()
            assert page.get_by_role('heading', name='Customer access', exact=True).count() == 0
            assert page.get_by_role('heading', name='Delivery rules', exact=True).count() == 0
            assert page.get_by_role('heading', name='Stores & delivery', exact=True).count() == 0
            page.screenshot(path=str(output / 'administration-desktop.png'), full_page=True)
            page.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Customers', exact=True).click()
            page.get_by_role('heading', name='Every account, connected.', exact=True).wait_for()
            page.locator('tbody tr').first.get_by_role('link', name='Edit customer', exact=False).click()
            page.get_by_role('heading', name='Delivery rules', exact=True).wait_for()
            assert page.get_by_label('Order notice (calendar days)', exact=False).input_value() == '1'
            assert page.get_by_label('Order cutoff time', exact=False).input_value() == '14:00:00'
            assert page.get_by_label('Delivery timezone', exact=False).input_value() == 'America/New_York'
            assert page.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Customers', exact=True).get_attribute('class') == 'active'
            page.screenshot(path=str(output / 'customer-editor-desktop.png'), full_page=True)
            page.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Administration', exact=True).click()
            page.locator('.admin-module').filter(has=page.get_by_role('heading', name='Logins & access', exact=True)).click()
            page.get_by_role('heading', name='Logins & access.', exact=True).wait_for()
            page.screenshot(path=str(output / 'logins-access-desktop.png'), full_page=True)
            page.locator('tbody tr').filter(has_text=username).get_by_role('link', name='Manage login & access', exact=True).click()
            page.get_by_role('heading', name='Login details & role', exact=True).wait_for()
            page.get_by_role('heading', name='Customer access', exact=True).wait_for()
            assert page.locator('select[name$="-customer"]').count() == 0
            assert page.locator('#id_access-0-location option').first.inner_text() == 'Select a customer'
            assert page.get_by_label('Username', exact=False).input_value() == username
            page.screenshot(path=str(output / 'login-access-detail-desktop.png'), full_page=True)
            total = int(page.locator('#id_access-TOTAL_FORMS').input_value())
            page.get_by_role('button', name='+ Add another customer', exact=True).click()
            assert int(page.locator('#id_access-TOTAL_FORMS').input_value()) == total + 1
            assert page.locator(f'#id_access-{total}-location').is_visible()
            page.get_by_role('link', name='Cancel', exact=True).click()
            page.get_by_role('link', name='Products & Pricing', exact=True).click()
            page.get_by_label('Search products', exact=True).fill('Tres Leches Cake')
            page.get_by_role('button', name='Search', exact=True).click()
            page.get_by_role('link', name='Tres Leches Cake 5"', exact=True).click()
            page.get_by_role('heading', name='Three zones. Every price.', exact=True).wait_for()
            assert page.get_by_label('Zone 1 · Ordering', exact=True).input_value() == '10.00'
            assert page.get_by_label('Zone 2 · Retail', exact=True).input_value() == '13.99'
            page.screenshot(path=str(output / 'product-detail-desktop.png'), full_page=True)
            page.get_by_role('link', name='My account', exact=True).click()
            page.get_by_role('link', name='Change password', exact=True).click()
            page.get_by_role('heading', name='Choose a new password.', exact=True).wait_for()
            # Inspect the password screen without changing credentials in browser QA.
            assert page.get_by_label('Old password:', exact=True).is_visible()
            mobile = browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True,
                                         device_scale_factor=1, storage_state=desktop.storage_state())
            phone = mobile.new_page()
            phone.goto('http://127.0.0.1:8765/')
            phone.get_by_role('heading', name='Good things start here.', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'dashboard-mobile.png'), full_page=True)
            for name, heading in [('Products & Pricing', 'Everything you bake.'),
                                  ('Price records', 'Zone price records.'), ('Customer special prices', 'Special prices.')]:
                phone.get_by_role('link', name=name, exact=True).click()
                phone.get_by_role('heading', name=heading, exact=True).wait_for()
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
                phone.screenshot(path=str(output / (name.lower().replace(' & ', '-').replace(' ', '-') + '-mobile.png')), full_page=True)
            phone.get_by_role('link', name='Customers', exact=True).click()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'customers-contacts-mobile.png'), full_page=True)
            phone.get_by_role('link', name='49 LAGAR RESTAURANT', exact=True).click()
            phone.get_by_role('heading', name='Contact details', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'customer-contact-mobile.png'), full_page=True)
            phone.get_by_role('link', name='Administration', exact=True).click()
            phone.get_by_role('heading', name='A home for the details.', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'administration-mobile.png'), full_page=True)
            phone.locator('.admin-module').filter(has=phone.get_by_role('heading', name='Customers', exact=True)).click()
            phone.locator('tbody tr').first.get_by_role('link', name='Edit customer', exact=False).click()
            phone.get_by_role('heading', name='Delivery rules', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'customer-editor-mobile.png'), full_page=True)
            phone.get_by_role('navigation', name='Main navigation', exact=True).get_by_role('link', name='Administration', exact=True).click()
            phone.locator('.admin-module').filter(has=phone.get_by_role('heading', name='Logins & access', exact=True)).click()
            phone.get_by_role('heading', name='Logins & access.', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'logins-access-mobile.png'), full_page=True)
            phone.locator('tbody tr').filter(has_text=username).get_by_role('link', name='Manage login & access', exact=True).click()
            phone.get_by_role('heading', name='Customer access', exact=True).wait_for()
            assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
            phone.screenshot(path=str(output / 'login-access-detail-mobile.png'), full_page=True)
            phone.get_by_role('button', name='Sign out', exact=True).click()
            phone.get_by_role('heading', name='Welcome back.', exact=True).wait_for()
            phone.screenshot(path=str(output / 'login-mobile.png'), full_page=True)
            assert not errors, errors
            browser.close()
        print('Browser QA passed: sign-in, navigation, validation upload, password screen, mobile layout, sign-out.')
    finally:
        for session in Session.objects.iterator():
            if session.get_decoded().get('_auth_user_id') == user_id:
                session.delete()
        user.delete()


if __name__ == '__main__':
    verify()
