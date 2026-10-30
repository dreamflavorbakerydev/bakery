import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from django.db import migrations, models
from tools import delivery


class DeliverySafetyTests(unittest.TestCase):
    def test_production_migrations_are_disabled_before_any_connection(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'disabled'):
                delivery.migrate(True)

    def test_only_additive_atomic_forward_migrations_are_allowed(self):
        migration = migrations.Migration('add_note', 'bakery')
        migration.operations = [migrations.AddField('order', 'note', models.TextField(null=True))]
        delivery.validate_plan([(migration, False)])
        for operation in (
            migrations.DeleteModel('Order'),
            migrations.RemoveField('Order', 'note'),
            migrations.AlterField('Order', 'note', models.CharField(max_length=1)),
            migrations.RunSQL('DELETE FROM bakery_order'),
            migrations.RunPython(lambda apps, schema: None),
            migrations.SeparateDatabaseAndState(),
        ):
            with self.subTest(operation=type(operation).__name__):
                migration.operations = [operation]
                with self.assertRaisesRegex(ValueError, 'blocked'):
                    delivery.validate_plan([(migration, False)])
        migration.operations = []
        with self.assertRaisesRegex(ValueError, 'backwards'):
            delivery.validate_plan([(migration, True)])
        migration.atomic = False
        with self.assertRaisesRegex(ValueError, 'non-atomic'):
            delivery.validate_plan([(migration, False)])

    def test_subclass_cannot_hide_destructive_work_as_additive(self):
        class UnsafeAddField(migrations.AddField):
            pass
        migration = migrations.Migration('unsafe', 'bakery')
        migration.operations = [UnsafeAddField('order', 'note', models.TextField(null=True))]
        with self.assertRaisesRegex(ValueError, 'blocked'):
            delivery.validate_plan([(migration, False)])

    def test_production_requires_matching_direct_and_pooled_endpoints(self):
        configuration = {
            'VERCEL_ORG_ID': 'team_example', 'VERCEL_PROJECT_ID': 'prj_example',
            'VERCEL_TOKEN': 'test-only', 'DJANGO_SECRET_KEY': 'test-only',
            'DATABASE_URL': 'postgresql://user@ep-example-pooler.test/db?sslmode=require',
            'DATABASE_URL_DIRECT': 'postgresql://user@ep-example.test/db?sslmode=require',
            'PRODUCTION_DATABASE_HOST': 'ep-example.test',
            'PRODUCTION_DATABASE_NAME': 'db',
        }
        with patch.dict(os.environ, configuration, clear=True):
            delivery.preflight_production()
            for name, value in (
                ('DATABASE_URL', 'postgresql://user@other.test/db?sslmode=require'),
                ('DATABASE_URL_DIRECT', configuration['DATABASE_URL']),
                ('DATABASE_URL_DIRECT', 'postgresql://user@ep-example.test/other?sslmode=require'),
            ):
                with self.subTest(name=name, value=value):
                    with patch.dict(os.environ, {name: value}):
                        with self.assertRaises(ValueError):
                            delivery.preflight_production()

    def test_missing_tls_is_rejected(self):
        for value in ('postgresql://user@ep-example.test/db',
                      'postgresql://user@ep-example.test/db?sslmode=disable',
                      'sqlite:///db.sqlite3'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery.database_identity(value)

    def test_query_options_cannot_override_endpoint_or_tls_checks(self):
        for suffix in ('&sslmode=disable', '&host=other.test', '&dbname=other',
                       '&service=production', '&options=-c%20search_path=other'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                delivery.database_identity('postgresql://user@ep-example.test/db?sslmode=require' + suffix)

    def test_preview_project_cannot_be_production(self):
        values = dict.fromkeys((
            'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID', 'VERCEL_TOKEN',
            'VERCEL_PRODUCTION_PROJECT_ID',
            'DJANGO_SECRET_KEY', 'NEON_PREVIEW_PROJECT_ID',
            'NEON_PRODUCTION_PROJECT_ID', 'NEON_PREVIEW_PARENT_BRANCH_ID',
            'NEON_DATABASE', 'NEON_ROLE',
        ), 'same-project')
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, 'separate Neon projects'):
                delivery.preflight_preview()

    def test_preview_project_cannot_deploy_to_production_vercel_project(self):
        values = dict.fromkeys((
            'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID', 'VERCEL_TOKEN',
            'VERCEL_PRODUCTION_PROJECT_ID', 'DJANGO_SECRET_KEY',
            'NEON_PREVIEW_PROJECT_ID', 'NEON_PRODUCTION_PROJECT_ID',
            'NEON_PREVIEW_PARENT_BRANCH_ID', 'NEON_DATABASE', 'NEON_ROLE',
        ), 'example')
        values['NEON_PREVIEW_PROJECT_ID'] = 'separate-preview'
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, 'separate Vercel projects'):
                delivery.preflight_preview()

    def test_deployment_url_requires_vercel_https(self):
        self.assertEqual(delivery.deployment_url('https://bakery-test.vercel.app/'),
                         'https://bakery-test.vercel.app')
        for value in ('http://bakery-test.vercel.app', 'https://vercel.app.evil.test',
                      'https://user:password@bakery-test.vercel.app',
                      'https://bakery-test.vercel.app/path',
                      'https://bakery-test.vercel.app?token=secret'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                delivery.deployment_url(value)

    @patch('tools.delivery.vercel')
    def test_failed_stage_never_yields_a_deployment(self, vercel):
        vercel.side_effect = ValueError('Build failed')
        with patch('tools.delivery.preflight_production'):
            with patch.dict(os.environ, {'DATABASE_URL': 'test', 'DJANGO_SECRET_KEY': 'test'}):
                with self.assertRaisesRegex(ValueError, 'Build failed'):
                    delivery.deploy(True)

    @patch('tools.delivery.vercel', return_value='https://bakery-candidate.vercel.app\n')
    def test_production_candidate_does_not_assign_domains(self, vercel):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'outputs'
            with patch('tools.delivery.preflight_production'), patch.dict(os.environ, {
                'DATABASE_URL': 'pooled-test-url', 'DJANGO_SECRET_KEY': 'test-key',
                'GITHUB_OUTPUT': str(output),
            }):
                delivery.deploy(True)
            arguments = vercel.call_args.args[0]
            self.assertIn('--prod', arguments)
            self.assertIn('--skip-domain', arguments)
            self.assertEqual(arguments.count('DATABASE_URL=pooled-test-url'), 2)
            self.assertEqual(output.read_text(), 'url=https://bakery-candidate.vercel.app\n')

    def test_preview_migration_refuses_reused_or_parent_branch_before_connection(self):
        with patch('tools.delivery.preflight_preview'), patch.dict(os.environ, {
            'DATABASE_URL': 'unused', 'PREVIEW_BRANCH_ID': 'br-parent',
            'NEON_PREVIEW_PARENT_BRANCH_ID': 'br-parent', 'PREVIEW_BRANCH_CREATED': 'true',
        }):
            with self.assertRaisesRegex(ValueError, 'newly created child branch'):
                delivery.migrate(False)
            with patch.dict(os.environ, {'PREVIEW_BRANCH_ID': 'br-child', 'PREVIEW_BRANCH_CREATED': 'false'}):
                with self.assertRaisesRegex(ValueError, 'newly created child branch'):
                    delivery.migrate(False)


if __name__ == '__main__':
    unittest.main()
