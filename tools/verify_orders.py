"""Desktop/mobile ordering QA using a disposable SQLite database, never real orders."""
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')


def verify():
    from django.conf import settings
    from django.core.management import call_command
    with tempfile.TemporaryDirectory(prefix='bakery-orders-qa-') as directory:
        settings.DATABASES['default']['NAME'] = str(Path(directory) / 'qa.sqlite3')
        import django
        django.setup()
        from django.contrib.auth import get_user_model
        from django.contrib.staticfiles.handlers import StaticFilesHandler
        from django.db import connections, close_old_connections
        from django.test.testcases import LiveServerThread
        from django.utils import timezone
        from playwright.sync_api import sync_playwright, expect
        from bakery import models as m
        from bakery.services.orders import create_draft, submit_order

        call_command('migrate', verbosity=0)
        password = 'Temporary-QA-only-279!'
        user = get_user_model().objects.create_user('qa-customer', password=password)
        office = get_user_model().objects.create_superuser('qa-bakery', password=password)
        customer = m.Customer.objects.create(customer_code='QA-ERIC', customer_name='Eric · QA example', pricing_zone=1)
        location = m.CustomerLocation.objects.create(customer=customer, location_code='MAIN', location_name='Eric’s store')
        m.CustomerAccess.objects.create(user=user, customer=customer, location=location)
        m.CustomerDeliveryRule.objects.create(customer=customer, location=location, delivery_days=list(range(7)))
        products = []
        for code, name, price, tray in [('QA-CAKE', 'Tres Leches Cake 5 inch', 10, 6), ('QA-FLAN', 'Flan', 8, 12), ('QA-ROLL', 'Dinner rolls', '4.25', 12)]:
            product = m.Product.objects.create(internal_product_code=code, product_name=name,
                unit_of_measure='item', pack_size=1, units_per_tray=tray, category='Bread' if code == 'QA-ROLL' else 'Dessert')
            m.ProductZonePrice.objects.create(product=product, zone=1, price=price, effective_date=timezone.localdate() - timedelta(days=1))
            products.append(product)
        future = timezone.localdate() + timedelta(days=3)
        m.ProductZonePrice.objects.filter(product=products[0], zone=1).update(expiration_date=future - timedelta(days=1))
        m.ProductZonePrice.objects.create(product=products[0], zone=1, price=12, effective_date=future)
        server = LiveServerThread('127.0.0.1', StaticFilesHandler)
        server.start()
        server.is_ready.wait()
        if server.error:
            raise server.error
        address = f'http://127.0.0.1:{server.port}'
        output = ROOT / 'artifacts'
        output.mkdir(exist_ok=True)
        def db_work(function):
            def run():
                try:
                    return function()
                finally:
                    connections.close_all()
            with ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(run).result()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                pricing_context = browser.new_context()
                pricing_page = pricing_context.new_page()
                pricing_page.goto(address)
                pricing_page.get_by_label('Username:', exact=True).fill(office.username)
                pricing_page.get_by_label('Password:', exact=True).fill(password)
                pricing_page.locator('button[type=submit]').click()
                pricing_page.goto(address + '/administration/')
                assert pricing_page.locator('.admin-module h2').all_text_contents() == ['Logins & access', 'Change trail']
                pricing_page.screenshot(path=str(output / 'administration-consolidated-desktop.png'), full_page=True)
                customer_edit_url = address + f'/customers/{customer.pk}/edit/'
                pricing_page.goto(customer_edit_url)
                pricing_page.locator('input[name="catalog-mode"][value="CUSTOM"]').check()
                pricing_page.get_by_role('button', name='+ Add product setting', exact=True).click()
                pricing_page.locator('#id_products-0-product').select_option(str(products[0].pk))
                pricing_page.locator('#id_products-0-customer_sku').fill('QA-CUSTOMER-SKU')
                pricing_page.locator('#id_products-0-vendor_id').fill('QA-VENDOR')
                pricing_page.screenshot(path=str(output / 'customer-product-settings-desktop.png'), full_page=True)
                pricing_page.locator('form.customer-workspace button[type=submit], form.customer-workspace .form-actions button').click()
                expect(pricing_page).to_have_url(address + f'/customers/{customer.pk}/')
                assert db_work(lambda: m.Customer.objects.get(pk=customer.pk).catalog_mode) == 'CUSTOM'
                pricing_page.goto(customer_edit_url)
                pricing_page.locator('input[name="catalog-mode"][value="FULL"]').check()
                pricing_page.set_viewport_size({'width': 390, 'height': 844})
                assert pricing_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                pricing_page.screenshot(path=str(output / 'customer-product-settings-mobile.png'), full_page=True)
                pricing_page.locator('form.customer-workspace .form-actions button').click()
                expect(pricing_page).to_have_url(address + f'/customers/{customer.pk}/')
                assert db_work(lambda: m.Customer.objects.get(pk=customer.pk).catalog_mode) == 'FULL'
                assert db_work(lambda: m.CustomerProduct.objects.get(customer=customer).customer_sku) == 'QA-CUSTOMER-SKU'
                pricing_page.goto(address + '/administration/')
                pricing_page.screenshot(path=str(output / 'administration-consolidated-mobile.png'), full_page=True)
                pricing_page.set_viewport_size({'width': 1280, 'height': 900})
                def save_special_price():
                    pricing_page.goto(address + '/administration/overrides/new/')
                    pricing_page.locator('#id_customer').select_option(str(customer.pk))
                    pricing_page.locator('#id_product').select_option(str(products[1].pk))
                    pricing_page.locator('#id_override_price').fill('6.50')
                    pricing_page.locator('#id_effective_date').fill(future.isoformat())
                    pricing_page.locator('#id_active').check()
                    pricing_page.locator('form.workspace-form button[type=submit]').click()
                    expect(pricing_page).to_have_url(address + '/products/special-prices/')
                save_special_price()
                assert not db_work(lambda: m.CustomerProduct.objects.filter(customer=customer, product=products[1]).exists())
                pricing_page.screenshot(path=str(output / 'full-catalog-special-price-saved.png'), full_page=True)
                pricing_page.get_by_role('link', name='Delete', exact=True).click()
                expect(pricing_page.get_by_role('heading', name='Delete special price?')).to_be_visible()
                assert db_work(lambda: m.CustomerPriceOverride.objects.filter(customer=customer).exists())
                pricing_page.screenshot(path=str(output / 'special-price-delete-desktop.png'), full_page=True)
                pricing_page.get_by_role('link', name='Cancel', exact=True).click()
                assert db_work(lambda: m.CustomerPriceOverride.objects.filter(customer=customer).exists())
                pricing_page.get_by_role('link', name='Delete', exact=True).click()
                pricing_page.set_viewport_size({'width': 390, 'height': 844})
                assert pricing_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                pricing_page.screenshot(path=str(output / 'special-price-delete-mobile.png'), full_page=True)
                pricing_page.get_by_role('button', name='Delete special price', exact=True).click()
                expect(pricing_page).to_have_url(address + '/products/special-prices/')
                assert not db_work(lambda: m.CustomerPriceOverride.objects.filter(customer=customer).exists())
                assert db_work(lambda: m.MasterDataChange.objects.filter(source='workspace-delete').count()) == 1
                save_special_price()
                pricing_context.close()
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(address)
                page.get_by_label('Username:', exact=True).fill(user.username)
                page.get_by_label('Password:', exact=True).fill(password)
                page.locator('button[type=submit]').click()
                page.get_by_role('link', name='Start new order').click()
                page.get_by_role('heading', name='Build your order.', exact=True).wait_for()
                dates = page.locator('#id_delivery_date option').evaluate_all('(options) => options.map(option => option.value)')
                assert page.locator('.order-product').count() == 3
                assert page.locator('#review-order').is_disabled()
                page.locator(f'#id_qty_{products[0].pk}').fill('12')
                page.get_by_role('button', name='Increase Tres Leches Cake 5 inch quantity', exact=True).click()
                page.locator(f'#id_qty_{products[1].pk}').fill('8')
                page.get_by_role('button', name='Reduce Flan quantity', exact=True).click()
                assert page.locator('#order-total').inner_text() == '$186.00'
                page.locator('#product-search').fill('flan')
                assert page.locator('.order-product:visible').count() == 1
                assert page.locator('#order-total').inner_text() == '$186.00'
                page.locator('#product-search').fill('')
                page.locator('#selected-only').check()
                assert page.locator('.order-product:visible').count() == 2
                page.locator('#selected-only').uncheck()
                page.locator('#product-category').select_option('Bread')
                assert page.locator('.order-product:visible').count() == 1
                assert page.locator('#order-total').inner_text() == '$186.00'
                page.locator('#product-category').select_option('')
                selected = dates[2]
                page.locator('#id_delivery_date').select_option(selected)
                page.wait_for_function("document.querySelector('#order-total').textContent === '$201.50'")
                assert page.locator(f'[data-product-id="{products[0].pk}"] [data-line-total]').inner_text() == '$156.00'
                assert page.locator(f'[data-product-id="{products[1].pk}"] [data-price]').inner_text() == '$6.50'
                # A failed refresh must block review while retaining the chosen quantities.
                page.route('**/orders/prices/**', lambda route: route.fulfill(status=503, body='temporarily unavailable'))
                selected = dates[3]
                page.locator('#id_delivery_date').select_option(selected)
                page.locator('#retry-prices').wait_for(state='visible')
                assert page.locator('#review-order').is_disabled()
                assert page.locator(f'#id_qty_{products[0].pk}').input_value() == '13'
                page.unroute('**/orders/prices/**')
                page.locator('#retry-prices').click()
                page.wait_for_function("document.querySelector('#order-total').textContent === '$201.50'")
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(output / 'customer-order-desktop.png'), full_page=True)
                mobile = browser.new_context(viewport={'width': 390, 'height': 844}, storage_state=context.storage_state())
                phone = mobile.new_page()
                phone.goto(page.url)
                phone.locator('#id_delivery_date').select_option(selected)
                phone.wait_for_function("!document.querySelector('#order-form').hasAttribute('aria-busy')")
                phone.locator(f'#id_qty_{products[0].pk}').fill('2')
                phone.locator(f'#id_qty_{products[1].pk}').fill('3')
                phone.wait_for_function("document.querySelector('#order-total').textContent === '$43.50'")
                assert phone.locator('#review-order').is_enabled()
                phone.locator(f'#id_qty_{products[0].pk}').fill('3')
                assert phone.locator('#order-total').inner_text() == '$55.50'
                phone.locator(f'#id_qty_{products[0].pk}').fill('2')
                assert phone.locator('#order-total').inner_text() == '$43.50'
                rows = phone.locator('.order-product').all()
                for row in rows:
                    assert row.bounding_box()['height'] <= 60
                    name = row.locator('.order-product-name').bounding_box()
                    qty = row.locator('.quantity-input').bounding_box()
                    assert abs(name['y'] + name['height']/2 - qty['y'] - qty['height']/2) < 2
                expect(phone.locator('.order-products-heading')).to_be_visible()
                details_button = phone.locator('.order-product-name').first
                details_button.click()
                expect(phone.locator('.order-product-details').first).to_be_visible()
                assert details_button.get_attribute('aria-expanded') == 'true'
                details_button.click()
                expect(phone.locator('.order-product-details').first).to_be_hidden()
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
                phone.screenshot(path=str(output / 'customer-order-mobile.png'), full_page=True)
                mobile.close()
                page.get_by_role('button', name='Review order').click()
                page.get_by_role('button', name='Submit order · $201.50').click()
                page.get_by_role('status').filter(has_text='Order submitted').wait_for()
                order = db_work(lambda: m.Order.objects.get(status=m.OrderStatus.SUBMITTED))
                assert str(order.total) == '201.50'
                # Concurrent repeated submissions of this order must remain idempotent.
                order.status = m.OrderStatus.DRAFT
                db_work(order.save)
                db_work(lambda: order.changes.filter(details__action='submitted').delete())
                def submit_again(_):
                    close_old_connections()
                    try:
                        return submit_order(get_user_model().objects.get(pk=user.pk), order.pk).status
                    finally:
                        connections.close_all()
                with ThreadPoolExecutor(max_workers=3) as executor:
                    statuses = list(executor.map(submit_again, range(3)))
                assert statuses == [m.OrderStatus.SUBMITTED] * 3
                assert db_work(lambda: order.changes.filter(details__action='submitted').count()) == 1
                bakery_context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                bakery = bakery_context.new_page()
                bakery.clock.install()
                bakery.goto(address)
                bakery.get_by_label('Username:', exact=True).fill(office.username)
                bakery.get_by_label('Password:', exact=True).fill(password)
                bakery.locator('button[type=submit]').click()
                expect(bakery.locator('.order-notification-dot')).to_be_visible()
                bakery.goto(address + '/orders/')
                bakery.get_by_role('heading', name='Pending orders').wait_for()
                expect(bakery.locator('.order-notification-dot')).to_be_hidden()
                assert bakery.get_by_role('link', name=order.order_number).count() == 1
                bakery.screenshot(path=str(output / 'pending-orders-desktop.png'), full_page=True)
                production_date = db_work(lambda: order.items.first().required_production_date.isoformat())
                bakery.goto(address + '/production/?date=' + production_date)
                bakery.get_by_role('heading', name='What to bake together').wait_for()
                assert '20 units to bake' in bakery.locator('main').inner_text()
                cake_row = bakery.locator('tbody tr').filter(has_text='Tres Leches')
                assert cake_row.locator('td').nth(2).inner_text() == '13'
                assert cake_row.locator('td').nth(3).inner_text().startswith('3')
                bakery.screenshot(path=str(output / 'bake-totals-desktop.png'), full_page=True)
                bakery_phone = browser.new_context(viewport={'width': 390, 'height': 844}, storage_state=bakery_context.storage_state())
                phone = bakery_phone.new_page()
                phone.clock.install()
                phone.goto(bakery.url)
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
                phone.screenshot(path=str(output / 'bake-totals-mobile.png'), full_page=True)
                # A submission received while the office is on another page
                # appears on the next background check, without a page reload.
                def send_new_order():
                    draft = create_draft(user, location.pk, order.requested_delivery_date, {products[0].pk: 1})
                    submit_order(user, draft.pk)
                db_work(send_new_order)
                bakery.clock.fast_forward(30000)
                expect(bakery.locator('.order-notification-dot')).to_be_visible()
                assert bakery.locator('.order-notification-dot').evaluate('(dot) => getComputedStyle(dot).backgroundColor') == 'rgb(239, 68, 68)'
                bakery.locator('.sidebar').screenshot(path=str(output / 'new-order-notification-desktop.png'))
                phone.reload()
                expect(phone.locator('.order-notification-dot')).to_be_visible()
                phone.locator('.sidebar').screenshot(path=str(output / 'new-order-notification-mobile.png'))
                bakery.locator('nav a').filter(has_text='Orders').click()
                expect(bakery.locator('.order-notification-dot')).to_be_hidden()
                phone.clock.fast_forward(30000)
                expect(phone.locator('.order-notification-dot')).to_be_hidden()
                def create_concurrent_order(_):
                    close_old_connections()
                    try:
                        draft = create_draft(get_user_model().objects.get(pk=user.pk), location.pk,
                            order.requested_delivery_date, {products[0].pk: 1})
                        return draft.pk, draft.order_number
                    finally:
                        connections.close_all()
                with ThreadPoolExecutor(max_workers=3) as executor:
                    numbered = sorted(executor.map(create_concurrent_order, range(3)))
                assert len({number for _, number in numbered}) == 3
                assert all(number == f'B-{pk:06d}' for pk, number in numbered)
                assert [pk for pk, _ in numbered] == list(range(numbered[0][0], numbered[0][0] + 3))
                assert not errors, errors
                browser.close()
            print('Order browser QA passed: full catalog, customer prices, live totals, date refresh/retry, filters, submission, desktop/mobile, bake totals, concurrent idempotency, live new-order notification, sequential numbers under concurrent creation. No real business records changed.')
        finally:
            server.terminate()
            server.join()
            connections.close_all()


if __name__ == '__main__':
    verify()
