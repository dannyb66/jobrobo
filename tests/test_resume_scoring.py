"""Synthetic regressions for transparent lexical coverage and mention provenance."""

import unittest
import json
from types import SimpleNamespace

from modules.resume_scoring import keyword_provenance, score_keywords
from modules.ai.resume_optimizer import ResumeOptimizer, build_guided_keywords, calculate_keyword_score


class LexicalCoverageTest(unittest.TestCase):
    def test_public_wrapper_preserves_result_keys(self):
        self.assertEqual(calculate_keyword_score("Python", ["Python", "Go"]), {
            "score": 50.0, "matched": ["Python"], "missing": ["Go"], "total": 2,
        })

    def test_java_is_not_javascript(self):
        self.assertEqual(score_keywords("Built JavaScript services", ["Java"])["score"], 0)
        self.assertEqual(score_keywords("Built Java services", ["Java"])["score"], 100)

    def test_rag_is_not_inside_storage_or_drag(self):
        self.assertEqual(score_keywords("Storage and drag controls", ["RAG"])["matched"], [])
        self.assertEqual(score_keywords("Built RAG retrieval", ["RAG"])["matched"], ["RAG"])

    def test_short_language_go_is_not_inside_django(self):
        self.assertEqual(score_keywords("Django API", ["Go"])["matched"], [])

    def test_language_suffixes_stay_distinct(self):
        for text, wanted in (("C++", "C"), ("C#", "C"), ("C", "C++"), ("C#", "C++")):
            with self.subTest(text=text, wanted=wanted):
                self.assertEqual(score_keywords(text, [wanted])["score"], 0)
        self.assertEqual(score_keywords("Used C++ and C#", ["C++", "C#"])["score"], 100)

    def test_punctuation_and_unicode_whitespace_are_phrase_separators(self):
        self.assertEqual(score_keywords("CI/CD; retrieval-augmented\ngeneration", [
            "CI/CD", "Retrieval Augmented Generation",
        ])["score"], 100)
        self.assertEqual(score_keywords("Ｐｙｔｈｏｎ", ["Python"])["score"], 100)

    def test_exact_duplicates_do_not_inflate_score(self):
        report = score_keywords("Used Python", ["Python", " Python ", "PYTHON", "Go"])
        self.assertEqual(report["score"], 50)
        self.assertEqual(report["total"], 2)

    def test_proven_acronym_aliases_count_once(self):
        full = "Model Context Protocol (MCP)"
        report = score_keywords("MCP services", ["MCP", full, "Terraform"])
        self.assertEqual(report, {"score": 50.0, "matched": [full], "missing": ["Terraform"], "total": 2})

    def test_proven_plural_acronym_retains_singular_source_provenance(self):
        full = "Large Language Models (LLMs)"
        self.assertEqual(score_keywords("Built LLM tools", [full])["score"], 100)
        self.assertEqual(keyword_provenance("LLM", full, [full])["introduced_terms"], [])

    def test_expanded_phrase_matches_without_acronym_present(self):
        report = score_keywords("Model Context Protocol services", ["Model Context Protocol (MCP)"])
        self.assertEqual(report["score"], 100)

    def test_multiple_proven_aliases_merge_existing_groups(self):
        report = score_keywords("MCP tooling", ["MCP", "MCPs", "Model Context Protocol (MCP) (MCPs)"])
        self.assertEqual(report["total"], 1)

    def test_parenthetical_context_is_not_an_alias(self):
        for text in ("Infrastructure tooling", "AWS services"):
            self.assertEqual(score_keywords(text, ["Infrastructure (AWS)"])["score"], 0)
        self.assertEqual(score_keywords("Infrastructure (AWS)", ["Infrastructure (AWS)"])["score"], 100)

    def test_ambiguous_acronym_does_not_prove_two_expansions(self):
        report = score_keywords("MCP", ["Model Context Protocol (MCP)", "Master Control Program (MCP)"])
        self.assertEqual(report["score"], 0)
        self.assertEqual(report["total"], 2)

    def test_core_weight_counts_concept_once(self):
        bank = {"keywords": [{"keyword": "Model Context Protocol (MCP)", "tier": "Core"}]}
        report = score_keywords("MCP", ["MCP", "Model Context Protocol (MCP)", "Python"], bank)
        self.assertEqual(report["score"], 66.7)
        self.assertEqual(report["total"], 2)

    def test_empty_keywords_do_not_fabricate_coverage(self):
        self.assertEqual(score_keywords("Python", ["", " () "]), {
            "score": 0.0, "matched": [], "missing": [], "total": 0,
        })

    def test_repetition_in_document_does_not_raise_coverage(self):
        self.assertEqual(score_keywords("Python " * 100, ["Python", "Go"])["score"], 50)


class MentionProvenanceTest(unittest.TestCase):
    def test_source_alias_retains_expanded_output_without_new_skill_claim(self):
        report = keyword_provenance("Built MCP tools", "Built Model Context Protocol tools", ["Model Context Protocol (MCP)"])
        self.assertEqual(report["introduced_terms"], [])
        self.assertEqual(report["retained_terms"], ["Model Context Protocol (MCP)"])
        self.assertEqual(report["details"][0]["source_mentions"][0]["variant"], "mcp")

    def test_new_removed_and_absent_terms_are_separate(self):
        report = keyword_provenance("Python services", "Python and AWS services", ["Python", "AWS", "Java", "Go"])
        self.assertEqual(report["introduced_terms"], ["AWS"])
        self.assertEqual(report["retained_terms"], ["Python"])
        self.assertEqual(report["absent_terms"], ["Java", "Go"])
        removed = keyword_provenance("Python Java", "Python", ["Java"])
        self.assertEqual(removed["removed_terms"], ["Java"])

    def test_substring_does_not_satisfy_source_provenance(self):
        report = keyword_provenance("JavaScript storage", "Java RAG", ["Java", "RAG"])
        self.assertEqual(report["introduced_terms"], ["Java", "RAG"])

    def test_textual_mentions_are_explicitly_not_factual_verification(self):
        report = keyword_provenance("No AWS experience", "AWS", ["AWS"])
        self.assertFalse(report["facts_verified"])
        self.assertIn("negated", report["interpretation"])
        self.assertEqual(report["retained_terms"], ["AWS"])

    def test_evidence_is_bounded_and_deterministic(self):
        report = keyword_provenance("Python " * 100, "Python", ["Python"])
        self.assertLessEqual(len(report["details"][0]["source_mentions"]), 3)
        self.assertEqual(report, keyword_provenance("Python " * 100, "Python", ["Python"]))


class GroundedSkillsTest(unittest.TestCase):
    def setUp(self):
        self.optimizer = ResumeOptimizer.__new__(ResumeOptimizer)

    def test_unsupported_jd_terms_cannot_displace_existing_source_skills(self):
        original = ["Python", "Django", "Storage"]
        result = self.optimizer.optimize_skills(original, ["Go", "Java", "RAG", "Scala", "Service Mesh"],
                                                "Go Java RAG Scala Service Mesh")
        self.assertEqual(result, original)

    def test_one_serving_tool_cannot_prove_a_compound_tool_stack(self):
        compound = "Inference Serving (vLLM, SGLang, TensorRT-LLM, TGI)"
        result = self.optimizer.optimize_skills(["vLLM", "Python"], [compound], compound)
        self.assertNotIn(compound, result)
        self.assertEqual(result, ["vLLM", "Python"])

    def test_bank_status_and_model_extraction_do_not_prove_candidate_experience(self):
        bank = {"keywords": [{"keyword": "Scala", "tier": "Core", "status": "Verified"},
                             {"keyword": "Service Mesh", "tier": "Core", "status": ""}]}
        keywords = build_guided_keywords("Scala Service Mesh", ["Scala"], "Engineer", ["Python"], bank, "", True)
        self.assertIn("Scala", keywords)
        self.assertIn("Service Mesh", keywords)
        self.assertEqual(self.optimizer.optimize_skills(["Python"], keywords, "Scala Service Mesh"), ["Python"])

    def test_source_project_can_support_a_keyword_absent_from_original_skills(self):
        result = self.optimizer.optimize_skills(["Python", "Django"], ["vLLM", "SGLang"], "vLLM SGLang",
                                                source_text="SKILLS Python, Django. PROJECT Built a vLLM server.")
        self.assertIn("vLLM", result)
        self.assertNotIn("SGLang", result)
        diagnostic = self.optimizer.last_skills_grounding
        self.assertIn("vLLM", diagnostic["supported_keywords"])
        self.assertIn("SGLang", diagnostic["blocked_keywords"])
        self.assertFalse(diagnostic["facts_verified"])
        self.assertTrue(next(item for item in diagnostic["details"] if "vLLM" in item["input_terms"])["source_mentions"])

    def test_proven_source_acronym_can_use_full_jd_phrase(self):
        full = "Retrieval-Augmented Generation (RAG)"
        result = self.optimizer.optimize_skills(["RAG", "Python"], [full], full)
        self.assertEqual(result, [full, "Python"])
        self.assertEqual(self.optimizer.last_skills_grounding["blocked_keywords"], [])

    def test_context_parentheses_cannot_be_inferred_from_a_component(self):
        result = self.optimizer.optimize_skills(["AWS", "Python"], ["Infrastructure (AWS)"], "Infrastructure AWS")
        self.assertEqual(result, ["AWS", "Python"])

    def test_ambiguous_acronym_cannot_introduce_two_expansions(self):
        expansions = ["Model Context Protocol (MCP)", "Master Control Program (MCP)"]
        result = self.optimizer.optimize_skills(["MCP", "Python"], expansions, "MCP")
        self.assertEqual(result, ["MCP", "Python"])
        self.assertEqual(self.optimizer.last_skills_grounding["blocked_keywords"], expansions)

    def test_supported_terms_still_respect_skill_capacity_and_max_count(self):
        result = self.optimizer.optimize_skills(["Python", "AWS", "React"], ["AWS", "Python"], "AWS Python", max_count=2)
        self.assertEqual(result, ["AWS", "Python"])

    def test_keyword_gaps_remain_visible_instead_of_being_inserted(self):
        keywords = ["Python", "Scala"]
        result = self.optimizer.optimize_skills(["Python", "Django"], keywords, "Scala Python")
        report = score_keywords(", ".join(result), keywords)
        self.assertEqual(report["missing"], ["Scala"])
        self.assertEqual(report["score"], 50)

    def test_length_failure_identifies_indices_and_counts_without_raw_bullet_or_identity(self):
        original = {"company": "Synthetic private company", "job_title": "Synthetic private role", "bullets": ["Built API"]}
        replacement = "Unacceptably long synthetic candidate sentence"
        content = json.dumps({"rewritten_experience": [dict(original, bullets=[replacement])]})
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        self.assertEqual(self.optimizer._parse_openai_response(response, [original]), [original])
        error = self.optimizer.last_bullet_rewrite_error
        self.assertIn("Entry 1, bullet 1", error)
        self.assertIn(str(len(replacement)) + " characters; maximum " + str(len(original["bullets"][0])), error)
        for private_text in (replacement, original["company"], original["job_title"]):
            self.assertNotIn(private_text, error)


if __name__ == "__main__":
    unittest.main()
