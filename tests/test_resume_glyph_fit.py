"""Fit estimates must use the source paragraph's font, not heading medians."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from modules.resume_all_bullets import _glyph_check


class GlyphFitTest(unittest.TestCase):
    def pdf(self):
        chars=[]
        for text,font,width in [('aaaa','Body',3),('bbbb','Body',7),('aaaaaaaa','Heading',6)]:
            for char in text:
                chars.append({'text':char,'fontname':font,'size':10,'x0':0,'x1':width})
        opened=MagicMock()
        opened.__enter__.return_value=SimpleNamespace(pages=[SimpleNamespace(chars=chars)])
        return opened

    def record(self, rewritten, budget):
        return {'source_text':'aaaa','rewritten_text':rewritten,'usable_line_width':budget,
                'source_rendered':{'line_count':1,'width':12}}

    def test_mixed_heading_widths_cannot_hide_body_overflow(self):
        with patch('pdfplumber.open',return_value=self.pdf()):
            check=_glyph_check('unused.pdf')
        self.assertIn('exceeds single-line budget',check(self.record('bbbb',20)))
        self.assertIsNone(check(self.record('bb',20)))

    def test_new_text_leaves_rendering_margin_without_rejecting_original(self):
        with patch('pdfplumber.open',return_value=self.pdf()):
            check=_glyph_check('unused.pdf')
        self.assertIsNotNone(check(self.record('bb',14.1)))
        self.assertIsNone(check(self.record('aaaa',12)))


if __name__=='__main__':unittest.main()
