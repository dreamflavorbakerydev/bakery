# Proposed CI/CD workflow (activation requires owner approval)

The owner approved the workflow on October 30, 2026, with a separate approval
required **before the first production migration or production deployment**.
Continue setup and preview validation, but leave `CICD_PRODUCTION_ENABLED`
unset/false until that specific release approval. Workflow approval alone does
not authorize merging this PR or starting the production candidate build.

## Component setup progress

The setup credentials now authenticate with GitHub, Vercel, and Neon. Two
isolated preview projects have been created without modifying production:

| GitHub variable | Verified value |
| --- | --- |
| `VERCEL_ORG_ID` | `team_zS6Uy4YLIfwbozJHrYtIHFPc` |
| `VERCEL_PREVIEW_PROJECT_ID` | `prj_fQllGlbJYrAMEumN6tBM7UG8HsJK` |
| `VERCEL_PRODUCTION_PROJECT_ID` | `prj_Nvmmgkrkwe0IyprzmIKPYwhxDBDT` |
| `NEON_PREVIEW_PROJECT_ID` | `withered-shadow-45786432` |
| `NEON_PREVIEW_PARENT_BRANCH_ID` | `br-raspy-frost-b8rb1wkq` |
| `NEON_PRODUCTION_PROJECT_ID` | `morning-hat-82636050` |
| `NEON_DATABASE` | `neondb` |
| `NEON_ROLE` | `neondb_owner` |

These are resource identifiers, not credentials. They have **not** been written
to GitHub variables because its administration API denies the setup token.
The Vercel `bakery-ci-previews` project has Deployment Protection enabled and
no Git repository link, so it will not duplicate the production Git integration.
The Neon `Bakery CI previews` project is PostgreSQL 17 with a fresh empty
`preview-baseline` branch; no production data was copied. An empty baseline is
valid because each preview runs all migrations from zero. A validation child
`br-super-cloud-b897sbjn` was created from this baseline to verify branch
creation; no database migrations or application deployments were run.

The account rejects explicit custom suspend intervals, including 300 seconds,
with HTTP 412. The pinned action now passes the documented value `0` to use the
account default, which succeeded in the preview branch-creation check.

Remaining account blocker: `GITHUB_SETUP_TOKEN` authenticates but still receives
HTTP 403 for environment creation (`administration=write` required), Actions
secrets/variables, branch protection, and webhook inventory. Update that
credential's repository permissions as described below and reapply it securely.
Do not create duplicate preview projects or mint deployment keys until they can
be transferred directly into GitHub encrypted environment secrets. Vercel's API
supports project-scoped deployment tokens (`projectId`); use the preview project
scope rather than reusing the broad setup credential. Neon likewise supports
organization API keys scoped to one project. No runtime preview secrets have
been minted or installed yet. Existing test failures remain release blockers.

This change prepares automation for review; the live setup progress above
records the separate preview resources created. No production resources were
changed, no production migrations ran, and no application deployment was made.
Neither deployment switch has been enabled by this task.

## Inspection

The inspected checkout is commit `dfd1974bdc55e1db20e3f1ffd76e37de90c1539c`.
It had no `.github/workflows`, `vercel.json`, or deployment scripts. It uses
Django 5.2.17, PostgreSQL through `dj-database-url`/psycopg, and reads
`DATABASE_URL` from the process or ignored dotenv files. `neon.ts` configures
Neon branch TTL for the local CLI; it does not provision PR databases or apply
Django migrations. `.vscode/mcp.json` references a Neon project; it grants this
workflow no credentials. README documents an existing Vercel deployment and
Neon pooled versus direct URLs. No application source or existing migrations
were changed for this workflow.

Git HTTPS and GitHub API repository/workflow reads now succeed. The live
inventory on October 30, 2026 found no Actions workflows, deployment
environments, repository rulesets, open PRs, or deployment records. The connected
GitHub integration returns HTTP 403 for webhooks, Actions permissions,
secret/variable metadata, branch protection, and preview-environment creation.
Repository admin status does not override a credential's narrower API
permissions. Vercel and Neon setup credentials are now available: inspection
confirmed the existing Vercel `bakery` Django project links to this repository's
`main` branch, uses automatic system environment variables and Deployment
Protection, and has separate production/development database bindings. The
existing Neon project has a default `production` branch and other development
branches; none were modified. Before activation, complete the inventory of
GitHub Actions, environments, branch rules and installed apps; Vercel Git
settings, build commands, deploy hooks and environment variables; and Neon
GitHub/Vercel integrations and branch automation. Remove or disable overlapping
deployment/migration owners **only after approval**. Never run this alongside
an independent integration that also creates branches or deploys main.

## What runs

1. Codex works on a feature branch and submits a pull request to `main`. Never
   push feature work directly to `main`. Human approval and branch protection
   enforce the merge boundary; this workflow does not auto-merge PRs.
2. `Django tests` runs on PRs and merged `main` commits. It uses disposable
   runner-local PostgreSQL 17, Python 3.13, deployment safety tests, Django
   checks, migration drift detection, real migrations, all bakery tests, and
   static asset collection. No production credentials enter this job.
3. For a same-repository PR, when previews are enabled, GitHub Actions creates
   a new Neon branch from an explicitly selected, sanitized baseline in a
   **separate preview project**. The name includes PR number, run ID, and
   attempt. It applies migrations via the direct URL, then tells Vercel to
   build/deploy with the new branch's pooled URL at build and runtime. Login
   and CSS responses are checked over HTTPS. The URL appears on the GitHub
   environment deployment. Fork/Dependabot PRs get tests only. No
   `pull_request_target` or privileged `workflow_run` executes PR code.
4. After a reviewed PR merges, tests run again on the merge commit. Production
   release is skipped unless `CICD_PRODUCTION_ENABLED=true`. With it enabled,
   the job waits for the protected `production` environment approval. It
   refuses an obsolete commit, verifies the configured database identity,
   builds a Vercel production candidate with `--skip-domain`, applies allowed
   migrations, checks login/CSS, and promotes that exact candidate.

Vercel performs preview builds automatically when Actions submits a successful
PR run. Actions is the single deployment coordinator: `vercel.json` disables
Vercel's parallel Git-triggered deployments and sets a static-only build command.
There is **no migration in the build command**. Review this routing change
before merging; the JSON file affects Vercel when the repository configuration
is adopted. No live Vercel setting was changed during preparation.

A failed test, build, migration, or smoke check prevents production promotion.
Production release jobs serialize and do not cancel active migrations. GitHub
concurrency may replace an older pending run with a newer one; it is not a FIFO
release queue. A candidate built with `--skip-domain` still has a deployment URL:
enable Vercel Deployment Protection for production candidates.

## GitHub configuration after approval

Create `preview` and `production` environments **before** enabling deployment.
For `production`, require an owner/release reviewer, prevent self-review,
restrict deployment branches to protected `main`, and disallow protection
bypass where your GitHub plan supports it. Review preview code before it gets
credentials; require approval for the `preview` environment when contributors
are not all trusted. Same-repository PR code can read preview credentials.

Protect `main`: require a PR, your approving review, the status check
`Django tests`, up-to-date branches, dismissal of stale approvals, approval of
the latest push, and no direct pushes/bypass. Configure CODEOWNERS/rules so
workflow, deployment helper, and migration changes require an owner review.
The Actions token needs only `contents: read`; no PAT or write permission is
needed for deployments. Codex needs separate scoped GitHub permission to push
feature branches and open PRs; the runner's read-only token cannot do that.

### Current account-setup prerequisites

The cloud configuration declares these setup-only HTTPS credentials. Values
are supplied and authentication is verified; only the GitHub credential's
administration permissions still need correction. Update it securely in
environment settings, not in chat. Keep the working Vercel/Neon bindings:

| Cloud secret | Destination | Use |
| --- | --- | --- |
| `GITHUB_SETUP_TOKEN` | `api.github.com` | Repository-scoped administration access for deployment environments, Actions secrets/variables, and protection settings that the existing connection cannot manage. |
| `VERCEL_SETUP_TOKEN` | `api.vercel.com` | Inspect existing Vercel integrations and configure the separate preview project. |
| `NEON_SETUP_API_KEY` | `console.neon.tech` | Inspect Neon configuration and prepare the nonproduction preview project/baseline. |

The draft adds those two API destinations while preserving GitHub access.
Saving requirements does not supply values or apply them to the running machine.
These setup credentials do not automatically create the GitHub Actions secrets
listed below. Scope setup credentials to the required accounts/projects; use
read-only production access for inspection and write access only for preview
resources. No production resource change or migration is authorized by this
setup step.

For the GitHub setup token, use a fine-grained token limited to
`dreamflavorbakerydev/bakery`: Environments, Secrets, Variables, and
Administration read/write; Actions and Webhooks read access for inventory.
Obtain repository-owner authorization where GitHub requires it. Keep normal
Git pushes and PR creation on the working platform authentication; the separate
setup token is only for the explicitly authorized administration requests.
Never print or write its value into the checkout.

Alternatively, the GitHub connection must additionally support managing repository Actions
variables/secrets, deployment environments, and reviewing protection/webhook
settings. Current requests fail with `Resource not accessible by integration`.
If the connection cannot receive those permissions, an authenticated repository
administrator must perform those settings in GitHub:
[environments](https://github.com/dreamflavorbakerydev/bakery/settings/environments),
[Actions secrets and variables](https://github.com/dreamflavorbakerydev/bakery/settings/secrets/actions),
and [branch rules](https://github.com/dreamflavorbakerydev/bakery/settings/rules).
Do not replace platform Git authentication or paste a GitHub token into chat.
Keep `CICD_PRODUCTION_ENABLED` unset/false throughout component setup.

Repository variables (switches must be repository variables, not environment
variables, because job conditions are evaluated before entering an environment):

| Variable | Value/purpose |
| --- | --- |
| `CICD_PREVIEWS_ENABLED` | Leave unset initially. Set `true` after preview setup is approved. |
| `CICD_PRODUCTION_ENABLED` | **Leave unset/false until explicit workflow approval.** |
| `VERCEL_ORG_ID` | Vercel team/account ID. |
| `VERCEL_PREVIEW_PROJECT_ID` | Separate Vercel preview project; cannot equal production. |
| `VERCEL_PRODUCTION_PROJECT_ID` | Existing production Vercel project ID. |
| `NEON_PREVIEW_PROJECT_ID` | Separate nonproduction project with sanitized/fictional data. |
| `NEON_PRODUCTION_PROJECT_ID` | Actual production project ID; must differ from preview. |
| `NEON_PREVIEW_PARENT_BRANCH_ID` | Baseline branch ID in the preview project. |
| `NEON_DATABASE`, `NEON_ROLE` | Explicit existing preview database and role. |
| `PRODUCTION_DATABASE_HOST` | Exact direct endpoint hostname, without scheme/port/path. |
| `PRODUCTION_DATABASE_NAME` | Exact existing production database name. |

Store the following as **environment secrets**, never in source, PR comments,
chat, artifacts, or committed dotenv files:

| Environment | Secret | Purpose |
| --- | --- | --- |
| preview | `NEON_PREVIEW_API_KEY` | Project-scoped key for the preview project only; branch creation/connection access. No production-project access. |
| preview | `VERCEL_PREVIEW_TOKEN` | Deploy access to the preview Vercel project only, using the narrowest available team/project role. |
| preview | `DJANGO_PREVIEW_SECRET_KEY` | Private preview-only Django key. |
| preview | `VERCEL_PREVIEW_BYPASS_SECRET` | Automation bypass secret if preview Deployment Protection is enabled. |
| production | `VERCEL_PRODUCTION_TOKEN` | Deploy/promote access to the existing production project. |
| production | `PRODUCTION_DATABASE_URL` | Existing pooled production URL, used by Vercel runtime/build. Require TLS. |
| production | `PRODUCTION_DATABASE_URL_DIRECT` | Direct URL to the same existing database; DDL permissions for reviewed migrations. Require TLS. |
| production | `DJANGO_PRODUCTION_SECRET_KEY` | Existing stable production Django key; do not replace it for each deployment. |
| production | `VERCEL_PRODUCTION_BYPASS_SECRET` | Automation bypass for protected production candidate smoke checks. |

Use separate service accounts/teams/projects if your provider cannot scope a
token sufficiently. Do not give preview tokens access to production. Do not
reuse a production database password in CI tests. Rotate any database password
that has been shared in chat before storing its replacement securely.

GitHub-hosted runners need HTTPS to GitHub, PyPI, npm, Neon API
(`console.neon.tech`), Vercel APIs/build services, and deployment URLs. Direct
PostgreSQL migration connections need TCP 5432 to the corresponding Neon
endpoints. A proxy-only cloud secret is not automatically a raw PostgreSQL
password: GitHub environment secrets must contain usable connection strings.
None of these GitHub secrets are required just to run local unit/DB tests.

## Vercel and Neon setup after approval

In Vercel, verify the correct repository/root directory and Django framework
preset with Python 3.13 available (pinned in `.python-version`). Use the checked-in `vercel.json` and no
dashboard install/build hook that applies migrations. Confirm project settings
or framework detection locate `config/wsgi.py`, collect static files, and serve
`/static/bakery/app.css`; the smoke step refuses promotion if either fails.
Enable system environment variables so `VERCEL_URL` is available for Django's
allowed-host handling. Keep production custom hosts and CSRF origins configured
as documented in README. Keep Deployment Protection on candidates/previews,
with automation bypass secrets as needed. Existing production environment
values stay intact; Actions explicitly supplies the intended database/key for
each new deployment. Do not use a Production DATABASE_URL as a Preview default.

Reuse the separate Neon preview project and baseline listed above. An empty
baseline is supported; if a baseline already has application tables, it must
also have matching `django_migrations` records. Use fictional data only. Do not
copy production customers, contacts, users,
password hashes, sessions, or orders. A schema-only clone without migration
history is not a usable baseline for `manage.py migrate`. Verify the preview
role has permission to apply schema migrations. Preview runs never reset a
branch; a new run gets a new database branch. Automatic deletion/TTL is
deliberately absent. Monitor branch/storage quotas and manually remove obsolete
branches **only within the separate preview project** after their deployments
are no longer needed. The existing `neon.ts` TTL is unrelated to this action.

## Production data and migration policy

The helper requires matching expected direct hostname/database for both runtime
and migration URLs, acquires a PostgreSQL session advisory lock, applies lock
and statement timeouts, checks migration consistency/conflicts, and validates
the complete pending plan before running any migration. Only atomic forward
migrations with exact Django operation types `CreateModel`, `AddField`,
`AddIndex`, `AddConstraint`, `AlterModelOptions`, `AlterModelManagers`, and
`AlterModelTableComment` are allowed. Subclasses and unknown operations fail
closed. There is no delete, reset, flush, reverse migration, or automatic
database rollback command in the deployment automation.

`RemoveField`, `DeleteModel`, `AlterField`, raw SQL, `RunPython`, state/database
wrappers, and non-atomic migrations block release and require a separate,
explicitly reviewed migration procedure. Existing migrations contain data
migrations and field removals: this workflow must not bootstrap production from
zero or silently replay those operations. Verify the existing migration history
before enabling it. Never relax this guard just to make a release pass.

Use expand/contract releases: additive changes must remain compatible with the
currently serving application. Even additive constraints/defaults can lock or
rewrite tables; review their production cost. Never automate a contract/drop
phase under this workflow. Review application code as well as migrations:
arbitrary approved Python code is trusted code, and a migration allowlist is
not a sandbox for malicious code.

Verify Neon backup/PITR retention and a recovery procedure before approval.
If a later migration fails, earlier successful migrations can remain applied;
Django transactions are per migration, not for the whole release. Failed smoke
or promotion can likewise leave an expanded schema and an unpromoted candidate.
Keep the current production deployment and data, investigate, and roll forward
with a reviewed fix. Never automatically roll back/reset the database. Release
and schema changes are not a single distributed transaction.

## Review and activation order

1. Review the PR containing these files. Inventory live integrations/settings
   to rule out duplicate deployment or migration owners. Keep both switches off.
2. Configure/protect the GitHub environments and branch rules, preview projects,
   secrets and variables. Confirm existing production values without changing
   production resources as part of this review.
3. After approving preview setup, enable previews and open a harmless PR. Verify
   its Neon branch, migration history, Vercel database isolation, login/static
   checks, and that a deliberately failing test blocks deployment. Verify a
   deliberately failing migration on a disposable preview blocks deployment.
4. Review the production migration policy, backups, Vercel Git deployment
   handoff and protected-environment approval. **Only after your explicit
   approval for the first production migration/deployment**, enable production releases and adopt the single-coordinator
   configuration. Merge a reviewed PR and approve its environment deployment.
5. Verify the first candidate is protected, migrations target the approved direct
   endpoint, and promotion occurs only after migration and smoke success.

Account activation, live preview delivery, production migration and production
promotion are intentionally not claimed as tested during preparation.

## Current validation and release blockers

Local validation used Python 3.13.5, Django 5.2.17 and a disposable PostgreSQL
17 container, with no connection to Neon or production. Actionlint 1.7.11
accepted the workflow. Django system checks, migration drift detection, empty
database migrations, static collection, and real login/CSS HTTP requests passed.
All 12 deployment guard unit tests passed.

The existing bakery suite executed 153 tests: 150 passed, one failed and two
errored. These failures are retained as release blockers, not skipped:

| Existing test | Diagnosis |
| --- | --- |
| `NelsonTests.test_repeated_import_is_idempotent` | PostgreSQL JSONB reorders `ProductSourceRecord.values` keys. `audit.snapshot` converts dictionaries to strings, so equal JSON objects appear changed and the second import reports an update. Reproduced independently using fictional data in a rolled-back local transaction. |
| `StoreAccessMigrationTests.test_account_grants_become_explicit_stores_without_widening_access` | Migration 0005 writes data with deferred foreign-key trigger events and then adds a constraint within the same atomic migration. PostgreSQL refuses ALTER TABLE with pending trigger events. |
| `StoreDeliveryMigrationTests.test_customer_inheritance_is_materialized_per_store` | Migration 0006 mixes data writes and schema alterations in one atomic migration, producing the same PostgreSQL trigger-event error with populated legacy fixtures. |

Fix those application/migration defects in a separately reviewed code change
before expecting a green release. Empty-database migration success does not
establish that populated production upgrades are safe. Existing app logic,
tests and migrations were left unchanged during CI/CD preparation.

References: [Vercel Django](https://vercel.com/docs/frameworks/backend/django),
[Vercel CLI deploy](https://vercel.com/docs/cli/deploy),
[Vercel promote](https://vercel.com/docs/cli/promote),
[Neon branch action](https://github.com/neondatabase/create-branch-action),
[GitHub deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).
