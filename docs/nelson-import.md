# Nelson product import

Source: `DFB_Products_Nelson.xlsx`, worksheet `dbo_Products`, rows 2–229. The original workbook is unchanged. Imported on October 3, 2026, with an explicitly selected initial price-effective date of October 3, 2026. Source `Updated` timestamps remain provenance and are not treated as price-effective dates.

Result: **228 products**, **228 linked source records**, **684 zone records**, containing all **2,052 supplied wholesale/retail/return price values**. Repeat import on the same effective date reports 228 unchanged products and creates no extra audit events or duplicate records.

| Zone | Ordering / wholesale | Retail | Return |
| --- | --- | --- | --- |
| 1 | G — Price | J — RetailPrice | M — ReturnPrice |
| 2 | H — Price2 | K — Retail2 | O — ReturnPrice2 |
| 3 | I — Price3 | L — Retail3 | P — ReturnPrice3 |

Current assumption: customer orders use **wholesale prices for individual SKU items**. Pack size is one ordering item; UnitsPerTray is retained separately, without multiplying the source price. The user was asked to confirm wholesale versus retail/return ordering prices and item versus full-tray ordering. If full-tray ordering is required, adapt the pricing and quantity-unit service together before enabling order submission.

Every customer must have zone 1, 2, or 3. An active dated CustomerPriceOverride for a permitted customer/product takes priority over the customer's assigned zone. Missing assigned-zone prices do not fall back to another zone. Customers only see their own resolved ordering prices.

## Product identity and source preservation

- C: product name; D: source SKU, retained as text and also used as the source UPC; E: unmodified size text; F: category; S: units per tray.
- A (VendorsId), B (Vendor), N (ReturnComm), Q (ReturnSamePrice), R (CostPrice), T (Updated), U (UserID), and all other source values remain in ProductSourceRecord, including leading zeros.
- Master product code is the transparent source-derived compound `Sku-VendorsId`. Source identity is the tuple `Vendor | VendorsId | Sku`, which is unique in this workbook. This avoids losing distinct rows where one source identifier is reused.
- The workbook has 52 Cake, 168 Seabra, and 8 Bread category records. Category labels are preserved exactly rather than reclassified.
- Vendor label Seabra appears in 176 records; 52 vendor labels are blank. These labels are provenance, not sufficient evidence to create a customer, choose its zone, or grant product access. Assign CustomerProduct explicitly to a real customer account. VendorIDs remain customer-product relationship data when an account-specific mapping is entered.

## Source issues retained for review

SKU/UPC **655746112342** is shared by two different products:

| Source row | Product | Source VendorID | Master code |
| --- | --- | --- | --- |
| 51 | SO Copitas | 163 | 655746112342-163 |
| 52 | SO Flan | 164 | 655746112342-164 |

Both are imported, kept separate, and flagged in the product list/details. Verify the barcode before implementing scanning or merging records. VendorsId `231068` is also reused by two different SKU rows; the compound source key retains both.

## Reusable import

```cmd
python manage.py import_nelson DFB_Products_Nelson.xlsx --effective-date 2026-10-03 --dry-run
python manage.py import_nelson DFB_Products_Nelson.xlsx --effective-date 2026-10-03
```

The custom Import data screen also offers **Nelson workbook · products + all zone prices**. Choose the effective date and use validation-only first. The importer verifies headers, text identifiers, finite nonnegative prices, positive tray counts, and distinct source identities. It validates every model and commits the workbook atomically. Later price periods require closing existing overlapping periods; the custom product zone editor performs that closure atomically.

## Custom administration

`/admin/` redirects to `/administration/`, the custom Bakery workspace. Manage products, zone price grids, customers, locations, product availability, SKU-specific special prices, delivery rules, logins/roles, and customer access there. User creation and role edits require authentication-model permissions; bakery office users can manage business records through the custom UI without the Django staff flag. Audit events never store plaintext passwords or password hashes.

Django's maintenance backend remains at `/maintenance-admin/` for authorized maintenance, with no links to it in the normal workspace. Order/production workflows remain outside this master-data release.
