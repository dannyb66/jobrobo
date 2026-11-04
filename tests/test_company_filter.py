"""Offline company selection: no browser or employer calls."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import direct_apply
from modules.generic_inputs import load_jobs


class CompanyFilterTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / 'jobs.json'
        self.rows = [
            {'id': 'other', 'url': 'https://example.test/0', 'company': 'Other'},
            {'id': 'a', 'url': 'https://example.test/1', 'company': ' Air Space Intelligence '},
            {'id': 'b', 'url': 'https://example.test/2', 'company': 'AIR SPACE INTELLIGENCE'},
            {'id': 'similar', 'url': 'https://example.test/3', 'company': 'Air Space Intelligence Labs'},
            {'id': 'missing', 'url': 'https://example.test/4', 'original_company_names': ['Air Space Intelligence']},
            {'id': 'invalid', 'url': 'https://example.test/5', 'company': {'name': 'Air Space Intelligence'}},
        ]
        self.source.write_text(json.dumps({'jobs': self.rows}))

    def test_exact_match_before_limit_preserves_input(self):
        before = self.source.read_bytes()
        jobs = load_jobs([self.source], company=' air space intelligence ')
        self.assertEqual([j['id'] for j in jobs], ['a', 'b'])
        self.assertEqual(load_jobs([self.source], company='Air Space Intelligence', limit=1)[0]['id'], 'a')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(len(load_jobs([self.source])), len(self.rows))

    def test_role_intersection_and_empty_selection(self):
        jobs = load_jobs([self.source], company='Air Space Intelligence', selected_roles=['b'])
        self.assertEqual([j['id'] for j in jobs], ['b'])
        for company, roles in [('Absent', []), ('Air Space Intelligence', ['other'])]:
            with self.subTest(company=company, roles=roles), self.assertRaisesRegex(ValueError, 'No jobs match company'):
                load_jobs([self.source], company=company, selected_roles=roles)
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            load_jobs([self.source], company='  ')

    def test_deduplication_and_role_alias_are_preserved(self):
        self.source.write_text(json.dumps({'jobs': [*self.rows, {**self.rows[1], 'id': 'alias'}]}))
        jobs = load_jobs([self.source], company='Air Space Intelligence', selected_roles=['alias'])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['id'], 'a')
        self.assertIn('alias', jobs[0]['aliases'])

    def test_full_input_still_validated(self):
        self.source.write_text(json.dumps({'jobs': [*self.rows, {'company': 'Other'}]}))
        with self.assertRaisesRegex(ValueError, 'url string'):
            load_jobs([self.source], company='Air Space Intelligence')

    def test_cli_routes_only_selected_company(self):
        with patch('modules.submit_runner.run_submissions', return_value={'jobs': [{'status': 'applied'}]}) as runner, redirect_stdout(StringIO()):
            code = direct_apply.main(['submit', '--urls-file', str(self.source),
                '--company', 'Air Space Intelligence', '--limit', '1', '--workers', '1'])
        self.assertEqual(code, 0)
        self.assertEqual([j['id'] for j in runner.call_args.args[0]], ['a'])

    def test_cli_errors_never_start_runner(self):
        for source, company in [(['--urls-file', str(self.source)], 'Absent'),
                                (['--urls-file', str(self.source)], ' '),
                                (['--resume', str(Path(self.tmp.name) / 'run')], 'Air Space Intelligence')]:
            with self.subTest(source=source, company=company), patch('modules.submit_runner.run_submissions') as runner, redirect_stderr(StringIO()):
                code = direct_apply.main(['submit', *source, '--company', company])
                self.assertEqual(code, 2)
                runner.assert_not_called()
