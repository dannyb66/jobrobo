"""Regressions for observed false skips and nonterminal detail timeouts."""
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from selenium.common.exceptions import TimeoutException
from test_search_runner import extract_functions, spec


class EligibilityRegressionTests(unittest.TestCase):
    def test_clearance_service_names_and_negations_are_allowed(self):
        from modules.job_pipeline.careers import clearance_required
        for text in ['Google Cloud Secret Manager and secrets management.', 'FDA clearance for a medical device.',
                     'No security clearance required.', 'Security clearance is not required.',
                     'We do not require a polygraph.', 'No active TS/SCI clearance is needed.',
                     "Security clearance isn't required.", 'Security clearance: None.',
                     'Security clearance preferred, not required.']:
            with self.subTest(text=text):self.assertFalse(clearance_required(text))

    def test_explicit_clearances_and_polygraph_requirements_are_rejected(self):
        from modules.job_pipeline.careers import clearance_required
        for text in ['Active security clearance required.', 'Must hold a Top Secret clearance.',
                     'Must be eligible to obtain TS/SCI clearance.', 'Must pass a polygraph examination.',
                     'No security clearance required, but must pass a polygraph.']:
            with self.subTest(text=text):self.assertTrue(clearance_required(text))

    def test_experience_has_no_twelve_year_cutoff_and_ignores_company_age(self):
        from modules.job_pipeline.careers import required_experience_years
        for text, expected in [('15+ years of engineering experience.',15),
                ('Our company has operated for 20 years.',0), ('We have 20 years of experience.',0),
                ('At least 8 years building production software.',8), ('3–5 years of software experience.',3),
                ('Experience: 10 years required.',10), ('No numeric requirement.',0),
                ('Founded 25 years ago. At least 5 years of experience required.',5)]:
            with self.subTest(text=text):self.assertEqual(required_experience_years(text),expected)

    def test_company_verification_uses_the_same_clearance_and_experience_rules(self):
        from modules.job_pipeline.careers import evaluate_role
        from test_job_pipeline_careers import CanonicalGateTests, config
        fixture=CanonicalGateTests()
        for text,blocked in [('Google Cloud Secret Manager and secrets management.',False),
                             ('No security clearance required.',False),('Active security clearance required.',True)]:
            with self.subTest(text=text):
                result=evaluate_role(fixture.role(descriptionPlain=text),config())
                self.assertEqual('security_clearance_required' in result['exclusion_reasons'],blocked)
        result=evaluate_role(fixture.role(descriptionPlain='15 years of engineering experience.'),config(current_experience=10))
        self.assertIn('experience_excluded',result['exclusion_reasons'])
        result=evaluate_role(fixture.role(descriptionPlain='Our company has operated for 20 years. 5 years of experience required.'),config(current_experience=5))
        self.assertNotIn('experience_excluded',result['exclusion_reasons'])

    def description_namespace(self, text, years=-1):
        ns=dict(driver=SimpleNamespace(find_elements=lambda *a:[object()]),
                WebDriverWait=lambda *a:SimpleNamespace(until=lambda condition:text),
                bad_words=[],security_clearance=False,did_masters=False,current_experience=years,
                print_lg=Mock(),extract_years_of_experience=Mock(side_effect=ValueError('unexpected parsing')))
        extract_functions(ns,'get_job_description')
        return ns

    def test_disabled_experience_filter_does_not_parse_or_reject_fifteen_year_jd(self):
        ns=self.description_namespace('15 years of engineering experience. Google Cloud Secret Manager.')
        self.assertFalse(ns['get_job_description']()[2])
        ns['extract_years_of_experience'].assert_not_called()

    def test_experience_error_is_not_misclassified_as_missing_description(self):
        ns=self.description_namespace('5 years of engineering experience.',years=4)
        result=ns['get_job_description']()
        self.assertTrue(result[2])
        self.assertEqual(result[3],'Experience parsing failed')
        self.assertIn('ValueError',result[4])

    def test_bot_wrapper_uses_safe_shared_experience_parser(self):
        ns={'print_lg':Mock(),'re':re,'re_experience':re.compile(r'(\d+)\s+years?',re.I)}
        extract_functions(ns,'extract_years_of_experience')
        self.assertEqual(ns['extract_years_of_experience']('15 years of engineering experience.'),15)
        self.assertEqual(ns['extract_years_of_experience']('Our company has operated for 20 years.'),0)


class DetailRecoveryTests(unittest.TestCase):
    def test_reselects_same_job_once_then_recovers(self):
        from modules.linkedin_job_details import wait_for_modern_details
        browser=SimpleNamespace()
        reselect=Mock()
        good={'id':'123','company':'Example'}
        wait=Mock(side_effect=[SimpleNamespace(until=Mock(side_effect=TimeoutException())),
                               SimpleNamespace(until=Mock(return_value=good))])
        self.assertEqual(wait_for_modern_details(browser,'123',reselect=reselect,wait_factory=wait),good)
        reselect.assert_called_once_with()
        self.assertEqual(wait.call_count,2)

    def test_readiness_recovery_preserves_the_selected_job_identity(self):
        from modules.linkedin_job_details import wait_for_modern_details
        from test_linkedin_job_details import DetailBrowser
        browser=DetailBrowser('123')
        browser.label.children['ancestor::a[1]'][0].attrs['componentkey']='old-binding-999'
        count=[]
        def wait_factory(driver,timeout):
            def until(predicate):
                count.append(1)
                value=predicate(driver)
                if not value:raise TimeoutException()
                return value
            return SimpleNamespace(until=until)
        def reselect():browser.label.children['ancestor::a[1]'][0].attrs['componentkey']='fresh-binding-123'
        value=wait_for_modern_details(browser,'123',reselect=reselect,wait_factory=wait_factory)
        self.assertEqual(value['id'],'123')
        self.assertEqual(len(count),2)

    def test_exhausted_wait_has_stage_traceback_and_job_bound_diagnostics(self):
        from modules.linkedin_job_details import wait_for_modern_details, JobDetailsUnavailable
        browser=SimpleNamespace(current_url='https://www.linkedin.com/jobs/search-results/?currentJobId=123',
                                find_elements=Mock(return_value=[]),save_screenshot=Mock(return_value=True))
        wait=Mock(return_value=SimpleNamespace(until=Mock(side_effect=TimeoutException())))
        with TemporaryDirectory() as directory:
            with self.assertRaises(JobDetailsUnavailable) as raised:
                wait_for_modern_details(browser,'123',reselect=Mock(),wait_factory=wait,diagnostics_dir=directory)
            details=raised.exception.diagnostics
            self.assertEqual(details['stage'],'job_details_ready')
            self.assertEqual(details['job_id'],'123')
            self.assertEqual(details['attempts'],2)
            evidence=json.loads(Path(details['report_path']).read_text())
            self.assertIn('TimeoutException',evidence['traceback'])
            self.assertTrue(evidence['predicate_error'])

    def test_runner_leaves_timeout_job_pending_and_can_resume_without_duplicate_application(self):
        from modules.linkedin_job_details import JobDetailsUnavailable
        from test_search_runner import SearchRunnerTests
        harness=SearchRunnerTests();harness.setUp()
        try:
            first,second=spec('timeout'),spec('healthy')
            manifest=harness.manifest([first,second],{'timeout':[['1']],'healthy':[['2']]})
            original=harness.namespace['get_job_main_details']
            def details(job,*args):
                if job.job_id=='1':raise JobDetailsUnavailable('123',{'stage':'job_details_ready','job_id':'1'})
                return original(job,*args)
            harness.namespace['get_job_main_details']=details
            harness.execute(manifest)
            self.assertEqual(manifest.query('timeout')['status'],'pending')
            self.assertEqual(manifest.query('timeout')['jobs']['1']['status'],'in_progress')
            self.assertNotIn('1',manifest.processed_ids())
            self.assertEqual(manifest.query('healthy')['jobs']['2']['status'],'applied')
            harness.namespace['get_job_main_details']=original
            harness.execute(manifest)
            self.assertEqual(manifest.query('timeout')['jobs']['1']['status'],'applied')
            self.assertEqual(harness.events.count('Submit application'),2)
        finally:harness.doCleanups()


if __name__=='__main__':unittest.main()
