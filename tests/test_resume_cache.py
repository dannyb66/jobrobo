import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules.resume_cache import (
    cache_record_path, load_cached_resume, resume_cache_fingerprint, store_cached_resume,
)


class ResumeCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.source = self.repo / "all resumes" / "default" / "resume.docx"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"source resume v1")
        (self.repo / "modules" / "ai").mkdir(parents=True)
        (self.repo / "modules" / "resume_all_bullets.py").write_text("v1")
        (self.repo / "modules" / "ai" / "resume_optimizer.py").write_text("v1")
        (self.repo / "config" / "prompts").mkdir(parents=True)
        (self.repo / "config" / "prompts" / "resume_bullets.txt").write_text("prompt v1")
        self.config = {"rewrite_all_bullets": True, "content_policy": "synthetic_jd_test"}

    def fingerprint(self, jd="JD one", config=None):
        return resume_cache_fingerprint(job_id="123", job_description=jd,
            source_resume=self.source, job_title="Staff Engineer", first_name="A", last_name="B",
            config=config or self.config, repo_root=self.repo)

    def test_key_is_bound_to_job_description_source_and_config(self):
        original = self.fingerprint()
        self.assertNotEqual(original, self.fingerprint(jd="JD two"))
        self.assertNotEqual(original, self.fingerprint(config={**self.config, "content_policy": "grounded"}))
        self.source.write_bytes(b"source resume v2")
        self.assertNotEqual(original, self.fingerprint())

    def test_prompt_or_optimizer_change_invalidates_key(self):
        original = self.fingerprint()
        (self.repo / "config" / "prompts" / "resume_bullets.txt").write_text("prompt v2")
        self.assertNotEqual(original, self.fingerprint())

    def test_long_context_text_is_not_treated_as_a_filename(self):
        config = {**self.config, "company_context": "Morgan Stanley\n" + ("context " * 10000)}
        key = resume_cache_fingerprint(job_id="123", job_description="JD", source_resume=self.source,
            job_title="Staff Engineer", first_name="A", last_name="B", config=config, repo_root=self.repo)
        self.assertEqual(len(key), 64)

    def test_only_intact_verified_pdf_is_reused(self):
        fingerprint = self.fingerprint()
        record = cache_record_path(self.source, "123", fingerprint)
        pdf = self.root / "optimized.pdf"
        pdf.write_bytes(b"verified")
        self.assertTrue(store_cached_resume(record, fingerprint, pdf))
        verifier = lambda path: path.read_bytes() == b"verified"
        self.assertEqual(load_cached_resume(record, fingerprint, verifier), pdf.resolve())
        pdf.write_bytes(b"changed")
        self.assertIsNone(load_cached_resume(record, fingerprint, verifier))

    def test_missing_or_rejected_artifact_is_cache_miss(self):
        fingerprint = self.fingerprint()
        record = cache_record_path(self.source, "123", fingerprint)
        pdf = self.root / "optimized.pdf"
        pdf.write_bytes(b"verified")
        store_cached_resume(record, fingerprint, pdf)
        self.assertIsNone(load_cached_resume(record, "wrong-key", lambda _: True))
        self.assertIsNone(load_cached_resume(record, fingerprint, lambda _: False))
        pdf.unlink()
        self.assertIsNone(load_cached_resume(record, fingerprint, lambda _: True))

    def test_upload_flow_reuses_verified_resume_and_skips_optimizer(self):
        from modules.resume_upload import upload_verified_resume
        from modules import resume_all_bullets

        config = {"rewrite_all_bullets": True, "source_checks_enabled": False,
                  "content_policy": "synthetic_jd_test"}
        source = self.root / "all resumes" / "default" / "resume.docx"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source docx")
        output = self.root / "all resumes" / "temp" / "task11" / "run-1" / "optimized.pdf"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"verified optimized pdf")
        optimizer = Mock(return_value=str(output))
        modal = Mock()
        modal.find_element.return_value = Mock()

        with patch("modules.config_loader.peek_runtime_config", return_value=config), \
             patch.object(resume_all_bullets, "verify_strict_attachment", return_value=True):
            first = upload_verified_resume(modal, source, "exact JD", "123", "Staff Engineer",
                                           optimize=optimizer)
            second = upload_verified_resume(modal, source, "exact JD", "123", "Staff Engineer",
                                            optimize=optimizer)

        self.assertTrue(first[0] and second[0])
        optimizer.assert_called_once()

    def test_upload_flow_does_not_reuse_for_changed_job_description(self):
        from modules.resume_upload import upload_verified_resume
        from modules import resume_all_bullets

        config = {"rewrite_all_bullets": True, "source_checks_enabled": False,
                  "content_policy": "synthetic_jd_test"}
        source = self.root / "all resumes" / "default" / "resume.docx"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source docx")
        output = self.root / "all resumes" / "temp" / "task11" / "run-1" / "optimized.pdf"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"verified optimized pdf")
        optimizer = Mock(return_value=str(output))
        modal = Mock()
        modal.find_element.return_value = Mock()

        with patch("modules.config_loader.peek_runtime_config", return_value=config), \
             patch.object(resume_all_bullets, "verify_strict_attachment", return_value=True):
            upload_verified_resume(modal, source, "JD one", "123", "Staff Engineer", optimize=optimizer)
            upload_verified_resume(modal, source, "JD two", "123", "Staff Engineer", optimize=optimizer)

        self.assertEqual(optimizer.call_count, 2)


if __name__ == "__main__":
    unittest.main()
