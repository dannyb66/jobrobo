"""Regression cases from the November 2 Easy Apply failures; never submit."""
import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modules.linkedin_form_fields import multi_select_values, fill_multi_select_groups
from modules.resume_titles import normalized_role_title


class QualificationSelectionTests(unittest.TestCase):
    def test_same_next_action_after_autofill_still_refills_new_page(self):
        from test_linkedin_easy_apply import Browser, form
        from modules.linkedin_easy_apply import advance_to_review
        browser=Browser([form('Resume','Next'),form('Work history','Next'),form('Review','Submit application')])
        fills=[]
        def fill(modal):
            fills.append(browser.page)
            if len(fills)==1:
                browser.page=1
                browser.render()
        advance_to_review(browser,fill,timeout=.2)
        self.assertEqual(browser.clicks,['Next'])
        self.assertEqual(fills,[0,1,2])

    def test_language_options_match_original_cv_without_selecting_none(self):
        self.assertEqual(multi_select_values('Programming languages (Select all that apply)*',
            ['Python', 'JavaScript / TypeScript', 'Java', 'None of the above'],
            'Python, TypeScript, JavaScript'), ['Python', 'JavaScript / TypeScript'])

    def test_claude_does_not_imply_claude_code(self):
        options = ['B. ChatGPT / Gemini / Claude', 'C. Specific AI Agents (Devin, Claude Code)']
        self.assertEqual(multi_select_values('Which AI tools do you primarily use for coding assistance?',
            options, 'Claude, Codex'), options[:1])

    def test_exact_mapping_and_unknown_options(self):
        self.assertEqual(multi_select_values('Tools (select all)*', ['One', 'Two'], '',
            {'Tools (select all)': ['Two']}), ['Two'])
        with self.assertRaises(ValueError):
            multi_select_values('Tools (select all)', ['One'], '', {'Tools (select all)': ['Missing']})
        self.assertEqual(multi_select_values('Consent (select all)*', ['I agree'], 'I agree'), [])

    def test_posting_metadata_does_not_enter_resume_titles(self):
        self.assertEqual(normalized_role_title(
            'Member of Technical Staff: Python, TypeScript & LLM Agent Evals | San Francisco On-site | Up to $400K + Equity'),
            'Member of Technical Staff')
        self.assertEqual(normalized_role_title('Staff Engineer - Hybrid'), 'Staff Engineer')
        self.assertEqual(normalized_role_title('Senior Engineer - Go'), 'Senior Engineer - Go')


@unittest.skipUnless(os.environ.get('JOBROBO_BROWSER_REPLAY_TESTS'), 'Opt-in local Chrome; no employer actions')
class FailedFormReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1300,900')
        cls.driver = webdriver.Chrome(options=options)
        cls.driver.execute_cdp_cmd('Network.enable', {})
        cls.driver.execute_cdp_cmd('Network.setBlockedURLs', {'urls': ['http://*', 'https://*']})

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def load(self, html):
        self.driver.get('data:text/html;base64,' + base64.b64encode(html.encode()).decode())

    def test_saved_multiselect_dom_selects_source_backed_options(self):
        from bs4 import BeautifulSoup
        from docx import Document
        from selenium.webdriver.common.by import By
        for job in ['4478591587', '4480993147']:
            paths = list(Path('logs/application_ui_diagnostics').glob(job+'-20261103*.private.html'))
            if not paths:
                self.skipTest('Private saved DOM is available only on the local investigation machine')
            soup = BeautifulSoup(paths[-1].read_text(), 'html.parser')
            group = next(fs.parent for fs in soup.select('fieldset')
                         if fs.select('input[type=checkbox]') and 'Select all' in fs.parent.get_text())
            # Only the failed question is replayed; scripts and remote assets are omitted.
            self.load('<dialog open aria-label="Apply to Replay">'+str(group)+'</dialog>')
            with TemporaryDirectory() as folder:
                source=Path(folder)/'source.docx'
                doc=Document();doc.add_paragraph('Python, JavaScript, TypeScript, Java, Claude, Codex');doc.save(source)
                handled,count=fill_multi_select_groups(self.driver.find_element(By.CSS_SELECTOR,'dialog'),
                    lambda control:control.click(),set(),{'default_resume_docx_path':str(source)})
            self.assertEqual(count,1)
            self.assertTrue(handled)
            self.assertTrue(self.driver.find_elements(By.CSS_SELECTOR,'input[type=checkbox]:checked'))

    def test_saved_crazy_maple_screening_uses_config_without_ai(self):
        from bs4 import BeautifulSoup
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        from test_search_runner import ReceiptRecoveryTests
        from test_application_screening import ScreeningTests
        from unittest.mock import Mock
        paths=list(Path('logs/application_ui_diagnostics').glob('4480290230-20261103*.private.html'))
        if not paths:
            self.skipTest('Private saved DOM unavailable')
        soup=BeautifulSoup(paths[-1].read_text(),'html.parser')
        labels=[label for label in soup.select('label[for]') if any(
            term in label.get_text().lower() for term in ['legally eligible','personal relationships','referred to this position'])]
        self.assertEqual(len(labels),3)
        markup='<dialog open aria-label="Apply to Crazy Maple Studio"><h2>Apply to Crazy Maple Studio</h2>'
        for label in labels:
            control=soup.find(id=label['for'])
            markup+='<div>'+str(label)+str(control)+'</div>'
        self.load(markup+'</dialog>')
        _,ns=ReceiptRecoveryTests().checkbox_form('',**ScreeningTests().settings())
        ns.update(driver=self.driver,actions=ActionChains(self.driver),full_name='Applicant Name',middle_name='',
                  ai_descriptive_answers_enabled=True)
        draft=Mock(side_effect=AssertionError('Personal questions must not invoke AI'))
        ns['answer_questions'](self.driver.find_element(By.CSS_SELECTOR,'dialog'),set(),'Bay Area',draft_answer=draft)
        values=[self.driver.find_element(By.ID,label['for']).get_attribute('value') for label in labels]
        self.assertEqual(values,['Yes','No','No'])
        draft.assert_not_called()

    def test_long_resume_dom_settles_and_reads_real_page_counter(self):
        from bs4 import BeautifulSoup
        from modules.linkedin_easy_apply import _settled_state, _navigation_snapshot
        paths=list(Path('logs/application_ui_diagnostics').glob('4482879755-20261103*.private.html'))
        if not paths:
            self.skipTest('Private saved DOM unavailable')
        soup=BeautifulSoup(paths[-1].read_text(),'html.parser');dialog=soup.select_one('dialog')
        for node in dialog.select('script,iframe,img,link'):
            node.decompose()
        self.load(str(dialog))
        modal,kind,button=_settled_state(self.driver,10,None,None)
        self.assertEqual(kind,'next')
        self.assertEqual(_navigation_snapshot(modal,kind)['page'],'2/4 pages')

    def test_saved_jiffy_missing_dates_card_opens_editor_and_saves(self):
        from bs4 import BeautifulSoup
        from docx import Document
        from selenium.webdriver.common.by import By
        from modules.linkedin_work_history import repair_incomplete_work_history_summary
        from test_linkedin_work_history import editor
        paths=list(Path('logs/application_ui_diagnostics').glob('4405808476-20261103*.private.html'))
        if not paths:
            self.skipTest('Private saved DOM unavailable')
        dialog=BeautifulSoup(paths[-1].read_text(),'html.parser').select_one('dialog')
        self.load(str(dialog))
        self.driver.execute_script('''for(const button of document.querySelectorAll('button[aria-label="Edit, Work Experience"]')) {
          button.onclick=function(){
            let card=this.parentElement;
            while(card.parentElement && !/Dates of employment/.test(card.textContent))card=card.parentElement;
            window.editedCard=card.textContent;
            document.querySelector('dialog').outerHTML=arguments[0];
          }.bind(button,arguments[0]);
        }''', editor().replace('<button>Save</button>',
            '<button onclick="window.savedDates=[...document.querySelectorAll(\'select\')].map(s=>s.options[s.selectedIndex].text);this.closest(\'dialog\').innerHTML=\'<h2>Apply to Example</h2><p>Saved</p><button>Next</button>\'">Save</button>'))
        with TemporaryDirectory() as folder:
            source=Path(folder)/'resume.docx';doc=Document()
            doc.add_paragraph('Senior Software Engineer January 2016 - January 2018');doc.save(source)
            self.assertTrue(repair_incomplete_work_history_summary(self.driver,
                self.driver.find_element(By.CSS_SELECTOR,'dialog'),source,set()))
        self.assertIn('Fission Labs',self.driver.execute_script('return window.editedCard'))
        self.assertEqual(self.driver.execute_script('return window.savedDates'),['January','2016','January','2018'])

    def test_upload_auto_advance_refills_same_kind_next_page_before_click(self):
        from modules.linkedin_easy_apply import advance_to_review
        self.load('<dialog open aria-label="Apply to Replay"><h2>Apply to Replay</h2>'
                  '<p>2/4 pages</p><input type="radio" aria-label="old.pdf">'
                  '<button>Next</button></dialog>')
        fills=[]
        def fill(modal):
            fills.append(self.driver.execute_script('return arguments[0].textContent',modal))
            if len(fills)==1:
                self.driver.execute_script('''arguments[0].innerHTML='<h2>Apply to Replay</h2><p>3/4 pages</p><label>Work history</label><input id="work"><button>Next</button>';
                    arguments[0].querySelector('button').onclick=function(){
                      this.closest('dialog').innerHTML='<h2>Apply to Replay</h2><p>4/4 pages</p><button>Submit application</button>';
                    };''',modal)
        result=advance_to_review(self.driver,fill,timeout=3)
        self.assertGreaterEqual(len(fills),2)
        self.assertIn('Work history',fills[1])
        self.assertIn('Submit application',result.text)


if __name__ == '__main__':
    unittest.main()
