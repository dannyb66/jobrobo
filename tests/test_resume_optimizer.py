import unittest
from pathlib import Path

from modules.ai.resume_optimizer import (
    ResumeOptimizer,
    build_guided_keywords,
    calculate_keyword_score,
    infer_role_profile,
    load_skill_bank,
)


class ResumeOptimizerHelpersTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = load_skill_bank()

    def test_skill_bank_and_profiles_are_loaded(self):
        self.assertGreater(len(self.bank["keywords"]), 100)
        self.assertIn("Staff / Principal AI Platform", self.bank["profiles"])
        self.assertIn("Healthcare AI", self.bank["profiles"])

    def test_profile_inference_and_acronym_guidance(self):
        profile = infer_role_profile(
            "Staff AI Platform Engineer",
            "Build MCP services, Kubernetes infrastructure, evals and observability",
            self.bank["profiles"],
        )
        self.assertEqual(profile, "Staff / Principal AI Platform")
        keywords = build_guided_keywords(
            "Model Context Protocol (MCP), Kubernetes and Terraform",
            ["MCP", "Kubernetes"],
            "Staff AI Platform Engineer",
            ["Python"],
            self.bank,
            profile,
        )
        self.assertIn("Model Context Protocol (MCP)", keywords)

    def test_score_is_deterministic_and_acronym_aware(self):
        report = calculate_keyword_score(
            "Built MCP services with Kubernetes",
            ["Model Context Protocol (MCP)", "Kubernetes", "Terraform"],
            self.bank,
        )
        self.assertEqual(report["matched"], ["Model Context Protocol (MCP)", "Kubernetes"])
        self.assertEqual(report["missing"], ["Terraform"])

    def test_optimizer_preserves_skill_section_density(self):
        optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
        result = optimizer.optimize_skills(
            ["Python", "Legacy Tool", "React"],
            ["React", "Kubernetes"],
            "Kubernetes React",
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], "React")
        self.assertIn("Kubernetes", result)


class ResumeFormatVerifierTest(unittest.TestCase):
    def test_default_resume_passes_its_own_format_contract(self):
        root = Path(__file__).resolve().parents[1]
        docx = root / "all resumes/default/resume.docx"
        pdf = root / "all resumes/default/resume.pdf"
        if not docx.exists() or not pdf.exists():
            self.skipTest("default resume fixtures are not available")
        optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
        report = optimizer.verify_format(str(docx), str(docx), str(pdf), str(pdf), 2)
        self.assertTrue(report["passed"], report)


if __name__ == "__main__":
    unittest.main()
