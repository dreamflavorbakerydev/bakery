from datetime import date
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.urls import reverse

from bakery import models as m
from bakery.services.orders import create_draft
from bakery.tests.test_foundation import FoundationFixture


class OrderDocumentTests(FoundationFixture):
    def setUp(self):
        self.client.force_login(self.user)
        with patch('django.utils.timezone.now', return_value=self.now):
            self.orders = [create_draft(self.user, self.location.pk, date(2026, 10, 6),
                {self.product.pk: quantity}, notes='Leave at front desk') for quantity in (2, 3)]
        self.endpoint = reverse('order-documents')

    def test_print_includes_complete_documents_in_selection_order(self):
        response = self.client.get(self.endpoint, {'order': [o.pk for o in reversed(self.orders)]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['orders']), list(reversed(self.orders)))
        self.assertContains(response, 'class="order-document"', count=2)
        self.assertContains(response, 'Test bread', count=2)
        self.assertContains(response, 'Leave at front desk', count=2)
        self.assertContains(response, 'Order total', count=2)
        self.assertContains(response, 'order-document-print.js')
        self.assertNotContains(response, 'Submit order')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_download_single_pdf_or_zip_with_one_pdf_per_order(self):
        response = self.client.get(self.endpoint, {'action': 'download', 'order': self.orders[0].pk})
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF-'))
        response = self.client.get(self.endpoint, {'action': 'download', 'order': [o.pk for o in self.orders]})
        self.assertEqual(response['Content-Type'], 'application/zip')
        with ZipFile(BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 2)
            for name in archive.namelist():
                self.assertTrue(archive.read(name).startswith(b'%PDF-'))

    def test_selection_rejects_other_customers_and_missing_orders(self):
        other = m.Order.objects.create(order_number='PRIVATE', customer=self.other,
            customer_location=self.other_location, order_date=date(2026, 10, 5),
            requested_delivery_date=date(2026, 10, 6))
        for action in ('print', 'download'):
            for inaccessible in (other.pk, 99999999):
                response = self.client.get(self.endpoint, {'action': action, 'order': [self.orders[0].pk, inaccessible]})
                self.assertEqual(response.status_code, 404)
                self.assertNotIn('Content-Disposition', response)
        self.client.logout()
        self.assertEqual(self.client.get(self.endpoint, {'order': self.orders[0].pk}).status_code, 302)

    def test_invalid_selections_and_duplicate_ids(self):
        for query in ({}, {'order': 'bad'}, {'order': '-1'}, {'order': '1' * 50},
                      {'order': ['1'] * 101}, {'order': '1', 'action': 'bad'}):
            self.assertEqual(self.client.get(self.endpoint, query).status_code, 400)
        response = self.client.get(self.endpoint, {'order': [self.orders[0].pk] * 2})
        self.assertContains(response, 'class="order-document"', count=1)
