"""Read-only reconciliation of persisted products against the supplied workbook."""
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from openpyxl import load_workbook
from bakery.models import ProductSourceRecord, ProductZonePrice

workbook = load_workbook(ROOT / 'DFB_Products_Nelson.xlsx', read_only=True, data_only=True)
sources = {record.source_key: record for record in ProductSourceRecord.objects.select_related('product')}
prices = {(record.product_id, record.zone): record for record in ProductZonePrice.objects.filter(effective_date='2026-10-03')}
product_count = price_count = 0
try:
    for row in workbook['dbo_Products'].iter_rows(min_row=2, values_only=True):
        key = f'{row[1] or ""}|{row[0]}|{row[3]}'
        source = sources[key]
        assert source.product.sku == row[3], key
        assert source.product.upc == row[3], key
        assert source.product.product_name == row[2], key
        assert source.product.size == str(row[4] or ''), key
        assert source.product.units_per_tray == int(row[18]), key
        assert source.values['VendorsId'] == row[0], key
        for zone, indices in {1: (6, 9, 12), 2: (7, 10, 14), 3: (8, 11, 15)}.items():
            stored = prices[(source.product_id, zone)]
            for field, index in zip(('price', 'retail_price', 'return_price'), indices):
                assert getattr(stored, field) == Decimal(str(row[index])).quantize(Decimal('.01')), (key, zone, field)
                price_count += 1
        product_count += 1
finally:
    workbook.close()
print(f'Reconciled {product_count} products and all {price_count} source price values.')
