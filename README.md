# Bakery

Proposed deployment automation and its approval/setup requirements are documented
in [the CI/CD guide](docs/ci-cd.md). Production automation is disabled by default.

Python/Django bakery ordering and production planning application, implemented incrementally according to the supplied specification. **Customer submission, bakery order handling, and aggregated bake demand are enabled.**

Working features: custom Bakery administration, product and customer editing, nine-value zone price grids, SKU-specific special prices, login creation/role editing, atomic/idempotent CSV/XLSX imports and template downloads, individual logins/password changes, explicit role permissions and location access, customer-scoped product catalogs, centralized dated zone/override pricing, delivery calendars/cutoffs/late policies, master-data audit trail, and responsive screens.

Customers can browse the full active catalog by default, or their configured custom product list, enter quantities with live line and order totals, refresh prices for the chosen delivery date, review drafts, submit orders, view their history, and reorder using current prices. The bakery sees pending orders across customers, filters by delivery date, approves late orders, and moves orders through confirmation, preparing, ready-to-pick, delivery, or cancellation. Bake totals aggregate outstanding demand by product and production/delivery date, convert packs to units, and estimate trays using saved tray capacities. Forecasting, recording completed bake batches, detailed picking/routing, and invoicing remain future work. The product catalog is populated from `DFB_Products_Nelson.xlsx`: 228 products and 684 zone records preserving all nine price values per product. There are no shared/demo passwords. See [the Nelson import report](docs/nelson-import.md) for column mapping, assumptions, and the duplicate SKU review flag.

Read [the inspection and architecture](docs/architecture.md) for all twelve analysis points, relationships, business rules, ambiguities, and the implementation sequence. Read [the import guide](docs/imports.md) before importing real data.

The GitHub repository contains the application, migrations, tests, and documentation. Local databases (including users and orders), credentials, customer contact transcriptions, WhatsApp source images, workbook imports, and generated artifacts are excluded. A fresh clone starts with an empty database after running migrations; keep private data backups separately. Supply your local workbook when importing products, and pass `--source` to `backfill_whatsapp_customers` when using a private contact transcription. Tests generate fictional customer data and require no private files.

## Run locally on Windows

Python 3.13 and Django 5.2 are used. Neon PostgreSQL is required for local development and deployment; SQLite is not supported. Django reads `DATABASE_URL` from `.env` or `.env.local`, or from the process environment.

```powershell
cd C:\Users\tiram\Bakery
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py setup_roles
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765
```

Pull the Neon branch environment into the ignored `.env.local` file, then run migrations and start the app:

```powershell
npx neon@latest env pull
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8765
```

Use Neon's pooled URL for web requests and its direct/unpooled URL for schema migrations. Keep `.env.local` private and never commit database credentials.

### Deploy on Vercel

Set these project environment variables in Vercel for Production and Preview, then redeploy: `DJANGO_DEBUG=0`, a private `DJANGO_SECRET_KEY`, `DATABASE_URL` set to Neon's pooled connection URL, and `DJANGO_ALLOWED_HOSTS=bakery-tau-brown.vercel.app,bakery.elaineanderic.com`. Enable Vercel system environment variables so each deployment's `VERCEL_URL` is also allowed automatically. The application adds its known Vercel URL hosts and requires PostgreSQL on Vercel; local `.env.local` values are not automatically available to deployed functions.

Open http://127.0.0.1:8765 and sign in using the administrator you created. The local secret is generated once in ignored `.django-secret`; keep it private. Django loads `.env` (or `.env.local` when `.env` is absent) for local development; process environment variables take precedence. Configure deployment secrets in the hosting provider rather than relying on local dotenv files.

Once `.venv` is installed, plain commands such as `python manage.py runserver 0.0.0.0:1122` automatically use the project environment when run from global Python. An explicitly activated virtual environment is respected. The launcher reports a clear error if that environment has an incompatible Django version. This avoids the `CheckConstraint` error caused by the global Django 5.0 installation. When binding to `0.0.0.0`, open `http://127.0.0.1:1122` locally; for access from another computer, include the bakery computer's hostname or LAN IP in `DJANGO_ALLOWED_HOSTS`.

On Windows, `start-bakery.cmd` starts directly with the project interpreter on port 1122 and clears inherited global Python path overrides. Startup prints the Django version and interpreter path before launching. There is no pre-created login: run `.venv\Scripts\python.exe manage.py createsuperuser` and choose your own username/password, then sign in at `http://127.0.0.1:1122`.

## Configure the bakery

1. Import actual customer, location, product, availability, price, override, and delivery files. Start with validation only. Customers can use the full active catalog or a custom product list, selected under Customers > Edit customer > Product settings. Customer SKUs, product names, and VendorIDs are retained when switching catalogs. Existing catalog restrictions are preserved; no mapping records are created automatically.
2. In Administration, open **Logins & access** to create individual logins and choose a role. The custom Bakery administration does not require the Django staff flag; business-record and user-management permissions are checked on the server. `/admin/` opens this custom workspace.
3. On the same login management page, add active **Customer access** assignments. Select each customer explicitly; assigning the CUSTOMER group alone grants no access. Existing delivery addresses and assignment IDs are retained internally.
4. In **Customers > Edit customer**, manage contact details, pricing zone, delivery rules, and optional product settings together. Administration contains only **Logins & access** and the **Change trail**.
5. Review every account's catalog, prices, access, and delivery rules. Dashboard checklist checks record presence only, not complete business readiness.

| Role | Access in this release |
| --- | --- |
| ADMINISTRATOR | All permissions, custom login creation and role management |
| BAKERY OFFICE | Master data, pending/all orders, date filtering, late approvals, status updates and bake totals; no staff flag needed |
| PRODUCTION | Combined bake demand and tray estimates by date; no global prices/customer administration |
| CUSTOMER | Assigned locations/products, review/submission, reorders, order history, own account/password |

`setup_roles` is repeatable and resets those named groups to their documented permissions. Do not use it to preserve manual permission customizations. Master-data changes go through validated custom forms or imports; direct ORM writes bypass model validation. Audit records are read-only in administration. Django's separate maintenance backend is at `/maintenance-admin/`, requires staff and appropriate permissions, and has no normal workspace links. No order/production editing is exposed in admin.

Office navigation shows a red dot beside Orders when an order has been submitted since that login last opened the main Orders list. The indicator checks for new submissions every 30 seconds while the page is visible. Read state is saved per login across devices; drafts and later status changes do not trigger it. Date-filtered and approval-only lists do not clear the indicator.

## Verify

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test bakery
```

The tests use isolated fictional fixtures in a disposable PostgreSQL test database. They cover schema integrity, customer/location isolation, role denial, authentication/CSRF, dated pricing precedence and missing-zone behavior, fixed-query catalog pricing, historical-line preservation, cutoff boundaries/timezones/DST, import insert/update/skip/audit, rollback, dry-run, duplicate/unknown columns, identifier preservation, and Excel validation.

Optional visual QA (with the development server already running on port 8765): install `requirements-dev.txt`, run `python -m playwright install chromium`, then run `.\.venv\Scripts\python.exe tools\verify_ui.py`. It creates and removes one temporary administrator, changes no business records, and saves screenshots in ignored `artifacts/`. Initial verification passed 66 tests and desktop/mobile browser checks. The in-app browser was unavailable, so visual verification used an installed local headless Chromium browser.

## Before deployment

This is a local application, not a deployed ordering service. New order numbers use the database ID in a short sequential format (`B-000001`, `B-000002`, and so on), allocated when the draft is created; existing references remain unchanged, and cancelled orders keep their numbers. Repeat submission is idempotent and status changes use conditional updates. Use Neon PostgreSQL for local development and production, and verify concurrent workflows there before broader deployment. Configure a WSGI server, TLS/static serving, backups, and login throttling before exposing customer accounts publicly. The old `db.sqlite3`, if present, is not read by the application.

Set `DJANGO_DEBUG=0`, a private `DJANGO_SECRET_KEY`, and comma-separated `DJANGO_ALLOWED_HOSTS` (include `bakery.elaineanderic.com` when overriding the default host list). Non-debug mode requires an explicit secret and enables secure cookies, HTTPS redirect, and HSTS. Run `manage.py check --deploy` against the deployment configuration and arrange HTTPS before enabling those settings. Do not use Django's development server for deployment.

The default `CSRF_TRUSTED_ORIGINS` includes `https://bakery.elaineanderic.com` for HTTPS form submissions through the bakery domain. Override with comma-separated `DJANGO_CSRF_TRUSTED_ORIGINS` if needed; each entry must include its scheme. CSRF cookies and form tokens remain required.

Framework references: [Django 5.2 support](https://docs.djangoproject.com/en/6.0/releases/5.2/) and [Django permissions](https://docs.djangoproject.com/en/5.2/topics/auth/default/).
