"""Offline staffing-agency detection for --exclude-agencies: no browser or network."""
import unittest

from modules.agency_filter import (AgencyExcluded, agency_by_about_company, agency_by_description,
                                   agency_by_name, classify, normalize_company)


class AgencyNameTests(unittest.TestCase):
    def test_listed_agencies_and_aggregators_match_with_punctuation_and_suffixes(self):
        for company in ("Harnham", "People In AI", "Jobgether", "Insight Global, LLC", "CYBERCODERS",
                        "Strategic Employment Partners (SEP)", "Colossus Search Group", "talentpluto"):
            with self.subTest(company=company):
                self.assertIsNotNone(agency_by_name(company))

    def test_name_shapes_used_only_by_staffing_firms(self):
        for company in ("Acme Recruiting", "Northwind Staffing", "Blue Executive Search", "Recruits Lab",
                        "Peak Search Partners", "Murphy Talent Group"):
            with self.subTest(company=company):
                self.assertIsNotNone(agency_by_name(company))

    def test_direct_employers_and_consultancies_are_not_agencies_by_default(self):
        for company in ("Replit", "Together AI", "Counterpart Health", "Elastic Ltd", "Perplexity",
                        "TrueFoundry", "Search Labs", "Talent Connect", "Cognizant", "Fractal", "Provectus", "", None):
            with self.subTest(company=company):
                self.assertIsNone(agency_by_name(company))

    def test_extra_and_allow_lists(self):
        self.assertIsNotNone(agency_by_name("Cognizant Technology Solutions", extra_names=["cognizant technology solutions"]))
        self.assertIsNone(agency_by_name("Harnham", allow_names=["HARNHAM"]))
        self.assertEqual(normalize_company(" Insight  Global, Inc. "), "insight global")


class AgencyDetailTests(unittest.TestCase):
    def test_linkedin_staffing_industry(self):
        self.assertIsNotNone(agency_by_about_company("About the company\nProSearch\nStaffing and Recruiting • 201-500 employees"))
        self.assertIsNotNone(agency_by_about_company("Staffing & Recruiting"))
        self.assertIsNone(agency_by_about_company("Software Development • 51-200 employees"))
        self.assertIsNone(agency_by_about_company("Staffing and Recruiting", company="Paraform", allow_names=["Paraform"]))

    def test_third_party_posting_language(self):
        for text in ("Aventis is working on behalf of its partner.", "We are partnering with a Series B AI startup.",
                     "Our client, a profitable fintech, is hiring.", "Hiring on behalf of our client in SF.",
                     "Our confidential client builds agents."):
            with self.subTest(text=text):
                self.assertIsNotNone(agency_by_description(text))

    def test_employer_language_is_not_third_party(self):
        for text in ("We partner with a range of customers.", "Our clients love the platform.",
                     "You will work with customers and partners.", "We are partnering with a number of hospitals."):
            with self.subTest(text=text):
                self.assertIsNone(agency_by_description(text))

    def test_classify_returns_first_reason_and_exception_is_value_error(self):
        self.assertIn("name", classify("Harnham", "Software Development", "Direct role"))
        self.assertIn("Staffing", classify("Acme", "Staffing and Recruiting", None))
        self.assertIsNone(classify("Acme", "Software Development", "We build agents."))
        self.assertTrue(issubclass(AgencyExcluded, ValueError))


if __name__ == "__main__":
    unittest.main()
