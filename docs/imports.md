# Master data imports

For the supplied `DFB_Products_Nelson.xlsx`, select **Nelson workbook · products + all zone prices** in the Import data screen, or use `import_nelson --effective-date YYYY-MM-DD`. The legacy adapter preserves all nine zone prices, sizes, source identifiers, and tray counts; see [the import report](nelson-import.md). The generic imports below expect normalized headers and are separate from this adapter.

Use the workspace **Import data** screen or the CLI. Both use the same service. Download CSV templates from the screen; each contains headers and no fabricated records. UTF-8 CSV and the active sheet of XLSX workbooks are supported. Legacy `.xls` is not supported; convert it explicitly to XLSX first.

The file's first row must contain unique, exact headers. Unknown columns are errors to prevent unnoticed data loss. Required cells must have values. Empty rows are skipped. Blank optional cells leave existing values unchanged; to change a value, supply it explicitly. To clear optional values, use administration. A file is committed atomically only when every row validates. Errors name row numbers. Duplicate keys in one file are rejected. Repeated files skip unchanged records and update changed records. `--dry-run` validates and reports without writing either data or audit events.

| Command / template | Required columns | Record key |
| --- | --- | --- |
| import_customers | customer_name, pricing_zone; customer_id or customer_code | existing customer_id or unique customer_code |
| import_locations | customer_id or customer_code, location_code, location_name | customer + location_code |
| import_products | internal_product_code, product_name, pack_size, unit_of_measure | internal_product_code |
| import_customer_products | customer_id or customer_code, internal_product_code | customer + product |
| import_prices | internal_product_code, zone, price, effective_date | product + zone + effective_date |
| import_price_overrides | customer_id or customer_code, internal_product_code, override_price, effective_date | customer + product + effective_date |
| import_delivery_rules | customer_id or customer_code, location_code, delivery_days | store |

Optional columns:

- Customers: customer_id, customer_code, address, city, state, zip, phone, active, timezone, payment_terms, notes.
- Locations: store_number, address, city, state, zip, phone, active.
- Products: description, upc, sku, size, units_per_tray, category, production_lead_days, active, sort_order.
- Customer products: vendor_id, customer_sku, customer_product_name, active, sort_order.
- Zone prices: expiration_date, active, retail_price, return_price.
- Overrides: expiration_date, active, reason, notes.
- Delivery rules: production_lead_days, order_cutoff_time, timezone, late_order_policy.

Import customers first; then locations/products; then customer-product relationships; then prices/overrides and delivery rules. Customer references accept the numeric customer_id shown in the customer directory or an exact customer_code. If both identify a relationship, they must refer to the same customer. Other foreign keys match exact text codes. Missing masters are errors. Special prices follow the ordering catalog: customers using the full catalog can receive overrides for any active product without a mapping. Customers with a custom list require an active mapping for that product. Saving a special price never creates mappings or changes catalog access. This importer never grants access automatically based on names or prices.

Customer codes are optional in the app. Every customer has an automatic, permanent database ID. Add a new customer without a code in **Customers**, then use its customer_id for later imports and relationships. Customer imports need an existing customer_id or a unique customer_code so repeated files cannot merge unnamed identities or create duplicate accounts. Phone numbers and ZIP codes remain text. The customer editor saves customer contact details and its delivery address together. Existing additional addresses remain available in the same editor when present.

The two supplied WhatsApp photos were transcribed in `docs/data/whatsapp-customers.json`. The repeatable `backfill_whatsapp_customers --zone 1` command fills contacts, creates a MAIN delivery location for each account, and audits changes. Use `--dry-run` to validate first. It refuses conflicting existing contact values and commits all rows together. The 18 photo customers use Zone 1 as instructed; source labels and the GOLD MEDAL address discrepancy are preserved in customer notes.

Manage delivery days, notice, cutoff, timezone, and late-order policy under **Administration ? Stores & delivery ? Edit store**. Saving store contacts and its calendar is atomic. Existing customer calendars and inherited defaults are materialized per store during migration; future stores have no calendar until one is configured. Customer timezone is retained for account pricing dates and no longer controls store delivery deadlines.

## Values

- Store codes, UPCs, VendorIDs, SKUs, phone/ZIP/store numbers **as text in Excel**. Numeric Excel identifiers are rejected because leading zeros cannot be recovered safely.
- Product pack size is a positive integer; unit_of_measure explicitly names the ordering unit, such as `case`.
- Pricing zones are `1`, `2`, or `3`. Prices are nonnegative finite decimal values with at most two decimal places; zero is valid. Currency symbols and thousands separators are not accepted.
- Dates use `YYYY-MM-DD` or native Excel date cells. Expiration dates include their final day. Active periods for the same zone/product or customer/product may not overlap. Close the old period before creating a replacement. Import price rows chronologically when closing/opening periods in the same file.
- Booleans accept true/false, yes/no, 1/0, or native Excel booleans.
- Times use 24-hour `HH:MM` or native Excel time cells. Timezones use IANA names such as `America/New_York`.
- Delivery days are comma-separated integers, Monday `0` through Sunday `6`. In CSV quote the cell, for example `"1,3,5"`. location_code is required: each delivery calendar belongs to one store. Missing calendars stay unconfigured.
- Late policy: `ALLOW`, `APPROVAL`, or `PROHIBIT`. Each store keeps its own settings. For a new imported rule, omitted optional settings use 1 day notice, 14:00 cutoff, America/New_York timezone, and APPROVAL. Blank optional cells on later imports leave its saved settings unchanged.
- Excel formulas are rejected; export explicit business values rather than relying on cached formula results.

```powershell
.\.venv\Scripts\python.exe manage.py import_customers path\customers.xlsx --dry-run
.\.venv\Scripts\python.exe manage.py import_customers path\customers.xlsx
```

The web form accepts files up to 5 MB and defaults to validation only. Uncheck **Validate only** to commit. Import activity records before/after values and the source filename; imports do not log raw file contents.

Choose Full catalog or Custom product list in **Customers > Edit customer > Product settings**. Customer-product imports maintain product identifiers and availability settings without changing a saved catalog choice. Switching to Full catalog retains existing customer SKUs, product names, and VendorIDs.
