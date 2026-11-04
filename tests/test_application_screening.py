"""Employer screening is deterministic; pre-upload prose never bypasses upload."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from modules.application_screening import employer_screening_answer, draft_evidence_path
from modules.linkedin_easy_apply import MissingApplicationAnswer
from modules.resume_upload import ResumeUploadError


ELIGIBILITY = 'If offered a position with Crazy Maple Studio, would you be legally eligible to begin employment immediately?*'
RELATIONSHIPS = 'Do you have any relatives or personal relationships with current employees, contractors, or vendors of Crazy Maple Studio? If yes, please provide their name, relationship and department:*'
REFERRAL = 'Were you referred to this position by a current employee? If yes, please provide their name and your relationship to them:*'


class ScreeningTests(unittest.TestCase):
    def settings(self):
        return {'us_citizenship': 'Non-citizen allowed to work for any employer',
                'available_start_date': 'Immediate', 'application_employer_screening_answers': {
                    'Crazy Maple Studio': {'employee_relationships': False,
                        'employee_referral': False, 'previous_application': False, 'previous_employment': False}}}

    def test_eligibility_uses_authorization_and_availability_not_visa(self):
        self.assertEqual(employer_screening_answer(ELIGIBILITY,self.settings()),'Yes')
        with self.assertRaises(MissingApplicationAnswer):
            employer_screening_answer(ELIGIBILITY,{'visa_status':'H-1B approved','require_visa':'No','available_start_date':'Immediate'})
        with self.assertRaises(MissingApplicationAnswer):
            employer_screening_answer(ELIGIBILITY,{**self.settings(),'available_start_date':'2027-01-01'})
        self.assertEqual(employer_screening_answer(ELIGIBILITY,
            {**self.settings(),'application_immediate_employment_eligible':False}),'No')

    def test_relationship_referral_and_prior_history_use_exact_employer_config(self):
        for question in [RELATIONSHIPS,
                'Were you referred to Crazy Maple Studio by an employee? Please provide their name.',
                'Have you previously applied to Crazy Maple Studio or its subsidiaries?',
                'Have you ever been employed by Crazy Maple Studio?']:
            self.assertEqual(employer_screening_answer(question,self.settings()),'No')
        with self.assertRaises(MissingApplicationAnswer):
            employer_screening_answer(RELATIONSHIPS.replace('Crazy Maple Studio','Other Company'),self.settings())

    def test_unconfigured_referral_is_not_the_applicants_name(self):
        with self.assertRaises(MissingApplicationAnswer):
            employer_screening_answer(REFERRAL,{'full_name':'Applicant Name'})
        self.assertIsNone(employer_screening_answer('Your full name',self.settings()))
        self.assertIsNone(employer_screening_answer('Why did you apply for this role?',self.settings()))
        self.assertEqual(employer_screening_answer(REFERRAL,
            {**self.settings(),'_application_employer':'Crazy Maple Studio'}),'No')

    def test_invalid_employer_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            employer_screening_answer(RELATIONSHIPS,{'application_employer_screening_answers':{'Crazy Maple Studio':False}})

    def test_personal_history_is_never_drafted(self):
        from modules.application_drafts import ApplicationDrafts,DraftError
        provider=Mock()
        drafts=ApplicationDrafts('unused.pdf',None,'test','Engineer','Employer','Exact JD','',provider=provider)
        for question in [RELATIONSHIPS,REFERRAL,'Have you previously applied to this company?']:
            with self.assertRaises(DraftError):
                drafts.answer(question)
        provider.assert_not_called()

    def test_prose_details_preserved_for_text_and_boolean_for_choice(self):
        settings={'application_employer_screening_answers':{'Crazy Maple Studio':{
            'employee_relationships':'Yes: Example Person, sibling, Engineering'}}}
        self.assertIn('Example Person',employer_screening_answer(RELATIONSHIPS,settings))
        self.assertEqual(employer_screening_answer(RELATIONSHIPS,settings,choice=True),'Yes')

    def test_source_evidence_is_available_before_upload(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.docx';source.write_bytes(b'fixture')
            self.assertEqual(draft_evidence_path(None,False,source,None),source.resolve())
            with self.assertRaises(Exception):
                draft_evidence_path(None,False,None,None)


class EarlyDraftRunnerTests(unittest.TestCase):
    def run_prepare(self, upload_later):
        from test_search_runner import SearchRunnerTests
        h=SearchRunnerTests();h.setUp();self.addCleanup(h.doCleanups)
        source=h.directory/'source.docx';source.write_bytes(b'fixture')
        ns=h.namespace;ns.update(default_resume_docx_path=str(source),ai_descriptive_answers_enabled=True,
            use_AI_for_resume=True,allow_contact_only_easy_apply=False,ResumeUploadError=ResumeUploadError)
        ns['resume_upload_target']=Mock(side_effect=[None,h.modal] if upload_later else [None])
        def upload(*args,**kwargs):
            kwargs['on_attached'](str(source));return True,str(source)
        ns['upload_optimized_resume']=Mock(side_effect=upload)
        answers=[]
        def answer(modal,questions,*args,draft_answer=None,**kwargs):
            answers.append(draft_answer('Describe a relevant project','descriptive',127))
            return set()
        ns['answer_questions']=answer
        def advance(browser,fill,**kwargs):
            fill(h.modal)
            if upload_later:fill(h.modal)
            return h.modal
        ns['advance_to_review']=advance
        drafts=Mock();drafts.answer.return_value='A source-grounded project answer';drafts.artifact_summary.return_value={}
        with patch('modules.application_drafts.ApplicationDrafts',return_value=drafts) as factory, \
                patch('modules.ai.application_drafting.create_drafting_client'), \
                patch('modules.ai.application_drafting.make_drafting_provider'):
            if upload_later:
                result=ns['prepare_easy_apply']('123','Engineer','Exact JD','Bay Area')
                self.assertTrue(result[2])
            else:
                with self.assertRaises(ResumeUploadError):
                    ns['prepare_easy_apply']('123','Engineer','Exact JD','Bay Area')
            self.assertTrue(answers)
            self.assertEqual(factory.call_args_list[0].kwargs['resume_path'],source.resolve())

    def test_draft_before_resume_page_then_upload_continues(self):
        self.run_prepare(True)

    def test_early_draft_does_not_bypass_required_resume_upload(self):
        self.run_prepare(False)


if __name__=='__main__':
    unittest.main()
