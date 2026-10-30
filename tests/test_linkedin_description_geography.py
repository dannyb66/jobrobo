"""Explicit JD office requirements override conflicting search-card geography."""
import ast
from pathlib import Path
import re
import unittest


class DescriptionGeographyTest(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'runAiBot.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='description_geography_rejections')
        namespace={'re':re}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        self.check=namespace[node.name]
        self.intent={'search_location':'San Francisco Bay Area','on_site':['Remote','Hybrid']}

    def test_explicit_glendale_onsite_is_rejected_even_with_bay_area_service_area(self):
        jd='We serve Greater LA and the Bay Area.\nThe details\nIn person, 5 days a week, at our office in Glendale, CA'
        reasons=self.check(jd,self.intent)
        self.assertTrue(any('location_excluded' in reason for reason in reasons))
        self.assertTrue(any('Glendale' in reason for reason in reasons))

    def test_explicit_bay_area_hybrid_is_allowed(self):
        jd='This role is hybrid, onsite three days a week at our office in San Francisco, CA'
        self.assertEqual(self.check(jd,self.intent),[])

    def test_fully_onsite_is_rejected_when_only_remote_hybrid_are_configured(self):
        self.assertTrue(self.check('Location: San Francisco, CA (On-site)',self.intent))
        self.assertEqual(self.check('Location: San Francisco, CA (On-site)',{**self.intent,'on_site':['On-site']}),[])

    def test_remote_or_company_context_does_not_create_an_office_requirement(self):
        for jd in ['Fully remote anywhere in the United States.',
                   'We serve onsite customers in Glendale, CA and across the Bay Area.',
                   'This role does not require onsite work in Glendale, CA.']:
            self.assertEqual(self.check(jd,self.intent),[])

    def test_no_named_explicit_location_does_not_invent_a_city(self):
        self.assertEqual(self.check('Work onsite with enterprise customers.',self.intent),[])


if __name__=='__main__':unittest.main()
