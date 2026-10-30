from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from bakery import models as m
from bakery.product_ids import PRODUCT_ID_ROWS, product_id_expression


class ProductIdTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('product-id-admin', password='Test-password-339!')
        for index, (product_id, sku) in enumerate(PRODUCT_ID_ROWS):
            product = m.Product.objects.create(
                internal_product_code=f'{sku}-{product_id}', sku=sku,
                product_name=f'Product {index:03}',
            )
            m.ProductZonePrice.objects.create(
                product=product, zone=1, price=Decimal('12.50'), effective_date=date(2026, 1, 1),
            )

    def setUp(self):
        self.client.force_login(self.user)

    def test_entire_mapping_and_shared_sku_are_preserved(self):
        self.assertEqual(len(PRODUCT_ID_ROWS), 228)
        products = m.Product.objects.annotate(catalog_product_id=product_id_expression())
        self.assertCountEqual(
            products.values_list('catalog_product_id', 'sku'), PRODUCT_ID_ROWS,
        )
        self.assertEqual(products.filter(catalog_product_id='231068').count(), 2)
        self.assertEqual(set(products.filter(sku='655746112342').values_list('catalog_product_id', flat=True)), {'163', '164'})

    def test_unknown_skus_and_ambiguous_records_do_not_get_guessed_ids(self):
        for code, sku in [('unknown', '999999999999'), ('no-sku', ''), ('ambiguous', '655746112342')]:
            m.Product.objects.create(internal_product_code=code, product_name=code, sku=sku)
        records = m.Product.objects.annotate(catalog_product_id=product_id_expression())
        self.assertEqual(records.filter(catalog_product_id__isnull=True).count(), 3)

    def test_source_record_disambiguates_even_with_custom_internal_code(self):
        product = m.Product.objects.create(internal_product_code='custom', product_name='Custom', sku='655746112342')
        m.ProductSourceRecord.objects.create(
            product=product, source_key='custom-source', workbook='fixture.xlsx',
            sheet='products', row_number=2, values={'VendorsId': '164'},
        )
        self.assertEqual(m.Product.objects.annotate(catalog_product_id=product_id_expression()).get(pk=product.pk).catalog_product_id, '164')

    def test_both_lists_show_ids_and_search_before_pagination(self):
        for route in ['products', 'price-records']:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {'q': '239476'})
                self.assertContains(response, 'Product ID')
                self.assertContains(response, '<td class="sku-cell">239476</td>', html=True)
                self.assertContains(response, '669423598930')
                self.assertEqual(response.context['page'].paginator.count, 1)
                response = self.client.get(reverse(route), {'q': '231068'})
                self.assertEqual(response.context['page'].paginator.count, 2)
                self.assertContains(response, '669423597346')
                self.assertContains(response, '669423597353')

    def test_ids_sort_numerically_on_both_lists(self):
        for route in ['products', 'price-records']:
            with self.subTest(route=route):
                response = self.client.get(reverse(route), {'sort': 'product_id', 'direction': 'asc'})
                self.assertEqual([row.catalog_product_id for row in response.context['page']][:4], ['4', '5', '13', '101'])
                response = self.client.get(reverse(route), {'sort': 'product_id', 'direction': 'desc'})
                self.assertEqual(response.context['page'][0].catalog_product_id, '243002')

    def test_product_ids_do_not_change_existing_detail_links_or_prices(self):
        product = m.Product.objects.get(sku='655746112427')
        for route in ['products', 'price-records']:
            response = self.client.get(reverse(route), {'q': product.sku})
            self.assertContains(response, reverse('product-detail', args=[product.pk]))
            self.assertContains(response, '$12.50')
        product.refresh_from_db()
        self.assertEqual(product.internal_product_code, '655746112427-101')
