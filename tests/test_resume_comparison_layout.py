"""Reader-first comparison layout preserves collapsed diagnostic evidence."""
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.resume_all_bullets import _comparison


class ComparisonDocument(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.tags = []
        self.details = []
        self.json_blocks = []
        self.capture = None
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if tag == 'details':
            self.details.append(attrs)
        if tag == 'pre' and attrs.get('data-format') == 'json':
            self.capture = {'chunks': [], 'collapsed': bool(self.details) and 'open' not in self.details[-1]}

    def handle_data(self, data):
        if self.capture is not None:
            self.capture['chunks'].append(data)

    def handle_endtag(self, tag):
        if tag == 'pre' and self.capture is not None:
            self.json_blocks.append((json.loads(''.join(self.capture['chunks'])), self.capture['collapsed']))
            self.capture = None
        if tag == 'details':
            self.details.pop()


class ResumeComparisonLayoutTest(unittest.TestCase):
    def render(self, root, report, records=()):
        (root / 'exact-jd.txt').write_text('Full JD with Python and AWS.', encoding='utf-8')
        _comparison(root, report, records)
        return (root / 'comparison.html').read_text(encoding='utf-8')

    def report(self):
        return dict(
            status='partial', strict_attachment_eligible=False, run_id='comparison-test',
            same_jd_verified=True, coverage=dict(inventoried=2, accepted=1, retained_source=1, failed=1),
            experience_coverage=[dict(experience_id='experience-a', accepted=1, failed=1)],
            score_breakdown=dict(all=dict(source=dict(percentage=20), output=dict(percentage=40),
                                          point_delta=20, total_weight=5)),
            tailoring_contract='all-bullets-skills-titles-v1',
            skills_optimization=dict(source=['AWS', 'Python'], output=['Python', 'AWS'], changed=True),
            skills_grounding=dict(policy='grounded', blocked_keywords=['Unsupported technology']),
            skills_layout=dict(source_skill_count=2, output_skill_count=2),
            title_changes=[dict(paragraph_index=4, source='Engineer\t2020–2022',
                                output='Staff Engineer\t2020–2022')],
            match_analysis=dict(method='test-evidence', requirements=['Exact requirement']),
            pre_optimization=dict(score=20), post_optimization=dict(score=40),
            keyword_provenance=dict(method='source-bound'),
            ai_activity=dict(request_attempts=3), source_sha256='source-hash', jd_sha256='jd-hash',
        )

    def test_summary_skills_and_titles_precede_panes_and_all_json_follows_bullets(self):
        report = self.report()
        records = [dict(bullet_id='bullet-a', source_text='Original bullet', rewritten_text='Draft bullet',
                        status='accepted', reason=None, matched_jd_spans=['Exact requirement'],
                        introduced_jd_keywords=['agentic systems', 'evaluation'])]
        with TemporaryDirectory() as tmp:
            page = self.render(Path(tmp), report, records)
        panes = page.index('<div class="panes">')
        coverage = page.index('<h2>Coverage by stable source identity</h2>')
        diagnostics = page.index('<h2 id="diagnostics">')
        self.assertLess(page.index('Bullets: 1 accepted of 2 inventoried'), panes)
        self.assertLess(page.index('Skills and professional title changes'), panes)
        self.assertLess(page.index('Skills: 2 original; 2 draft.'), panes)
        self.assertLess(page.index('Staff Engineer'), panes)
        self.assertLess(panes, coverage)
        self.assertLess(page.index('Draft bullet'), diagnostics)
        self.assertLess(page.index('<th>Added JD keywords</th>'), diagnostics)
        self.assertLess(page.index('<td>agentic systems, evaluation</td>'), diagnostics)
        self.assertIn('<td>Exact requirement</td>', page)
        self.assertNotIn("['agentic systems', 'evaluation']", page)
        self.assertLess(coverage, diagnostics)
        json_positions = [match.start() for match in re.finditer('<pre data-format="json">', page)]
        self.assertEqual(len(json_positions), 5)
        self.assertTrue(all(position > diagnostics for position in json_positions))
        parsed = ComparisonDocument(page)
        self.assertTrue(all(collapsed for _, collapsed in parsed.json_blocks))
        self.assertEqual(parsed.json_blocks[-1][0], report, 'Complete diagnostics and provenance must survive presentation changes')
        self.assertEqual(parsed.json_blocks[1][0], dict(total=report['coverage'], experiences=report['experience_coverage']))
        for target in ('original.pdf', 'optimized.pdf', 'original.docx', 'optimized.docx',
                       'artifact-manifest.json', 'match-report.json', 'rewrite-coverage.json'):
            self.assertIn(target, page)
        self.assertIn("crypto.subtle.digest('SHA-256'", page)
        self.assertIn('BINDING UNVERIFIED / FAILED', page)

    def test_partial_run_without_optional_diagnostics_keeps_honest_reader_summary(self):
        report = dict(status='blocked', strict_attachment_eligible=False, run_id='blocked-test')
        with TemporaryDirectory() as tmp:
            page = self.render(Path(tmp), report)
        self.assertIn('Partial / not eligible for strict generated attachment', page)
        self.assertIn('Skills comparison unavailable for this run.', page)
        self.assertIn('Same exact JD: unverified.', page)
        self.assertLess(page.index('Skills comparison unavailable'), page.index('<div class="panes">'))
        self.assertEqual(ComparisonDocument(page).json_blocks[-1][0], report)

    def test_resume_and_diagnostic_strings_are_escaped_in_both_presentations(self):
        report = self.report()
        attack = '<img src=x onerror="alert(1)">'
        report['skills_optimization']['output'] = [attack]
        report['title_changes'][0]['output'] = attack
        report['keyword_provenance']['untrusted_note'] = attack
        record = dict(bullet_id='bullet-a', source_text=attack, rewritten_text=attack,
                      status='blocked', reason=attack, introduced_jd_keywords=[attack])
        with TemporaryDirectory() as tmp:
            page = self.render(Path(tmp), report, [record])
        parsed = ComparisonDocument(page)
        self.assertNotIn('img', parsed.tags)
        self.assertNotIn(attack, page)
        self.assertIn('&lt;img', page)
        self.assertEqual(parsed.json_blocks[-1][0], report)


if __name__ == '__main__':
    unittest.main()
