from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from bakery import models as m
from bakery.services.orders import create_draft, submit_order, change_status
from bakery.tests.test_foundation import FoundationFixture


class OrderingTests(FoundationFixture):
    def setUp(self):
        self.clock = patch('django.utils.timezone.now', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.delivery = date(2026, 10, 6)
        self.office = get_user_model().objects.create_user('order-office')
        self.office.user_permissions.add(Permission.objects.get(codename='office_access'))
        self.production = get_user_model().objects.create_user('order-production')
        self.production.user_permissions.add(Permission.objects.get(codename='production_access'))
        self.product.units_per_tray = 12
        self.product.save()
        self.client.force_login(self.user)

    def draft(self, qty=3):
        return create_draft(self.user, self.location.pk, self.delivery, {self.product.pk: qty})

    def test_order_numbers_are_short_sequential_and_stable(self):
        first = self.draft()
        second = self.draft()
        self.assertEqual(first.order_number, f'B-{first.pk:06d}')
        self.assertEqual(second.order_number, f'B-{second.pk:06d}')
        self.assertEqual(second.pk, first.pk + 1)
        number = first.order_number
        submit_order(self.user, first.pk)
        change_status(self.office, first.pk, m.OrderStatus.CANCELLED)
        first.refresh_from_db()
        self.assertEqual(first.order_number, number)
        third = self.draft()
        self.assertEqual(third.order_number, f'B-{second.pk + 1:06d}')

    def test_failed_order_creation_does_not_leave_a_number_or_partial_order(self):
        with patch('bakery.models.OrderItem.objects.bulk_create', side_effect=ValidationError('Test rollback')):
            with self.assertRaises(ValidationError):
                self.draft()
        self.assertFalse(m.Order.objects.exists())
        self.assertFalse(m.OrderChangeLog.objects.exists())
        order = self.draft()
        self.assertEqual(order.order_number, f'B-{order.pk:06d}')

    def test_new_order_notification_is_per_office_user_and_clears_on_orders(self):
        office = Client()
        office.force_login(self.office)
        other = get_user_model().objects.create_superuser('second-office')
        other_client = Client()
        other_client.force_login(other)
        endpoint = reverse('order-notifications')
        first = self.draft()
        older_draft = self.draft()
        self.assertFalse(office.get(endpoint).json()['has_new_orders'])
        submit_order(self.user, first.pk)
        self.assertTrue(office.get(endpoint).json()['has_new_orders'])
        self.assertFalse(m.OrderInboxState.objects.exists())
        response = office.get(reverse('account'))
        self.assertTrue(response.context['has_new_orders'])
        self.assertContains(response, 'title="New orders received"></i>')
        self.assertEqual(office.get(endpoint)['Cache-Control'], 'private, no-store')
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(seconds=1)):
            response = office.get(reverse('orders'))
        self.assertFalse(response.context['has_new_orders'])
        self.assertFalse(office.get(endpoint).json()['has_new_orders'])
        self.assertTrue(other_client.get(endpoint).json()['has_new_orders'])
        # A previously created draft becomes new when submitted later.
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(seconds=2)):
            submit_order(self.user, older_draft.pk)
        self.assertTrue(office.get(endpoint).json()['has_new_orders'])

    def test_status_changes_and_duplicate_submissions_do_not_trigger_new_order_dot(self):
        office = Client()
        office.force_login(self.office)
        order = self.draft()
        submit_order(self.user, order.pk)
        office.get(reverse('orders'))
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(seconds=1)):
            change_status(self.office, order.pk, m.OrderStatus.CONFIRMED)
            submit_order(self.user, order.pk)
        self.assertFalse(office.get(reverse('order-notifications')).json()['has_new_orders'])

    def test_filtered_lists_do_not_clear_unseen_orders(self):
        office = Client()
        office.force_login(self.office)
        submit_order(self.user, self.draft().pk)
        for query in ({'date': '2026-10-08'}, {'date': 'bad'}, {'scope': 'approval'}):
            response = office.get(reverse('orders'), query)
            self.assertTrue(response.context['has_new_orders'])
        self.assertFalse(m.OrderInboxState.objects.exists())

    def test_notifications_are_office_only_and_read_time_never_moves_backwards(self):
        from bakery.services.notifications import mark_orders_seen
        endpoint = reverse('order-notifications')
        self.assertEqual(self.client.get(endpoint).status_code, 403)
        self.assertNotContains(self.client.get(reverse('account')), 'data-new-orders-url')
        production = Client()
        production.force_login(self.production)
        self.assertEqual(production.get(endpoint).status_code, 403)
        self.assertEqual(Client().get(endpoint).status_code, 302)
        mark_orders_seen(self.user, self.now)
        self.assertFalse(m.OrderInboxState.objects.exists())
        mark_orders_seen(self.office, self.now + timedelta(seconds=1))
        mark_orders_seen(self.office, self.now)
        self.assertEqual(m.OrderInboxState.objects.get(user=self.office).last_seen_at,
            self.now + timedelta(seconds=1))

    def test_full_customer_review_and_submit(self):
        response = self.client.post(reverse('order-new'), {'location': self.location.pk,
            'delivery_date': self.delivery.isoformat(), f'qty_{self.product.pk}': 3,
            'unit_price': '0.01', 'total': '0.01', 'customer_po_number': 'PO123'})
        order = m.Order.objects.get()
        self.assertRedirects(response, reverse('order-detail', args=[order.pk]))
        self.assertEqual(order.status, m.OrderStatus.DRAFT)
        self.assertEqual(order.total, Decimal('63'))
        self.assertContains(self.client.get(response.url), 'Submit order')
        self.client.post(reverse('order-submit', args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, m.OrderStatus.SUBMITTED)
        self.assertIsNotNone(order.submitted_at)
        self.assertEqual(order.items.get().required_production_date, date(2026, 10, 5))
        self.assertEqual(order.items.get().units_per_tray, 12)

    def test_duplicate_submit_creates_no_duplicate_order_or_audit(self):
        order = self.draft()
        for _ in range(3):
            submit_order(self.user, order.pk)
        self.assertEqual(m.Order.objects.count(), 1)
        self.assertEqual(order.changes.filter(details__action='submitted').count(), 1)

    def test_override_price_is_saved_and_history_is_stable(self):
        m.CustomerPriceOverride.objects.create(customer=self.customer, product=self.product,
            override_price=19, effective_date=date(2026, 1, 1))
        order = self.draft()
        submit_order(self.user, order.pk)
        m.CustomerPriceOverride.objects.update(override_price=99)
        self.product.product_name = 'New label'
        self.product.pack_size = 8
        self.product.save()
        line = order.items.get()
        self.assertEqual((line.unit_price, line.product_name, line.pack_size), (Decimal('19'), 'Test bread', 6))

    def test_price_for_delivery_date_and_review_price_change_block(self):
        self.price.expiration_date = date(2026, 10, 5)
        self.price.save()
        m.ProductZonePrice.objects.create(product=self.product, zone=2, price=25, effective_date=self.delivery)
        order = self.draft()
        self.assertEqual(order.total, 75)
        m.ProductZonePrice.objects.filter(effective_date=self.delivery).update(price=26)
        with self.assertRaisesRegex(ValidationError, 'changed since your review'):
            submit_order(self.user, order.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, m.OrderStatus.DRAFT)

    def test_default_catalog_shows_all_active_products_and_honors_customer_prices(self):
        m.CustomerProduct.objects.filter(customer=self.customer).delete()
        extra = m.Product.objects.bulk_create([
            m.Product(internal_product_code=f'FULL-{number:02}', product_name=f'Full catalog {number:02}')
            for number in range(35)])
        m.Product.objects.create(internal_product_code='INACTIVE', product_name='Inactive product', active=False)
        m.CustomerPriceOverride.objects.create(customer=self.customer, product=self.product, override_price='19.25',
                                              effective_date=date(2026, 1, 1))
        response = self.client.get(reverse('order-new'), {'location': self.location.pk})
        self.assertEqual(len(response.context['rows']), 37)
        self.assertContains(response, extra[-1].product_name)
        self.assertContains(response, 'product-sku-label')
        self.assertContains(response, self.product.internal_product_code)
        self.assertNotContains(response, 'Inactive product')
        self.assertContains(response, 'data-unit-cents="1925"')
        self.assertFalse(m.CustomerProduct.objects.filter(customer=self.customer).exists())
        self.assertEqual(self.draft(2).total, Decimal('38.50'))

    def test_price_refresh_is_scoped_and_uses_selected_delivery_date(self):
        self.price.expiration_date = date(2026, 10, 5)
        self.price.save()
        m.ProductZonePrice.objects.create(product=self.product, zone=2, price=25, effective_date=self.delivery)
        m.CustomerPriceOverride.objects.create(customer=self.customer, product=self.product, override_price='23.75',
                                              effective_date=self.delivery)
        response = self.client.get(reverse('order-prices'), {'location': self.location.pk, 'date': self.delivery.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['prices'], {str(self.product.pk): '2375'})
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(reverse('order-prices'), {'location': self.other_location.pk,
            'date': self.delivery.isoformat()}).status_code, 404)
        self.assertEqual(self.client.get(reverse('order-prices'), {'location': self.location.pk, 'date': '2026-10-07'}).status_code, 400)
        self.assertFalse(m.Order.objects.exists())

    def test_inactive_custom_list_does_not_fall_back_to_full_catalog(self):
        self.link.active = False
        self.link.save()
        response = self.client.get(reverse('order-new'), {'location': self.location.pk})
        self.assertEqual(response.context['rows'], [])
        self.assertNotContains(response, 'Private pastry')

    def test_product_list_can_be_browsed_before_calendar_is_configured(self):
        self.rule.delete()
        response = self.client.get(reverse('order-new'), {'location': self.location.pk})
        self.assertContains(response, 'Test bread')
        self.assertContains(response, 'data-can-order="false"')
        self.assertContains(response, 'No delivery dates available.')

    def test_no_products_zero_negative_fractional_quantities(self):
        for qty in (0, -1, 1.5, 100001):
            with self.subTest(qty=qty), self.assertRaises(ValidationError):
                self.draft(qty)
        self.assertFalse(m.Order.objects.exists())

    def test_unassigned_product_and_location_are_rejected(self):
        with self.assertRaises(ValidationError):
            create_draft(self.user, self.location.pk, self.delivery, {self.restricted.pk: 2})
        with self.assertRaises(PermissionDenied):
            create_draft(self.user, self.other_location.pk, self.delivery, {self.product.pk: 2})
        self.assertEqual(self.client.get(reverse('order-new'), {'location': self.second_location.pk}).status_code, 404)
        self.assertFalse(m.Order.objects.exists())

    def test_unknown_quantity_post_is_rejected(self):
        response = self.client.post(reverse('order-new'), {'location': self.location.pk,
            'delivery_date': self.delivery.isoformat(), f'qty_{self.product.pk}': 3, f'qty_{self.restricted.pk}': 1})
        self.assertContains(response, 'no longer available')
        self.assertFalse(m.Order.objects.exists())

    def test_missing_price_and_disallowed_date_rejected(self):
        self.price.delete()
        with self.assertRaisesRegex(ValidationError, 'no price'):
            self.draft()
        with self.assertRaises(ValidationError):
            create_draft(self.user, self.location.pk, date(2026, 10, 7), {self.product.pk: 3})

    def test_deactivated_product_blocks_submission(self):
        order = self.draft()
        self.link.active = False
        self.link.save()
        with self.assertRaises(ValidationError):
            submit_order(self.user, order.pk)

    def test_cutoff_rechecked_at_submission_and_approval(self):
        order = self.draft()
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(minutes=2)):
            submit_order(self.user, order.pk)
        order.refresh_from_db()
        self.assertTrue(order.requires_approval)
        change_status(self.office, order.pk, m.OrderStatus.CONFIRMED)
        order.refresh_from_db()
        self.assertFalse(order.requires_approval)

    def test_prohibited_late_submit_rolls_back(self):
        order = self.draft()
        self.rule.late_order_policy = m.LatePolicy.PROHIBIT
        self.rule.save()
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(minutes=2)), self.assertRaises(ValidationError):
            submit_order(self.user, order.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, m.OrderStatus.DRAFT)

    def test_customer_cannot_change_status_or_view_production(self):
        order = self.draft()
        self.assertEqual(self.client.post(reverse('order-status', args=[order.pk]), {'status': 'CONFIRMED'}).status_code, 403)
        self.assertEqual(self.client.get(reverse('bake-plan')).status_code, 403)
        self.assertEqual(self.client.get(reverse('order-submit', args=[order.pk])).status_code, 405)

    def test_other_login_cannot_access_or_submit_order(self):
        order = self.draft()
        stranger = get_user_model().objects.create_user('order-stranger')
        m.CustomerAccess.objects.create(user=stranger, customer=self.other, location=self.other_location)
        self.client.force_login(stranger)
        for name in ('order-detail', 'order-submit'):
            response = self.client.post(reverse(name, args=[order.pk])) if name == 'order-submit' else self.client.get(reverse(name, args=[order.pk]))
            self.assertEqual(response.status_code, 404)
        self.assertNotContains(self.client.get(reverse('orders')), order.order_number)

    def test_bakery_pending_date_filter_and_status_lifecycle(self):
        order = submit_order(self.user, self.draft().pk)
        self.client.force_login(self.office)
        self.assertContains(self.client.get(reverse('orders')), order.order_number)
        self.assertNotContains(self.client.get(reverse('orders'), {'date': '2026-10-08'}), order.order_number)
        with self.assertRaises(ValidationError):
            change_status(self.office, order.pk, m.OrderStatus.DELIVERED)
        for status in (m.OrderStatus.CONFIRMED, m.OrderStatus.PRODUCTION, m.OrderStatus.READY_TO_PICK, m.OrderStatus.DELIVERED):
            change_status(self.office, order.pk, status)
        self.assertNotContains(self.client.get(reverse('orders')), order.order_number)
        self.assertContains(self.client.get(reverse('orders'), {'scope': 'all', 'date': '2026-10-06'}), order.order_number)

    def test_office_dashboard_groups_orders_by_status_and_filters_delivery_date(self):
        first = submit_order(self.user, self.draft().pk)
        second = submit_order(self.user, self.draft(2).pk)
        change_status(self.office, first.pk, m.OrderStatus.CONFIRMED)
        self.client.force_login(self.office)

        response = self.client.get(reverse('dashboard'), {'date': self.delivery.isoformat()})
        groups = response.context['order_status_groups']
        self.assertEqual([group['label'] for group in groups], [
            'Submitted', 'Confirmed', 'Production', 'Ready to pick', 'Delivered'])
        self.assertEqual(groups[0]['count'], 1)
        self.assertEqual(groups[0]['orders'][0].pk, second.pk)
        self.assertEqual(groups[1]['count'], 1)
        self.assertEqual(groups[1]['orders'][0].pk, first.pk)
        self.assertContains(response, first.order_number)
        self.assertContains(response, second.order_number)

        response = self.client.get(reverse('dashboard'), {'date': '2026-10-08'})
        self.assertTrue(all(group['count'] == 0 for group in response.context['order_status_groups']))
        self.assertNotContains(response, first.order_number)
        self.assertNotContains(response, second.order_number)

        orders_response = self.client.get(reverse('orders'))
        self.assertEqual(orders_response.context['scope'], 'pending')
        self.assertNotContains(orders_response, 'Status overview')

    def test_reorder_uses_quantities_and_new_price(self):
        order = submit_order(self.user, self.draft(7).pk)
        response = self.client.get(reverse('order-new'), {'location': self.location.pk, 'reorder': order.pk})
        self.assertEqual(response.context['form'][f'qty_{self.product.pk}'].value(), 7)
        self.price.price = 29
        self.price.save()
        second = self.draft(7)
        self.assertEqual(second.total, 203)

    def test_reorder_warns_when_product_removed(self):
        order = submit_order(self.user, self.draft().pk)
        self.link.active = False
        self.link.save()
        self.assertContains(self.client.get(reverse('order-new'), {'location': self.location.pk, 'reorder': order.pk}), 'Unavailable products omitted')

    def test_all_new_screens_render(self):
        order = self.draft()
        for url in (reverse('order-new'), reverse('order-new') + f'?location={self.location.pk}', reverse('orders'), reverse('order-detail', args=[order.pk]), reverse('dashboard')):
            self.assertEqual(self.client.get(url, follow=True).status_code, 200)
        self.client.force_login(self.office)
        self.assertEqual(self.client.get(reverse('bake-plan')).status_code, 200)
        self.assertContains(self.client.get(reverse('dashboard')), 'Print status overview')
        self.assertContains(self.client.get(reverse('orders')), 'Print orders')
        self.assertContains(self.client.get(reverse('bake-plan')), 'Print bake totals')
        self.assertContains(self.client.get(reverse('order-detail', args=[order.pk])), 'Print order')

    def test_aggregate_across_customers_snapshots_and_trays(self):
        first = submit_order(self.user, self.draft(3).pk)
        m.CustomerDeliveryRule.objects.create(customer=self.other, location=self.other_location, delivery_days=[1])
        m.CustomerProduct.objects.create(customer=self.other, product=self.product)
        m.ProductZonePrice.objects.create(product=self.product, zone=1, price=11, effective_date=date(2026, 1, 1))
        second = create_draft(self.office, self.other_location.pk, self.delivery, {self.product.pk: 4})
        submit_order(self.office, second.pk)
        self.draft(99)  # Drafts never become bake demand.
        self.client.force_login(self.production)
        response = self.client.get(reverse('bake-plan'), {'date': '2026-10-05'})
        row = response.context['rows'][0]
        self.assertEqual((row['quantity'], row['units'], row['trays'], len(row['orders']), len(row['customers'])), (7, 42, 4, 2, 2))
        self.product.pack_size = 100
        self.product.units_per_tray = 100
        self.product.save()
        response = self.client.get(reverse('bake-plan'), {'date': '2026-10-05'})
        self.assertEqual(response.context['rows'][0]['units'], 42)
        change_status(self.office, first.pk, m.OrderStatus.CANCELLED)
        response = self.client.get(reverse('bake-plan'), {'date': '2026-10-06', 'basis': 'delivery'})
        self.assertEqual(response.context['rows'][0]['quantity'], 4)

    def test_approval_demand_is_separate_until_approved(self):
        with patch('django.utils.timezone.now', return_value=self.now + timedelta(minutes=2)):
            order = submit_order(self.user, self.draft(5).pk)
        self.client.force_login(self.office)
        response = self.client.get(reverse('bake-plan'), {'date': '2026-10-05'})
        row = response.context['rows'][0]
        self.assertEqual((row['quantity'], row['approval_quantity'], row['units']), (0, 5, 0))
        change_status(self.office, order.pk, m.OrderStatus.CONFIRMED)
        response = self.client.get(reverse('bake-plan'), {'date': '2026-10-05'})
        self.assertEqual(response.context['rows'][0]['units'], 30)

    def test_invalid_dates_show_errors_without_unfiltered_data(self):
        submit_order(self.user, self.draft().pk)
        self.client.force_login(self.office)
        for name in ('orders', 'bake-plan'):
            response = self.client.get(reverse(name), {'date': 'not-a-date'})
            self.assertContains(response, 'Enter a valid date')
            self.assertFalse(response.context.get('rows', response.context.get('page')).__len__())
