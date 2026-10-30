"""Local history/tracker tests; never open or submit employer applications."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

from modules.direct_careers_apply import write_json
from modules.search_history import file_lock
from modules.submission_tracking import job_url, publish, publish_checkpoint
from modules.submit_state import SubmitRun
from modules.generic_inputs import load_jobs

URL = 'https://jobs.ashbyhq.com/example/11111111-1111-4111-8111-111111111111'
OTHER = 'https://jobs.lever.co/example/22222222-2222-4222-8222-222222222222'


class SubmissionTrackingTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root/'config'; self.config.mkdir()
        self.history = self.root/'history'
        self.source = self.root/'roles.json'; self.page = self.root/'roles.html'
        self.roles = {'stage': 'verified_roles', 'records': [
            {'id': 'role:one', 'career_url': URL, 'title': 'First', 'verified_at': '2026-10-15T00:00:00Z'},
            {'id': 'role:two', 'career_url': OTHER, 'title': 'Second', 'verified_at': '2026-10-15T00:00:00Z'},
            {'id': 'role:three', 'career_url': 'https://careers.example.com/jobs/3', 'title': 'Third'}]}
        write_json(self.source, self.roles)
        cards = ''.join('<article class="role" data-search="'+r['title'].lower()+'"><div><h3><a href="'+r['career_url']+'">'+r['title']+'</a></h3></div></article>' for r in self.roles['records'])
        self.page.write_text('<!doctype html><html><body><div class="filters"><input id="query"><select id="tier"><option value="">All</option></select></div><p id="count"></p><section data-group="1">'+cards+'</section><script>function filter(){for(const r of document.querySelectorAll(".role"))r.hidden=!r.dataset.search.includes(document.querySelector("#query").value.toLowerCase())}</script></body></html>')
        self.settings = {'enabled': True, 'history_dir': str(self.history), 'run_roots': [str(self.root/'runs')],
                         'tracker_lock': str(self.root/'render.lock'), 'role_reviews': [{'input': str(self.source), 'page': str(self.page)}]}
        write_json(self.config/'submission_tracking.json', self.settings)

    def snapshot(self, name='one', status='submission_uncertain', url=URL, at='2026-10-22T00:00:00Z'):
        directory = self.root/'custom'/name; directory.mkdir(parents=True, exist_ok=True)
        return {'run_id': name, 'run_dir': str(directory), 'updated_at': at, 'options': {'api_key': 'SECRET'},
                'jobs': [{'id': name, 'url': url, 'title': 'First', 'company': 'Example', 'status': status,
                          'stage': 'confirmation', 'attempts': 1, 'updated_at': at}]}

    def test_all_run_attempts_preserved_and_confirmed_result_dominates(self):
        publish(self.snapshot('old'), config_dir=self.config)
        publish(self.snapshot('confirmed', 'applied'), config_dir=self.config)
        result = publish(self.snapshot('later', 'failed_before_submit', at='2026-10-23T00:00:00Z'), config_dir=self.config)
        job = result['by_url'][URL]
        self.assertEqual(job['status'], 'applied'); self.assertTrue(job['has_uncertain_attempts'])
        self.assertEqual(len(job['attempts']), 3); self.assertTrue(job['exclude_from_remaining'])
        self.assertNotIn('SECRET', (self.history/'history.js').read_text())

    def test_reconciliation_replaces_same_run_without_erasing_other_runs(self):
        publish(self.snapshot(), config_dir=self.config)
        publish(self.snapshot('two'), config_dir=self.config)
        result = publish(self.snapshot(status='applied', at='2026-10-23T00:00:00Z'), config_dir=self.config)
        self.assertEqual(result['runs'][str((self.root/'custom/one').resolve())]['jobs'][0]['status'], 'applied')
        self.assertEqual(len(result['by_url'][URL]['attempts']), 2)
        # Replaying an old progress file cannot downgrade this run's checkpoint.
        result = publish(self.snapshot(), config_dir=self.config)
        self.assertEqual(result['by_url'][URL]['status'], 'applied')

    def test_url_matching_preserves_distinct_postings_and_filters_test_hosts(self):
        self.assertEqual(job_url(URL+'/application?utm_source=x'), URL)
        self.assertEqual(job_url(OTHER+'/apply?source=x'), OTHER)
        self.assertNotEqual(job_url(URL), job_url(OTHER))
        self.assertEqual(job_url('https://jobs.example.test/job/1'), '')
        self.assertEqual(job_url('https://user:secret@example.com/job/1'), '')
        self.assertNotEqual(job_url('https://example.com/job?id=1'), job_url('https://example.com/job?id=2'))

    def test_exports_preserve_source_and_filter_only_possibly_submitted(self):
        source = self.source.read_bytes()
        publish(self.snapshot(status='applied'), config_dir=self.config)
        publish(self.snapshot('two', 'awaiting_manual_submit', OTHER), config_dir=self.config)
        annotated = json.loads(self.source.with_name('roles-with-submissions.json').read_text())
        remaining = json.loads(self.source.with_name('roles-remaining.json').read_text())
        self.assertEqual(self.source.read_bytes(), source)
        self.assertEqual([r['id'] for r in remaining['records']], ['role:two', 'role:three'])
        self.assertEqual(annotated['records'][0]['verified_at'], self.roles['records'][0]['verified_at'])
        self.assertEqual(self.page.read_text().count('jobrobo-submission-tracking:start'), 1)
        self.assertIn('runs.html', (self.history/'history.js').read_text())
        self.assertEqual(len(self.source.with_name('roles-remaining.txt').read_text().splitlines()), 2)

    def test_corrupt_backfill_is_visible_and_does_not_erase_history(self):
        publish(self.snapshot(), config_dir=self.config)
        bad = self.root/'runs/bad/progress.json'; bad.parent.mkdir(parents=True); bad.write_text('{broken')
        result = publish(config_dir=self.config)
        self.assertEqual(result['by_url'][URL]['status'], 'submission_uncertain')
        self.assertEqual(len(result['warnings']), 1)

    def test_busy_reporting_lock_retains_custom_checkpoint_for_next_refresh(self):
        self.history.mkdir()
        progress = self.snapshot(); progress['options']['config_dir'] = str(self.config)
        with file_lock(self.history/'history.lock'):
            publish_checkpoint(progress)  # Must not affect submission state.
        result = publish(config_dir=self.config)
        self.assertEqual(result['by_url'][URL]['status'], 'submission_uncertain')

    def test_submit_state_automatically_publishes_progress_in_custom_run_directory(self):
        jobs = load_jobs(url=URL)
        run = SubmitRun(self.root/'outside-default-runs', jobs=jobs, options={'config_dir': str(self.config)})
        try:
            run.update(jobs[0], status='submitting', stage='waiting_for_confirmation')
            index = json.loads((self.history/'history.json').read_text())
            self.assertEqual(index['by_url'][URL]['status'], 'submission_uncertain')
            run.update(jobs[0], status='applied', stage='confirmed')
            index = json.loads((self.history/'history.json').read_text())
            self.assertEqual(index['by_url'][URL]['status'], 'applied')
        finally:
            run.close()

    def test_dashboard_escapes_job_titles(self):
        progress = self.snapshot(); progress['jobs'][0]['title'] = '<script>alert(1)</script>'
        publish(progress, config_dir=self.config)
        self.assertNotIn('<script>alert(1)', (self.history/'runs.html').read_text())
        self.assertNotIn('<script>alert(1)', (self.history/'history.js').read_text())

    @skipUnless(os.getenv('JOBROBO_PLAYWRIGHT_TESTS') == '1', 'Opt-in isolated local tracker browser')
    def test_tracker_filters_links_and_search_compose(self):
        from playwright.sync_api import sync_playwright
        publish(self.snapshot(status='applied'), config_dir=self.config)
        publish(self.snapshot('two', 'submission_uncertain', OTHER), config_dir=self.config)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
            page = browser.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.page.as_uri())
            self.assertEqual(page.locator('.role:visible').count(), 1)
            page.select_option('#submission-filter', 'all'); self.assertEqual(page.locator('.role:visible').count(), 3)
            page.select_option('#submission-filter', 'submitted'); self.assertEqual(page.locator('.role:visible').count(), 1)
            page.select_option('#submission-filter', 'uncertain'); self.assertEqual(page.locator('.role:visible').count(), 1)
            page.select_option('#submission-filter', 'status:submission_uncertain'); self.assertEqual(page.locator('.role:visible').count(), 1)
            page.fill('#query', 'first'); self.assertEqual(page.locator('.role:visible').count(), 0)
            page.select_option('#submission-filter', 'all'); self.assertEqual(page.locator('.role:visible').count(), 1)
            self.assertEqual(page.get_by_role('link', name='All submit runs').count(), 1)
            self.assertIn('needs-review.json', page.locator('a', has_text='Inspect uncertain outcome').get_attribute('href'))
            self.assertEqual(errors, [])
            browser.close()
