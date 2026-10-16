"""Landing prompt may hydrate into modern results after native submission."""
import unittest
from unittest.mock import Mock
from urllib.parse import urlencode
from lxml import html
from test_linkedin_modern_search import FilterBrowser, FIXTURES, make_spec, immediate
from modules.linkedin_search import prepare_search
from modules.linkedin_modern_search import clear_recipe_cache

class LandingBrowser(FilterBrowser):
    def __init__(self):
        super().__init__()
        self.root=html.fromstring('<html><body><textarea placeholder="Describe the job you want"></textarea></body></html>')
        self.current_url='https://www.linkedin.com/jobs/'
    def type_into(self,node,value):
        super().type_into(node,value)
        if '\ue007' in value and node.tag == 'textarea':
            query=node.get('value')
            self.root=html.fromstring((FIXTURES/'linkedin_modern_filters.html').read_text())
            self.root.xpath('//*[@componentkey="semanticSearchBox"]')[0].set('value',query)
            self.current_url='https://www.linkedin.com/jobs/search-results/?'+urlencode({'keywords':query,'geoId':'103644278'})

class LandingTransitionTests(unittest.TestCase):
    def test_landing_prompt_transition_uses_modern_filter_and_location_verification(self):
        clear_recipe_cache()
        driver=LandingBrowser()
        classic=Mock(return_value=[])
        result=prepare_search(driver,make_spec(),Mock(),Mock(),classic,wait=immediate,timeout=.1)
        classic.assert_not_called()
        self.assertEqual(result.ui_variant,'modern_prompt')
        self.assertIn('easy_apply_only',result.verified_filters)
        self.assertIn('search_location',result.verified_filters)
        self.assertEqual(result.location_confirmation['selected_label'],'San Francisco Bay Area')
