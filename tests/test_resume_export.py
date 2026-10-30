"""Local saved-artifact export checks; no employer or provider requests."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import direct_apply
from modules.resume_export import copy_resume


URL = 'https://jobs.lever.co/shieldai/bb87c070-f5bb-41ea-80e5-76e6f7f07a4e'
NAME = 'Danny_Basavaraju_Resume_Shield_AI_Senior_Staff__job-123.pdf'


class ResumeExportTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'config'
        self.config.mkdir()
        self.runs = self.root / 'runs'
        self.downloads = self.root / 'Downloads'
        self.write(self.config / 'submission_tracking.json', {
            'run_roots': [str(self.runs)], 'history_dir': str(self.root / 'history')})

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def run_fixture(self, name='latest', started='2026-10-30T01:00:00Z', updated=None,
                    data=b'%PDF-1.7\noptimized resume', url=URL):
        directory = self.runs / name
        directory.mkdir(parents=True)
        pdf = directory / 'internal-resume.pdf'
        pdf.write_bytes(data)
        sha = hashlib.sha256(data).hexdigest()
        report = directory / 'preparation' / 'report.json'
        self.write(report, {'url': url, 'resume': {'pdf': str(pdf), 'pdf_sha256': sha},
                            'attachment': {'name': NAME, 'sha256': sha}})
        self.write(directory / 'progress.json', {'run_id': name, 'started_at': started,
            'updated_at': updated or started, 'jobs': [{'url': url, 'status': 'submission_uncertain',
                'resume_sha256': sha, 'preparation_report': str(report)}]})
        return directory, pdf, report

    def export(self, **kwargs):
        return copy_resume(URL + '/apply?source=example', config_dir=self.config,
                           destination=self.downloads, **kwargs)

    def test_latest_run_uses_start_time_and_recorded_name(self):
        self.run_fixture('old', '2026-10-29T01:00:00Z', '2026-10-31T00:00:00Z', data=b'%PDF-1.7\nold')
        _, pdf, _ = self.run_fixture()
        result = self.export()
        self.assertEqual(result['run_id'], 'latest')
        self.assertEqual(result['application_status'], 'submission_uncertain')
        self.assertEqual(Path(result['destination']).name, NAME)
        self.assertEqual(Path(result['destination']).read_bytes(), pdf.read_bytes())
        self.assertEqual(list(self.downloads.iterdir()), [self.downloads / NAME])

    def test_explicit_run_and_missing_latest_do_not_fall_back(self):
        old, _, _ = self.run_fixture('old', '2026-10-29T01:00:00Z')
        latest, pdf, _ = self.run_fixture()
        pdf.unlink()
        with self.assertRaises(FileNotFoundError):
            self.export()
        self.assertFalse(self.downloads.exists())
        self.assertEqual(self.export(run_dir=old)['run_id'], 'old')
        with self.assertRaises(FileNotFoundError):
            self.export(run_dir=latest / 'absent')

    def test_latest_pending_run_does_not_fall_back(self):
        self.run_fixture('old', '2026-10-29T01:00:00Z')
        directory, _, _ = self.run_fixture()
        path = directory / 'progress.json'
        data = json.loads(path.read_text())
        del data['jobs'][0]['preparation_report']
        self.write(path, data)
        with self.assertRaisesRegex(ValueError, 'no saved resume preparation report'):
            self.export()

    def test_collisions_preserve_existing_and_identical_copy_is_reused(self):
        self.run_fixture()
        self.downloads.mkdir()
        (self.downloads / NAME).write_bytes(b'keep this')
        first = self.export()
        self.assertTrue(first['copied'])
        self.assertTrue(first['destination'].endswith(' (1).pdf'))
        self.assertEqual((self.downloads / NAME).read_bytes(), b'keep this')
        second = self.export()
        self.assertFalse(second['copied'])
        self.assertEqual(first['destination'], second['destination'])

    def test_rejects_hash_mismatches_and_unrelated_report(self):
        directory, pdf, report = self.run_fixture()
        original = json.loads(report.read_text())
        pdf.write_bytes(b'%PDF-1.7\ntampered')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.export()
        pdf.write_bytes(b'%PDF-1.7\noptimized resume')
        for field in ('attachment', 'resume'):
            changed = json.loads(json.dumps(original))
            changed[field]['sha256' if field == 'attachment' else 'pdf_sha256'] = '0' * 64
            self.write(report, changed)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.export()
        changed = {**original, 'url': URL + '-other'}
        self.write(report, changed)
        with self.assertRaisesRegex(ValueError, 'does not match the requested job'):
            self.export()
        self.assertFalse(self.downloads.exists())

    def test_rejects_unsafe_names_and_skips_destination_symlinks(self):
        _, pdf, report = self.run_fixture()
        original = json.loads(report.read_text())
        for name in ('../escape.pdf', 'bad\\name.pdf', 'bad\nname.pdf', 'resume.docx', ''):
            changed = {**original, 'attachment': {**original['attachment'], 'name': name}}
            self.write(report, changed)
            with self.assertRaisesRegex(ValueError, 'filename'):
                self.export()
        self.write(report, original)
        self.downloads.mkdir()
        (self.downloads / NAME).symlink_to(pdf)
        self.assertTrue(self.export()['destination'].endswith(' (1).pdf'))

    def test_cli_routes_copy_and_returns_validation_error(self):
        self.run_fixture()
        args = ['copy-resume', '--url', URL, '--destination', str(self.downloads),
                '--config-dir', str(self.config)]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(direct_apply.main(args), 0)
        self.assertTrue(Path(json.loads(output.getvalue())['destination']).is_file())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(direct_apply.main([*args, '--url', URL + '-other']), 2)

    def test_custom_run_is_discovered_from_history(self):
        directory, _, _ = self.run_fixture()
        self.write(self.config / 'submission_tracking.json', {
            'run_roots': [], 'history_dir': str(self.root / 'history')})
        self.write(self.root / 'history' / 'history.json', {'runs': {'custom': {'run_dir': str(directory)}}})
        self.assertEqual(self.export()['run_id'], 'latest')

    def test_run_hash_mismatch_and_non_pdf_are_rejected(self):
        directory, _, _ = self.run_fixture()
        path = directory / 'progress.json'
        data = json.loads(path.read_text())
        data['jobs'][0]['resume_sha256'] = '0' * 64
        self.write(path, data)
        with self.assertRaisesRegex(ValueError, 'saved run'):
            self.export()
        other, _, _ = self.run_fixture('non-pdf', '2026-10-31T00:00:00Z', data=b'not a PDF')
        with self.assertRaisesRegex(ValueError, 'PDF header'):
            self.export(run_dir=other)
