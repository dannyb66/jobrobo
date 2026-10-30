"""Opt-in Chrome regression using local synthetic forms, never an employer.

JOBROBO_BROWSER_TESTS=1 PYTHONPATH=tests:. python3 -m unittest test_generic_prepare_browser
"""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from modules.generic_prepare import prepare_url, PreparationBrowser
from modules.direct_careers_apply import digest

JOB = {'@context': 'https://schema.org', '@type': 'JobPosting', 'title': 'Staff Engineer',
       'hiringOrganization': {'name': 'Synthetic Test'},
       'jobLocation': {'address': {'addressCountry': 'US'}},
       'description': 'Build reliable distributed software systems using Python and cloud infrastructure. ' * 8}


def page(path):
    header = '<title>Staff Engineer @ Synthetic Test</title><script type="application/ld+json">' + json.dumps(JOB) + '</script><h1>Staff Engineer</h1>'
    fields = '<label>Email<input name="email" type="email" required></label><label>Resume<input name="resume" type="file" required></label>'
    final = '<button id="submit" type="submit" onclick="window.finalClicks++">Submit application</button>'
    before = '<script>window.finalClicks=0;window.submits=0</script>'
    if path == '/entry':
        return header + before + '<a href="/native">Apply for this job</a>'
    if path == '/modal':
        return header + before + '<button type="button" onclick="this.outerHTML=' + "'" + '<form>' + fields.replace('"', '&quot;') + final.replace('"', '&quot;') + '</form>' + "'" + '">Apply now</button>'
    if path == '/frame':
        return header + before + '<iframe src="/native" width="1000" height="800"></iframe>'
    if path == '/shadow':
        return header + before + '<div id="host"></div><script>host.attachShadow({mode:"open"}).innerHTML=' + json.dumps('<form>'+fields+final+'</form>') + '</script>'
    if path == '/access':
        return header + before + '<p>Sign in to apply</p><input type="password">'
    if path == '/closed':
        return header + before + '<h2>This job is no longer available</h2>'
    if path == '/unknown':
        fields += '<label>Are you legally authorized to work in the US?<input name="work_auth" required></label><label>Phone<input name="phone" required></label>'
    if path == '/first-choice':
        fields += '<label>Which team?<select name="team" required><option value="">Select</option><option value="engineering">Engineering</option><option value="product">Product</option></select></label><label>Optional Twitter URL<input name="twitter"></label>'
    if path == '/dei':
        fields += '<fieldset><legend>Which communities do you belong to?</legend><label><input type="checkbox" name="community" value="a" checked>Community A</label><label><input type="checkbox" name="community" value="none">None of the above</label></fieldset><label>Gender<select name="gender"><option value="male">Male</option><option value="none">Prefer not to answer</option></select></label>'
    if path == '/choice':
        fields += '<label>Country<select name="country" required><option value="">Select</option><option value="US">United States</option></select></label>'
    if path == '/styled':
        fields += '<div style="height:900px"></div><fieldset><legend>How did you hear about us? *</legend><label style="display:block;height:40px"><input style="opacity:0;position:absolute" type="checkbox" name="source" value="Other" required><span>Other</span></label><label><input type="checkbox" name="source" value="LinkedIn" required>LinkedIn</label></fieldset><div style="position:fixed;bottom:0;background:gray;height:100px;width:100%">Fixed overlay</div>'
    if path in ('/custom', '/custom-stuck', '/intended-country', '/custom-unknown', '/custom-retry', '/custom-dei'):
        fields += '<label id="country-label">Country *</label><button type="button" role="combobox" aria-labelledby="country-label" aria-required="true" id="country" onclick="options.hidden=false">Choose</button><div id="options" role="listbox" hidden><div role="option" onclick="country.textContent=this.textContent;country.dataset.value=this.textContent;options.hidden=true">United States</div></div>'
        if path == '/custom-stuck':
            fields = fields.replace('country.textContent=this.textContent;country.dataset.value=this.textContent;options.hidden=true', 'void 0')
        if path == '/intended-country':
            fields = fields.replace('Country *', 'Which country do you intend to work from? *')
        if path == '/custom-unknown':
            fields = fields.replace('Country *', 'Which team? *').replace('United States', 'Engineering')
        if path == '/custom-retry':
            fields = fields.replace('onclick="options.hidden=false"', 'onclick="window.opens=(window.opens||0)+1;if(window.opens>1)options.hidden=false"')
        if path == '/custom-dei':
            fields = fields.replace('Country *', 'Gender *').replace('United States', 'Male')
            fields = fields.replace('>Male</div></div>', '>Male</div><div role="option" onclick="country.textContent=this.textContent;country.dataset.value=this.textContent;options.hidden=true">Prefer not to answer</div></div>')
    if path in ('/phone-country', '/phone-country-wrong'):
        flag = 'ca' if path.endswith('wrong') else 'us'
        fields += '<label id="country-label">Country *</label><div class="select__control"><div class="select__single-value" id="selected"></div><input id="country" role="combobox" aria-labelledby="country-label" aria-required="true" aria-expanded="false" aria-controls="countries"><button type="button" aria-label="Toggle flyout" onclick="countries.hidden=false;country.setAttribute(\'aria-expanded\',\'true\')">Toggle</button></div><div id="countries" role="listbox" hidden><div role="option" onclick="selected.innerHTML=\'<div class=&quot;iti__flag iti__' + flag + '&quot;></div><span>+1</span>\';countries.hidden=true;country.setAttribute(\'aria-expanded\',\'false\')"><div class="iti__flag iti__us"></div>United States+1</div></div>'
    if path == '/aria-radio':
        fields += '<div role="radiogroup" aria-required="true"><h3>Country *</h3><div role="radio" aria-label="United States" aria-checked="false" onclick="this.setAttribute(\'aria-checked\',\'true\')">United States</div><div role="radio" aria-label="Canada" aria-checked="false">Canada</div></div>'
    if path == '/unresolved-modal':
        fields += '<label>Optional location<input name="optional-location" role="combobox" aria-expanded="false" onclick="form.setAttribute(\'aria-hidden\',\'true\');popup.hidden=false" onkeydown="if(event.key===\'Escape\'){form.removeAttribute(\'aria-hidden\');popup.hidden=true}"></label>'
        return header + before + '<form id="form">' + fields + final + '</form><div id="popup" role="listbox" hidden>No results<button type="button">Dismiss</button></div>'
    if path == '/unknown-control':
        fields += '<div role="spinbutton" aria-required="true" aria-label="Unknown custom required widget">Choose</div>'
    if path == '/styled-required':
        fields += '<div data-field-path="unknown"><label class="_required_xyz" for="unknown">Unknown factual field</label><input id="unknown" name="unknown"></div>'
    if path == '/styled-choice':
        fields += '<div data-field-path="country"><label class="_required_xyz">Country</label><label><input type="radio" name="country" value="United States">United States</label><label><input type="radio" name="country" value="Canada">Canada</label></div>'
    if path == '/boolean-buttons':
        fields += '<div data-field-path="sponsor"><label class="_required_xyz">Will you now or in the future require sponsorship for employment visa status to work in this location?</label><button aria-pressed="false" data-option="yes">Yes</button><button aria-pressed="false" data-option="no" onclick="this.setAttribute(\'aria-pressed\',\'true\')">No</button><input style="display:none" type="checkbox"></div>'
    if path == '/city-autocomplete':
        fields += '<label id="city-label">Location *</label><input id="city" role="combobox" aria-labelledby="city-label" aria-expanded="false" onclick="cities.hidden=false;this.setAttribute(\'aria-expanded\',\'true\')"><div id="cities" role="listbox" hidden><div role="option" onclick="city.value=this.textContent;cities.hidden=true;city.setAttribute(\'aria-expanded\',\'false\')">San Francisco, California, United States</div><div role="option">San Francisco Bay Area, California, United States</div></div>'
    if path == '/unknown-required-proxy':
        fields += '<div data-field-path="unknown"><label class="_required_xyz">Unknown required choice</label><button type="button">Pick</button><input style="display:none" type="checkbox"></div>'
    if path == '/attestation':
        fields += '<div><p>Please confirm all information is accurate and complete.</p><div role="radiogroup" aria-required="true"><label><input name="confirm" type="radio" required value="confirm">I have reviewed and confirmed that all the information provided is accurate and complete.</label></div></div>'
    if path == '/receipt':
        fields = fields.replace('type="file"', 'type="file" onchange="const name=this.files[0].name;this.value=\'\';document.getElementById(\'receipt\').textContent=name"') + '<p id="receipt"></p>'
        fields = fields.replace('<label>Resume', '<div aria-required="true" aria-label="Resume"><label>Resume') + '</div>'
    if path == '/conditional':
        fields += '<label>Current employer<input name="employer" required onchange="document.getElementById(\'conditional\').hidden=false"></label><div id="conditional" hidden><label>Phone<input name="phone" required></label></div>'
    if path == '/multi':
        return header + before + '<form onsubmit="window.submits++;return false"><div id="one">' + fields + '<button type="button" onclick="one.hidden=true;two.hidden=false">Next</button></div><div id="two" hidden><label>Phone<input name="phone" required></label>' + final + '</div></form>'
    if path == '/multi-submit':
        return header + before + '<form id="one" onsubmit="one.hidden=true;two.hidden=false;return false">' + fields + '<button type="submit">Next</button></form><form id="two" hidden><label>Phone<input name="phone" required></label>' + final + '</form>'
    return header + before + '<form id="form" onsubmit="window.submits++;return false">' + fields + final + '</form>' + '<footer><label>Theme<input type="radio" name="theme" value="Light"></label><label>Theme<input type="radio" name="theme" value="Dark"></label></footer>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = ('<!doctype html><meta charset="utf-8">' + page(self.path)).encode()
        self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(os.environ.get('JOBROBO_BROWSER_TESTS') == '1', 'Opt-in local Chrome regression')
class BrowserPreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True); cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'
        options = webdriver.ChromeOptions(); options.add_argument('--headless=new')
        cls.driver = webdriver.Chrome(options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit(); cls.server.shutdown(); cls.server.server_close()

    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.pdf = Path(self.temp.name)/'optimized.pdf'; self.pdf.write_bytes(b'synthetic fixture attachment')
        self.calls = []

    def run_form(self, path, *, legacy_review_required=False, first_choice=False, dei_opt_out=False):
        def resume(job, root):
            self.calls.append(job)
            return {'pdf': str(self.pdf), 'pdf_sha256': digest(self.pdf), 'job_id': 'synthetic',
                    'visual_review_required': legacy_review_required,
                    'visual_review_path': str(Path(self.temp.name)/'missing-review.json')}
        return prepare_url(self.base+path, driver=self.driver, output_dir=Path(self.temp.name)/'reports',
            candidate={'email': 'test@example.test', 'phone': '5550100', 'current_employer': 'Synthetic Test', 'country': 'United States', 'city': 'San Francisco', 'state': 'California', 'require_visa': 'No', 'application_source': 'Web search', 'gender': 'Male'},
            question_config={'unanswered_choice_policy': 'first_option' if first_choice else 'manual',
                             'dei_choice_policy': 'prefer_not_to_answer' if dei_opt_out else 'manual'}, resume_provider=resume, allow_local=True, settle=0.05)

    def test_dei_opt_out_replaces_existing_native_and_custom_choices(self):
        for path in ('/dei', '/custom-dei'):
            with self.subTest(path=path):
                result = self.run_form(path, first_choice=True, dei_opt_out=True)
                self.assertEqual(result['status'], 'prepared', result['blockers'])
                self.assertTrue(any(q['source'] == 'user_policy:dei_opt_out' for q in result['questions']))
                if path == '/dei':
                    controls = self.driver.find_elements('name', 'community')
                    self.assertEqual([e.is_selected() for e in controls], [False, True])
                    self.assertEqual(self.driver.find_element('name', 'gender').get_attribute('value'), 'none')
                else:
                    self.assertEqual(self.driver.find_element('id', 'country').text, 'Prefer not to answer')
                self.assertEqual(self.driver.execute_script('return window.finalClicks'), 0)

    def test_first_choice_and_optional_unanswered_reporting(self):
        for path in ('/first-choice', '/custom-unknown', '/attestation'):
            with self.subTest(path=path):
                result = self.run_form(path, first_choice=True)
                self.assertEqual(result['status'], 'prepared', result['blockers'])
                if path == '/first-choice':
                    self.assertEqual(self.driver.find_element('name', 'team').get_attribute('value'), 'engineering')
                    self.assertEqual(result['optional_unanswered'], ['Optional Twitter URL'])
                self.assertTrue(any(q['source'] == 'user_policy:first_option' for q in result['questions']))
                self.assertEqual(self.driver.execute_script('return window.finalClicks'), 0)
                self.assertEqual(self.driver.execute_script('return window.submits'), 0)

    def test_custom_menu_recovers_after_first_open_has_no_options(self):
        result = self.run_form('/custom-retry')
        self.assertEqual(result['status'], 'prepared', result['blockers'])
        self.assertEqual(self.driver.execute_script('return window.opens'), 2)
        self.assertEqual(self.driver.execute_script('return window.finalClicks'), 0)

    def test_legacy_review_marker_does_not_block_upload_or_filling(self):
        result = self.run_form('/native', legacy_review_required=True)
        self.assertEqual(result['status'], 'prepared', result['blockers'])
        self.assertTrue(result['attachment_verified'])
        self.assertEqual(self.driver.find_element('name', 'email').get_attribute('value'), 'test@example.test')
        self.assertFalse(Path(self.temp.name, 'missing-review.json').exists())
        self.assertEqual(self.driver.execute_script('return window.finalClicks'), 0)
        self.assertEqual(self.driver.execute_script('return window.submits'), 0)

    def test_native_entry_iframe_shadow_and_select_preparations(self):
        for path in ('/native', '/entry', '/frame', '/shadow', '/choice', '/custom', '/intended-country', '/phone-country', '/city-autocomplete', '/unresolved-modal', '/aria-radio', '/conditional', '/multi', '/multi-submit', '/styled', '/styled-choice', '/boolean-buttons', '/modal', '/receipt'):
            with self.subTest(path=path):
                result = self.run_form(path)
                self.assertEqual(result['status'], 'prepared', result['blockers'])
                self.assertTrue(result['attachment_verified'])
                self.assertTrue(result['submission_disabled'])
                self.assertEqual(self.driver.execute_script('return window.finalClicks'), 0)
                self.assertFalse(any(a['action'] == 'submit' for a in result['actions']))
                if path == '/boolean-buttons':
                    self.assertEqual(self.driver.find_element('css selector', '[data-option=no]').get_attribute('aria-pressed'), 'true')

    def test_unverified_custom_selection_and_unknown_required_control_block(self):
        for path in ('/custom-stuck', '/phone-country-wrong', '/unknown-control', '/styled-required', '/unknown-required-proxy'):
            with self.subTest(path=path):
                result = self.run_form(path)
                self.assertEqual(result['status'], 'blocked', result)
                self.assertTrue(result['blockers'])

    def test_attestation_is_not_checked_and_external_theme_controls_are_ignored(self):
        result = self.run_form('/attestation')
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(self.driver.find_element('name', 'confirm').is_selected())
        self.assertFalse(any(q['name'] == 'theme' for q in result['questions']))
        self.assertFalse(any(e.is_selected() for e in self.driver.find_elements('name', 'theme')))

    def test_unknown_fact_blocks_but_phone_and_resume_still_filled(self):
        result = self.run_form('/unknown')
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['attachment_verified'])
        self.assertTrue(any(q['name'] == 'phone' and q['status'] == 'prepared' for q in result['questions']))
        self.assertIn('Are you legally authorized to work in the US?', result['blockers'])

    def test_access_and_closed_never_generate_resume(self):
        self.assertEqual(self.run_form('/access')['status'], 'blocked')
        self.assertEqual(self.run_form('/closed')['status'], 'closed')
        self.assertEqual(self.calls, [])

    def test_guard_blocks_click_native_methods_and_enter(self):
        from selenium.webdriver.common.keys import Keys
        self.run_form('/native')
        driver = self.driver
        self.assertFalse(driver.execute_script('window.__jobroboPrepare.submissionMode=true;return window.__jobroboPrepare.armSubmit(document.getElementById("submit"))'))
        driver.find_element('id', 'submit').click()
        driver.execute_script('HTMLFormElement.prototype.submit.call(document.getElementById("form"));HTMLFormElement.prototype.requestSubmit.call(document.getElementById("form"));')
        driver.find_element('name', 'email').send_keys(Keys.ENTER)
        self.assertEqual(driver.execute_script('return window.finalClicks'), 0)
        self.assertEqual(driver.execute_script('return window.submits'), 0)
        blocked = driver.execute_script('return window.__jobroboPrepare.blocked')
        for event in ('final-click', 'form.submit', 'form.requestSubmit', 'enter'):
            self.assertIn(event, blocked)


if __name__ == '__main__':
    unittest.main()
