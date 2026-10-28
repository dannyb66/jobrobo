"""Preparation safety, binding and dispatch tests. No live employers/providers."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import json
import unittest

from modules.generic_prepare import (canonical_url, extract_job, PreparationResolver,
    generated_resume, preparation_resume_config, fingerprint, NEXT, FINAL, make_question_mapper, record_resume_review)
from modules.external_apply import apply_hosted_application
from modules.external_questions import QuestionResolver


class GenericPreparationTests(unittest.TestCase):
    def test_urls_preserve_job_query_but_remove_attribution(self):
        self.assertEqual(canonical_url('https://example.test/careers/?job_id=42&utm_source=a#form'),
                         'https://example.test/careers?job_id=42')
        self.assertNotEqual(canonical_url('https://example.test/?job=1'), canonical_url('https://example.test/?job=2'))

    def test_url_validation(self):
        for url in ('http://employer.test/job', 'https://user:pass@example.test/job', 'javascript:alert(1)', 'https://example.test/a\nb'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                canonical_url(url)

    def test_extracts_structured_description(self):
        result = extract_job({'job': {'title': 'Staff Engineer', 'hiringOrganization': {'name': 'Test'},
            'description': '<p>Build systems</p><p>Use Python</p>'}})
        self.assertEqual(result['company'], 'Test')
        self.assertEqual(result['description'], 'Build systems\nUse Python')

    def test_config_precedes_ai_and_missing_fact_never_calls_ai(self):
        drafts = Mock()
        resolver = PreparationResolver({'email': 'test@example.test'}, {}, drafts)
        question = {'label': 'Email', 'name': 'email', 'kind': 'text', 'required': True}
        self.assertEqual(resolver.resolve(question, 'generic').value, 'test@example.test')
        self.assertFalse(resolver.resolve({**question, 'label': 'Are you legally authorized to work in the US?', 'name': 'authorization'}, 'generic').resolved)
        drafts.answer.assert_not_called()

    def test_explicit_sponsorship_is_reused_but_not_inferred_from_visa(self):
        q = {'label': 'Will you now or in the future require sponsorship for employment? If so, please explain in detail.',
             'name': 'sponsor', 'kind': 'textarea', 'required': True}
        self.assertEqual(PreparationResolver({'require_visa': 'No'}, {}).resolve(q, 'generic').value, 'No')
        self.assertFalse(PreparationResolver({'visa_status': 'H-1B approved'}, {}).resolve(q, 'generic').resolved)

    def test_common_portal_sponsorship_wordings_use_explicit_config(self):
        resolver = PreparationResolver({'require_visa': 'No'}, {})
        questions = [
            {'label': 'Will you now or in the future require employment visa sponsorship (e.g., H-1B visa) to legally work for our company?', 'name': 'lever_sponsor', 'kind': 'text'},
            {'label': 'Will you require sponsorship for employment now or in the future?', 'name': 'shield_sponsor', 'kind': 'radio', 'options': ['Yes', 'No']},
        ]
        for question in questions:
            with self.subTest(label=question['label']):
                answer = resolver.resolve(question, 'lever')
                self.assertTrue(answer.resolved)
                self.assertEqual(answer.value, 'No')
                self.assertEqual(answer.source, 'candidate_config:require_visa')

    def test_online_discovery_can_truthfully_answer_no_referral_question(self):
        resolver = PreparationResolver({'application_source': 'Web'}, {})
        question = {'label': 'If someone at Solace referred you, please share their name and your connection.',
                    'name': 'referral', 'kind': 'textarea', 'required': True}
        answer = resolver.resolve(question, 'ashby')
        self.assertTrue(answer.resolved)
        self.assertIn('found this opening online', answer.value)
        self.assertIn('no personal referral', answer.value)

    def test_us_authorization_uses_only_explicit_employment_eligibility(self):
        q = {'label': 'Are you legally authorized to work in the US?', 'name': 'auth', 'kind': 'radio', 'options': ['Yes', 'No']}
        self.assertEqual(PreparationResolver({'employment_eligibility_statement': 'Non-citizen allowed to work for any employer'}, {}).resolve(q, 'generic').value, 'Yes')
        self.assertFalse(PreparationResolver({'visa_status': 'H-1B approved', 'citizenship': 'Non-citizen'}, {}).resolve(q, 'generic').resolved)
        self.assertFalse(PreparationResolver({'employment_eligibility_statement': 'Non-citizen allowed to work for any employer'}, {}).resolve({**q, 'label': 'Are you authorized to work in Canada?'}, 'generic').resolved)

    def test_missing_urls_attendance_and_relationships_are_not_generated(self):
        drafts = Mock()
        resolver = PreparationResolver({}, {}, drafts)
        for label in ('Twitter URL', 'Are you able to work on-site three days per week?', 'Describe any family connections at this company'):
            answer = resolver.resolve({'label': label, 'name': 'q', 'kind': 'textarea'}, 'generic')
            self.assertFalse(answer.resolved)
        drafts.answer.assert_not_called()

    def test_plain_current_location_uses_supplied_profile(self):
        resolver = PreparationResolver({'city': 'San Francisco', 'state': 'California', 'country': 'United States'}, {})
        q = {'label': 'Please list your current location✱', 'name': 'location', 'kind': 'text', 'required': True}
        self.assertEqual(resolver.resolve(q, 'lever').value, 'San Francisco, California, United States')

    def test_engineering_experience_threshold_uses_config_and_never_specific_skill_guess(self):
        q = {'label': 'Do you have 4+ years of experience as a full-time engineer?', 'name': 'years', 'kind': 'radio', 'options': ['Yes', 'No']}
        self.assertEqual(PreparationResolver({'years_of_experience': '8'}, {}).resolve(q, 'ashby').value, 'Yes')
        self.assertEqual(PreparationResolver({'years_of_experience': '2'}, {}).resolve(q, 'ashby').value, 'No')
        self.assertFalse(PreparationResolver({}, {}).resolve(q, 'ashby').resolved)
        self.assertFalse(PreparationResolver({'years_of_experience': '8'}, {}).resolve({**q, 'label': 'Do you have 4+ years of experience with Rust?'}, 'ashby').resolved)

    def test_known_city_does_not_establish_office_commitment(self):
        r = PreparationResolver({'city': 'San Francisco', 'country': 'United States'}, {}, Mock())
        q = {'label': 'Are you located in San Francisco or New York City?', 'name': 'city', 'kind': 'radio', 'options': ['Yes', 'No']}
        self.assertEqual(r.resolve(q, 'ashby').value, 'Yes')
        self.assertFalse(r.resolve({**q, 'label': 'Are you willing to work onsite in our San Francisco or New York City office?'}, 'ashby').resolved)

    def test_qualified_authorization_choices_use_exact_supported_facts(self):
        auth = 'Yes, I am currently legally authorized to work in the country where the jobs is located.'
        q = {'label': 'Are you legally authorized to work in the country where the job is located?*', 'name': 'auth',
             'kind': 'select', 'required': True, 'options': [auth, 'No']}
        candidate = {'employment_eligibility_statement': 'Non-citizen allowed to work for any employer', 'require_visa': 'No'}
        resolver = PreparationResolver(candidate, {}, job_country='US')
        self.assertEqual(resolver.resolve(q, 'greenhouse').value, auth)
        self.assertFalse(PreparationResolver(candidate, {}, job_country='CA').resolve(q, 'greenhouse').resolved)
        self.assertFalse(resolver.resolve({**q, 'options': ['Yes, and I hold a security clearance', 'No']}, 'greenhouse').resolved)
        sponsor = 'No, I do not and will not require immigration sponsorship to legally work in the country where the job is located.'
        q.update(label='Will you now or in the future require company sponsorship to retain or extend your work authorization in the country where the job is located?*', options=[sponsor, 'Yes, now', 'Yes, in the future'])
        self.assertEqual(resolver.resolve(q, 'greenhouse').value, sponsor)
        self.assertFalse(PreparationResolver({**candidate, 'require_visa': 'Yes'}, {}, job_country='US').resolve(q, 'greenhouse').resolved)

    def test_attestations_in_radio_options_never_use_ai(self):
        drafts = Mock(); drafts.answer.return_value = 'I have reviewed and confirmed that all the information provided is accurate and complete.'
        resolver = PreparationResolver({}, {}, drafts)
        q = {'label': 'Review', 'name': 'review', 'kind': 'radio', 'required': True, 'options': [drafts.answer.return_value]}
        self.assertFalse(resolver.resolve(q, 'generic').resolved)
        drafts.answer.assert_not_called()

    def test_linkedin_explicit_preparation_routes_without_global_flag(self):
        from types import SimpleNamespace
        from test_search_runner import extract_functions
        ns = {'search_profile': SimpleNamespace(search_state_dir='logs/search_runs'), 'prepare_only_run': False}
        extract_functions(ns, 'prepare_external_application')
        report = {'status': 'prepared', 'blockers': [], 'questions': [], 'resume': {'pdf': '/tmp/test.pdf', 'pdf_sha256': 'test'}}
        with patch('modules.generic_prepare.run_preparations', return_value=[report]) as prepare:
            result = ns['prepare_external_application']('https://example.test/job', '123', 'Staff Engineer', 'JD', 'Test', prepare_only=True)
        self.assertEqual(result.status, 'prepared')
        self.assertNotIn('grounded_resume', prepare.call_args.kwargs)

    def test_grounded_prose_uses_shared_draft_cache_interface(self):
        drafts = Mock(); drafts.answer.return_value = 'I would build a reliable service.'
        resolver = PreparationResolver({}, {}, drafts)
        answer = resolver.resolve({'label': 'Why this role?', 'name': 'motivation', 'kind': 'textarea', 'max_length': 90}, 'generic')
        self.assertEqual(answer.source, 'ai_draft')
        drafts.answer.assert_called_once_with('Why this role?', kind='descriptive', max_length=90)

    def test_ai_failure_and_bad_control_remain_unresolved(self):
        drafts = Mock(); drafts.answer.side_effect = RuntimeError('private key must not escape')
        resolver = PreparationResolver({}, {}, drafts)
        result = resolver.resolve({'label': 'Why this company?', 'name': 'fit', 'kind': 'textarea'}, 'generic')
        self.assertFalse(result.resolved)
        self.assertNotIn('private', result.reason)
        resolver.resolve({'label': 'Pick a skill', 'name': 'choice', 'kind': 'select', 'options': ['Python']}, 'generic')
        self.assertEqual(drafts.answer.call_count, 2)

    def test_ai_choice_must_identify_available_option(self):
        drafts = Mock(); drafts.answer.return_value = 'Python'
        resolver = PreparationResolver({}, {}, drafts)
        q = {'label': 'Which language have you used?', 'name': 'language', 'kind': 'select', 'options': ['Python', 'Go']}
        self.assertEqual(resolver.resolve(q, 'generic').value, 'Python')
        drafts.answer.return_value = 'Ruby'
        self.assertFalse(resolver.resolve(q, 'generic').resolved)

    def test_shared_json_is_used_without_overrides_even_with_legacy_flag(self):
        from modules.config_loader import peek_runtime_config
        with TemporaryDirectory() as tmp:
            defaults, runtime = Path(tmp)/'defaults.json', Path(tmp)/'runtime.json'
            defaults.write_text(json.dumps({'optimization_mode': 'full', 'content_policy': 'grounded', 'source_checks_enabled': True}))
            saved = {'rewrite_all_bullets': True, 'source_checks_enabled': False, 'content_policy': 'synthetic_jd_test',
                     'replace_job_title': True, 'project_bullet_banks': [{'company': 'Test', 'path': 'test.json'}], 'nested': {'keep': True}}
            runtime.write_text(json.dumps(saved)); before = runtime.read_bytes()
            with patch('modules.config_loader.APP_BUNDLE_CONFIG_FILE', defaults), patch('modules.config_loader.RUNTIME_CONFIG_FILE', runtime):
                expected = peek_runtime_config()
                for legacy in (False, True):
                    actual = preparation_resume_config(grounded_resume=legacy)
                    self.assertEqual(actual, expected)
                    actual['nested']['keep'] = False
                    self.assertTrue(preparation_resume_config()['nested']['keep'])
            self.assertEqual(runtime.read_bytes(), before)

    @staticmethod
    def accepted_generator(source, *, strict=False, eligible=True):
        from modules.direct_careers_apply import digest
        def generate(**kwargs):
            root = Path(kwargs['output_root']) / 'run' if strict else Path(kwargs['output_root'])
            root.mkdir(parents=True, exist_ok=True)
            canonical = root/'optimized.pdf'; canonical.write_bytes(b'generated pdf')
            canonical.with_suffix('.docx').write_bytes(b'generated docx')
            selected = root/'resume-job-run.pdf' if strict else canonical
            if strict:
                selected.write_bytes(canonical.read_bytes()); selected.with_suffix('.docx').write_bytes(canonical.with_suffix('.docx').read_bytes())
            report = {'status': 'complete' if strict else 'accepted', 'job_id': kwargs['job_id'],
                      'source_sha256': digest(source), 'output_path': str(canonical), 'format_verification': {'passed': True}}
            if strict: report.update(attachment_path=str(selected), strict_attachment_eligible=eligible)
            path = root/'match-report.json' if strict else canonical.with_suffix('.match_report.json')
            path.write_text(json.dumps(report))
            return str(selected)
        return generate

    def test_standard_optimizer_uses_shared_config_without_preparation_wrapper(self):
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            source = Path(tmp)/'resume.docx'; source.write_bytes(b'source'); pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
            config = {'content_policy': 'grounded', 'source_checks_enabled': True, 'replace_job_title': True, 'nested': {'keep': True}}
            with patch('modules.ai.resume_optimizer.run_resume_optimization', side_effect=self.accepted_generator(source)) as optimize:
                generated_resume({'title': 'Engineer', 'description': 'JD'}, Path(tmp)/'out', source, pdf, config, {})
            self.assertEqual(optimize.call_args.kwargs['runtime_config_override'], config)
            self.assertNotIn('optimizer_instance', optimize.call_args.kwargs)

    def test_optimization_progress_is_visible_and_callback_closes(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            source = Path(tmp)/'resume.docx'; source.write_bytes(b'source')
            pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
            callbacks = []
            accepted = self.accepted_generator(source)
            def generate(**kwargs):
                callbacks.append(kwargs['progress_callback'])
                kwargs['progress_callback']({'event': 'bullets_progress', 'ready': 12, 'total': 47})
                return accepted(**kwargs)
            output = StringIO()
            args = ({'title': 'Engineer', 'description': 'PRIVATE JD'}, Path(tmp)/'out', source, pdf, {}, {})
            with redirect_stdout(output):
                generated_resume(*args, generate=generate)
                generated_resume(*args, generate=generate)
            self.assertEqual(len(callbacks), 1)
            self.assertTrue(callbacks[0].closed.is_set())
            self.assertIn('Starting resume optimization', output.getvalue())
            self.assertIn('Bullet candidates ready: 12/47', output.getvalue())
            self.assertIn('ready for upload', output.getvalue())
            self.assertIn('Reusing verified cached PDF', output.getvalue())
            self.assertNotIn('PRIVATE JD', output.getvalue())

    def test_strict_shared_mode_accepts_alias_and_rechecks_cached_manifest(self):
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume') as legacy_format, \
                patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True) as verify:
            source = Path(tmp)/'resume.docx'; source.write_bytes(b'source'); pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
            job = {'title': 'Engineer', 'description': 'JD'}
            config = {'content_policy': 'synthetic_jd_test', 'source_checks_enabled': False, 'rewrite_all_bullets': True, 'replace_job_title': True}
            optimize = Mock(side_effect=self.accepted_generator(source, strict=True))
            args = (job, Path(tmp)/'out', source, pdf, config, {})
            first = generated_resume(*args, generate=optimize)
            self.assertEqual(Path(first['report']).name, 'match-report.json')
            self.assertEqual(Path(first['pdf']).name, 'resume-job-run.pdf')
            self.assertEqual(verify.call_args.kwargs['expected_config'], config)
            self.assertFalse(verify.call_args.kwargs['expected_source_checks_enabled'])
            self.assertEqual(verify.call_args.kwargs['expected_jd'], 'JD')
            self.assertEqual(verify.call_args.kwargs['expected_source_docx'], source)
            self.assertEqual(generated_resume(*args, generate=optimize), first)
            self.assertEqual(verify.call_count, 2); optimize.assert_called_once(); legacy_format.assert_not_called()
            verify.return_value = False
            with self.assertRaisesRegex(ValueError, 'Cached strict'):
                generated_resume(*args, generate=optimize)
            optimize.assert_called_once()

    def test_partial_or_unverified_strict_outputs_never_become_upload_bindings(self):
        for eligible, verified in ((False, True), (True, False)):
            with self.subTest(eligible=eligible, verified=verified), TemporaryDirectory() as tmp, \
                    patch('modules.resume_all_bullets.verify_strict_attachment', return_value=verified):
                source = Path(tmp)/'resume.docx'; source.write_bytes(b'source'); pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
                root = Path(tmp)/'out'
                with self.assertRaises(ValueError):
                    generated_resume({'title': 'Engineer', 'description': 'JD'}, root, source, pdf,
                        {'rewrite_all_bullets': True, 'source_checks_enabled': False, 'content_policy': 'synthetic_jd_test'}, {},
                        generate=self.accepted_generator(source, strict=True, eligible=eligible))
                self.assertFalse((root/'binding.json').exists())

    def test_old_preparation_cache_is_not_reused_by_shared_engine(self):
        from modules.direct_careers_apply import digest
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            source = Path(tmp)/'resume.docx'; source.write_bytes(b'source'); pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
            job = {'title': 'Engineer', 'description': 'JD'}; config = {'content_policy': 'grounded', 'source_checks_enabled': True}
            root = Path(tmp)/'out'; root.mkdir()
            old_pdf = root/'old.pdf'; old_pdf.write_bytes(b'old pdf')
            old_docx = old_pdf.with_suffix('.docx'); old_docx.write_bytes(b'old docx')
            old_report = old_pdf.with_suffix('.match_report.json'); old_report.write_text('{}')
            old = {'input_hash': fingerprint({'job': job, 'docx': digest(source), 'pdf': digest(pdf), 'config': config}),
                   'format_verification': {'passed': True}}
            for name, path in [('pdf', old_pdf), ('docx', old_docx), ('report', old_report)]:
                old[name], old[name+'_sha256'] = str(path), digest(path)
            (root/'binding.json').write_text(json.dumps(old))
            generate = Mock(side_effect=self.accepted_generator(source))
            result = generated_resume(job, root, source, pdf, config, {}, generate=generate)
            generate.assert_called_once(); self.assertNotEqual(result['pdf'], str(old_pdf))

    def test_concurrent_generation_not_repeated(self):
        from modules.search_history import file_lock
        with TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.docx'; source.write_bytes(b'source')
            pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
            output = Path(tmp)/'out'; output.mkdir()
            generate = Mock()
            with file_lock(output/'generation.lock'), self.assertRaises(BlockingIOError):
                generated_resume({'title': 'Engineer', 'description': 'JD'}, output, source, pdf, {}, {}, generate=generate)
            generate.assert_not_called()

    def test_hosted_prepare_only_ignores_submit_review_callback(self):
        import test_external_apply as hosted
        with TemporaryDirectory() as tmp:
            pdf = Path(tmp)/'resume.pdf'; pdf.write_bytes(b'test')
            browser = hosted.Browser()
            review, checkpoint = Mock(return_value='Submit application'), Mock()
            result = apply_hosted_application(browser, browser.url,
                {'full_name': 'Test Applicant', 'email': 'test@example.test', 'phone': '5550100'}, pdf,
                verify_pdf=lambda _: True, official_role_urls=[browser.url], review=review, on_status=checkpoint, prepare_only=True)
            self.assertEqual(result.status, 'prepared')
            self.assertEqual(browser.clicks, 0)
            review.assert_not_called(); checkpoint.assert_not_called()

    def test_cli_exposes_no_submission_option(self):
        from direct_apply import parser
        args = parser().parse_args(['prepare', '--url', 'https://example.test/job'])
        self.assertFalse(hasattr(args, 'execute'))
        self.assertFalse(hasattr(args, 'max_applications'))

    def test_label_mapper_accepts_only_observed_text_and_caches(self):
        client = Mock()
        client.chat.completions.create.return_value.choices = [Mock(message=Mock(content=json.dumps({'mappings': [
            {'name': 'opaque', 'question': 'Why this employer?'}]})))]
        mapper = make_question_mapper(client, 'test-model')
        fields = [{'visible': True, 'type': 'textarea', 'name': 'opaque', 'question': 'opaque', 'context_text': 'Why this employer? *'}]
        mapper(fields)
        self.assertEqual(fields[0]['question'], 'Why this employer?')
        fields[0]['question'] = 'opaque'; mapper(fields)
        self.assertEqual(client.chat.completions.create.call_count, 1)
        bad = make_question_mapper(client, 'test-model')
        fields[0].update(question='opaque', context_text='A completely different question')
        bad(fields)
        self.assertEqual(fields[0]['question'], 'opaque')

    def test_accepted_resume_cache_and_tamper_invalidation(self):
        from modules.direct_careers_apply import digest
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            source = Path(tmp)/'resume.docx'; source.write_bytes(b'original docx')
            pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'original pdf')
            calls = []
            def generate(**kwargs):
                calls.append(kwargs)
                output = Path(kwargs['output_root'])/'optimized.pdf'; output.parent.mkdir(exist_ok=True)
                output.write_bytes(b'generated pdf'); output.with_suffix('.docx').write_bytes(b'generated docx')
                output.with_suffix('.match_report.json').write_text(json.dumps({'status': 'accepted', 'job_id': kwargs['job_id'],
                    'source_sha256': digest(source), 'output_path': str(output)}))
                return str(output)
            args = ({'title': 'Staff Engineer', 'description': 'JD'}, Path(tmp)/'out', source, pdf,
                    {'content_policy': 'grounded', 'source_checks_enabled': True}, {})
            first = generated_resume(*args, generate=generate)
            self.assertFalse(first['visual_review_required'])
            self.assertEqual(generated_resume(*args, generate=generate), first)
            self.assertEqual(len(calls), 1)
            # Existing cache entries must resume without another paid rewrite
            # or a review marker left over from the former gate.
            binding_path = Path(tmp)/'out'/'binding.json'
            binding_path.write_text(json.dumps({**first, 'visual_review_required': True}))
            self.assertEqual(generated_resume(*args, generate=generate), first)
            self.assertFalse(json.loads(binding_path.read_text())['visual_review_required'])
            self.assertEqual(len(calls), 1)
            Path(first['docx']).write_bytes(b'tampered')
            generated_resume(*args, generate=generate)
            self.assertEqual(len(calls), 2)
            report = Path(tmp)/'report.json'; report.write_text(json.dumps({'resume': first}))
            record_resume_review(report, first['pdf_sha256'])
            with self.assertRaises(ValueError):
                record_resume_review(report, 'wrong-hash')


if __name__ == '__main__':
    unittest.main()
