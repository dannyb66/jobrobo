"""Synthetic hosted questions and fake AI: no personal documents, keys or network."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from modules.external_apply import SELECT_ANSWER_JS, apply_hosted_application, missing_required
from modules.external_questions import (
    QuestionConfigError, QuestionResolver, collect_questions, grounding_context,
    load_question_config, make_local_ai_answerer, normalize_label, validate_answer,
)
import test_external_apply as hosted


def question(label="Why this role?", kind="textarea", **extra):
    return {"label": label, "kind": kind, "required": True, "options": [], "name": "custom", **extra}


class ResolverTests(unittest.TestCase):
    def test_normalized_exact_question_answer_overrides_candidate_and_ai(self):
        calls = []
        config = {"candidate": {"city": "Candidate City"}, "answers": [{"question": "CURRENT CITY (required)", "type": "text", "answer": "Configured City"}], "ai": {"enabled": True}}
        resolver = QuestionResolver(config, {"city": "Legacy City"}, {"resume": "Synthetic evidence"}, lambda payload: calls.append(payload))
        result = resolver.resolve(question("Current city *", "text"), "ashby")
        self.assertEqual((result.value, result.source), ("Configured City", "question_config"))
        self.assertEqual(calls, [])
        self.assertEqual(normalize_label("What’s your focus? *"), normalize_label("WHAT'S YOUR FOCUS?"))

    def test_candidate_fallback_uses_explicit_fact_without_inferring_work_authorization(self):
        resolver = QuestionResolver(candidate={"require_visa": "No", "citizenship": "Non-citizen allowed to work for any employer"})
        result = resolver.resolve(question("Will you require sponsorship?", "radio", options=["Yes", "No"]), "lever")
        self.assertEqual((result.value, result.source), ("No", "candidate_config:require_visa"))
        self.assertFalse(resolver.resolve(question("Are you authorized to work in the US?", "radio", options=["Yes", "No"]), "lever").resolved)
        resolver.candidate["work_authorization"] = "Yes"
        self.assertTrue(resolver.resolve(question("Are you authorized to work in the US?", "radio", options=["Yes", "No"]), "lever").resolved)
        for label in ("Are you eligible to work night shifts?", "Are you authorized to work with confidential customer data?", "Do you require sponsorship for conference travel?"):
            self.assertFalse(resolver.resolve(question(label, "radio", options=["Yes", "No"]), "lever").resolved)

    def test_options_must_match_uniquely_and_types_are_not_coerced(self):
        for q, value in [(question(kind="radio", options=["Yes", "No"]), True), (question(kind="select", options=["Yes", "Yes *"]), "Yes"), (question(kind="checkbox"), "true"), (question(kind="multiselect", options=["Python"]), ["Rust"]), (question(kind="number", min="0", max="10"), "11"), (question(kind="date"), "tomorrow")]:
            with self.subTest(kind=q["kind"], value=value):
                with self.assertRaises(ValueError):
                    validate_answer(q, value)
        self.assertEqual(validate_answer(question(kind="multiselect", options=["Python", "TypeScript"]), ["python"]), ["Python"])

    def test_all_sensitive_unknowns_stay_manual_without_an_ai_call(self):
        calls = []
        labels = ["Citizenship status", "Do you require sponsorship?", "Work authorization", "Security clearance", "Veteran status", "Disability status", "Gender", "Criminal history", "Desired salary", "Availability", "Current employer", "Years of experience", "Graduation date", "Country", "Email"]
        resolver = QuestionResolver({"ai": {"enabled": True}}, context={"resume": "Synthetic project evidence", "job_description": "Infrastructure role"}, ai_answerer=lambda data: calls.append(data))
        for label in labels:
            with self.subTest(label=label):
                self.assertFalse(resolver.resolve(question(label), "greenhouse").resolved)
        self.assertFalse(resolver.resolve(question("Select one", "radio", options=["Male", "Female", "Decline"]), "ashby").resolved)
        self.assertEqual(calls, [])

    def test_personal_answer_and_exact_explicit_consent_are_allowed_but_not_inferred(self):
        config = {"answers": [{"question": "Work authorization", "type": "radio", "answer": "Yes"}, {"question": "I agree to the privacy policy", "type": "checkbox", "answer": True}]}
        resolver = QuestionResolver(config)
        self.assertEqual(resolver.resolve(question("Work authorization", "radio", options=["Yes", "No"]), "ashby").value, "Yes")
        self.assertTrue(resolver.resolve(question("I agree to the privacy policy", "checkbox"), "ashby").value)
        self.assertFalse(resolver.resolve(question("I agree to the privacy policy *", "checkbox"), "ashby").resolved)
        self.assertFalse(QuestionResolver(candidate={"consent": True}).resolve(question("I agree to the privacy policy", "checkbox"), "ashby").resolved)
        self.assertFalse(resolver.resolve(question("Policies", "radio", options=["I agree", "I decline"]), "ashby").resolved)
        self.assertEqual(QuestionResolver({"candidate": {"legal_signature": "Synthetic Signature"}}).resolve(question("Signature", "text"), "ashby").value, "Synthetic Signature")

    def test_ai_draft_is_grounded_typed_bounded_and_cites_candidate_evidence(self):
        calls = []
        def ai(payload):
            calls.append(payload)
            return {"answer": "I built a queue-backed API.", "source_ids": ["resume"], "manual_review": False}
        resolver = QuestionResolver({"ai": {"enabled": True}}, context={"resume": "Built a queue-backed API.", "job_description": "Build reliable infrastructure."}, ai_answerer=ai)
        result = resolver.resolve(question("Describe relevant project experience"), "ashby")
        self.assertTrue(result.resolved)
        self.assertEqual(result.source, "ai_draft:resume")
        self.assertNotIn("fields", calls[0]["question"])

    def test_ai_failure_uncertainty_hallucinated_options_sources_numbers_and_length_stay_manual(self):
        responses = [None, {"answer": "Draft", "source_ids": ["resume"], "manual_review": True}, {"answer": "Draft", "source_ids": ["missing"], "manual_review": False}, {"answer": "I built 100 APIs.", "source_ids": ["resume"], "manual_review": False}, {"answer": "x" * 1501, "source_ids": ["resume"], "manual_review": False}, {"answer": "I built an API.", "source_ids": ["job_description"], "manual_review": False}, {"answer": "I led Google cybersecurity and hold a Stanford doctorate.", "source_ids": ["resume"], "manual_review": False}]
        for response in responses:
            with self.subTest(response_type=type(response).__name__):
                resolver = QuestionResolver({"ai": {"enabled": True}}, context={"resume": "Built an API", "job_description": "Build infrastructure"}, ai_answerer=lambda payload: response)
                self.assertFalse(resolver.resolve(question("Describe project experience"), "lever").resolved)
        resolver = QuestionResolver({"ai": {"enabled": True}}, context={"resume": "Python"}, ai_answerer=lambda payload: {"answer": "Rust", "source_ids": ["resume"], "manual_review": False})
        self.assertFalse(resolver.resolve(question("Which technical area?", "select", options=["Python", "Java"]), "lever").resolved)
        self.assertFalse(resolver.resolve(question("Which technology have you used?", "select", options=["Python", "Rust"]), "lever").resolved)
        def failure(payload):
            raise RuntimeError("PRIVATE ANSWER AND KEY MUST NOT ESCAPE")
        resolver.ai_answerer = failure
        self.assertNotIn("PRIVATE", resolver.resolve(question(), "ashby").reason)

    def test_ai_never_uses_jd_as_candidate_evidence_and_honors_question_limit(self):
        calls = []
        resolver = QuestionResolver({"ai": {"enabled": True, "max_questions": 1}}, context={"job_description": "Build distributed systems"}, ai_answerer=lambda payload: calls.append(payload) or {"answer": "The systems mission interests me.", "source_ids": ["job_description"], "manual_review": False})
        self.assertFalse(resolver.resolve(question("Describe your experience"), "lever").resolved)
        self.assertEqual(calls, [])
        self.assertTrue(resolver.resolve(question("Why this role?"), "lever").resolved)
        self.assertFalse(resolver.resolve(question("Why this company?"), "lever").resolved)
        self.assertEqual(len(calls), 1)

    def test_ai_choice_cannot_borrow_jd_skills_and_hypotheticals_cannot_hide_personal_claims(self):
        config = {"ai": {"enabled": True}}
        context = {"resume": "Built Python APIs.", "job_description": "We use Rust."}
        resolver = QuestionResolver(config, context=context, ai_answerer=lambda payload: {"answer": "Rust", "source_ids": ["job_description"], "manual_review": False})
        self.assertFalse(resolver.resolve(question("Which technology have you used?", "select", options=["Python", "Rust"]), "lever").resolved)
        resolver.ai_answerer = lambda payload: {"answer": "I would bring my Google cybersecurity expertise.", "source_ids": ["resume"], "manual_review": False}
        self.assertFalse(resolver.resolve(question("Why should we hire you?"), "lever").resolved)
        resolver.ai_answerer = lambda payload: {"answer": "I would build Python APIs.", "source_ids": ["resume"], "manual_review": False}
        self.assertTrue(resolver.resolve(question("How would you approach this work?"), "lever").resolved)

    def test_ai_cannot_remove_negation_from_candidate_evidence(self):
        resolver = QuestionResolver({"ai": {"enabled": True}}, context={"resume": "Never built Python APIs."}, ai_answerer=lambda payload: {"answer": "I built Python APIs.", "source_ids": ["resume"], "manual_review": False})
        self.assertFalse(resolver.resolve(question("Why should we hire you?"), "lever").resolved)
        resolver.ai_answerer = lambda payload: {"answer": "Python", "source_ids": ["resume"], "manual_review": False}
        self.assertFalse(resolver.resolve(question("Which technology have you used?", "radio", options=["Python", "Rust"]), "lever").resolved)

    def test_duplicate_question_labels_require_explicit_control_name(self):
        fields = [{"id": key, "name": key, "type": "text", "label": "Profile URL", "visible": True} for key in ("a", "b")]
        questions = collect_questions(fields)
        resolver = QuestionResolver({"answers": [{"question": "Profile URL", "type": "text", "answer": "https://example.test"}]})
        self.assertTrue(all(not resolver.resolve(q, "lever").resolved for q in questions))
        resolver.config["answers"][0]["name"] = "a"
        self.assertTrue(resolver.resolve(questions[0], "lever").resolved)
        self.assertFalse(resolver.resolve(questions[1], "lever").resolved)

    def test_provider_specific_conflicts_and_wrong_live_type_require_manual_review(self):
        resolver = QuestionResolver({"answers": [{"question": "Focus", "type": "text", "answer": "AI", "provider": "lever"}]})
        self.assertFalse(resolver.resolve(question("Focus", "select", options=["AI"]), "lever").resolved)
        self.assertFalse(resolver.resolve(question("Focus", "text"), "ashby").resolved)
        resolver.config["answers"].append(dict(resolver.config["answers"][0]))
        self.assertFalse(resolver.resolve(question("Focus", "text"), "lever").resolved)

    def test_provider_scoped_answer_beats_wildcard_for_the_same_question(self):
        """A scoped entry is the disambiguation, not an extra conflict.

        Boilerplate labels differ between ATSs (one marks the label with a
        trailing glyph), so a wildcard entry and a provider-scoped entry for the
        same question are expected together and must not force manual review.
        """
        resolver = QuestionResolver({"answers": [
            {"question": "Authorized to work?", "type": "radio", "answer": "Yes"},
            {"question": "Authorized to work?", "type": "radio", "answer": "Yes", "provider": "lever"},
        ]})
        scoped = dict(question("Authorized to work?", "radio"), options=["Yes", "No"])
        resolve = resolver.resolve(scoped, "lever")
        self.assertTrue(resolve.resolved)
        self.assertEqual(resolve.value, "Yes")
        # Two entries for the same provider still conflict.
        resolver.config["answers"].append({"question": "Authorized to work?", "type": "radio",
                                           "answer": "No", "provider": "lever"})
        self.assertFalse(resolver.resolve(scoped, "lever").resolved)


class LocalAIConfigTests(unittest.TestCase):
    def test_missing_file_disabled_and_malformed_config_fails_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "answers.json"
            self.assertFalse(load_question_config(path)["ai"]["enabled"])
            for content in ["{", '{"version":2}', '{"version":1,"answers":{}}', '{"version":1,"answers":[{"question":"Q","type":"radio"}]}']:
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(QuestionConfigError):
                    load_question_config(path)

    def test_dedicated_local_key_only_no_shared_openai_environment_fallback(self):
        settings = {"enabled": True, "model": "synthetic-model"}
        self.assertIsNone(make_local_ai_answerer(settings, environ={"OPENAI_API_KEY": "not-an-authorized-feature-key"}))
        self.assertIsNone(make_local_ai_answerer(dict(settings, base_url="http://evil.example/v1"), environ={"JOBROBO_EXTERNAL_AI_API_KEY": "synthetic"}))
        self.assertIsNone(make_local_ai_answerer(dict(settings, enabled=False), environ={"JOBROBO_EXTERNAL_AI_API_KEY": "synthetic"}))
        self.assertIsNone(make_local_ai_answerer(dict(settings, api_key_env="OPENAI_API_KEY"), environ={"OPENAI_API_KEY": "legacy-cloud-key"}))
        self.assertIsNotNone(make_local_ai_answerer(dict(settings, api_key_env="OPENAI_API_KEY"), environ={"OPENAI_API_KEY": "legacy-cloud-key"}, original_local_env={"OPENAI_API_KEY": "synthetic-original-local-key"}))
        with tempfile.TemporaryDirectory() as directory:
            envfile = Path(directory) / "synthetic.env"
            envfile.write_text("OPENAI_API_KEY=synthetic-explicit-local-key\n")
            self.assertIsNotNone(make_local_ai_answerer(dict(settings, api_key_env="OPENAI_API_KEY", dotenv_file=str(envfile)), environ={"OPENAI_API_KEY": "legacy-cloud-key"}))

    def test_actual_client_contract_with_synthetic_local_key_and_json_response(self):
        seen = {}
        class Client:
            def __init__(self, **kwargs):
                seen.update(kwargs)
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def create(self, **kwargs):
                seen["request"] = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"answer":"Draft","source_ids":["resume"],"manual_review":false}'))])
        answer = make_local_ai_answerer({"enabled": True, "model": "synthetic-model"}, environ={"JOBROBO_EXTERNAL_AI_API_KEY": "synthetic-local-key"}, client_factory=Client)
        self.assertEqual(answer({"question": {"label": "Why?"}, "sources": {"resume": "Synthetic"}})["answer"], "Draft")
        self.assertEqual((seen["api_key"], seen["max_retries"], seen["request"]["max_completion_tokens"]), ("synthetic-local-key", 0, 650))
        self.assertEqual(seen["request"]["response_format"], {"type": "json_object"})

    def test_grounding_reads_only_supplied_synthetic_document(self):
        from docx import Document
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic.docx"
            document = Document(); document.add_paragraph("Built a synthetic queue API"); document.save(path)
            context = grounding_context(path, "User Information", "Synthetic summary", "Synthetic JD")
            self.assertIn("synthetic queue", context["resume"])
            resolver = QuestionResolver(context=context)
            self.assertNotIn("candidate_information", resolver.context)


class NativeElement(hosted.Element):
    def click(self):
        if self.data.get("type") in {"radio", "checkbox"}:
            if self.data["type"] == "radio":
                for item in self.browser.fields:
                    if item.get("name") == self.data.get("name"):
                        item["checked"] = False
            self.data["checked"] = not self.data.get("checked", False)
            self.actions.append("click")
        else:
            super().click()


class NativeBrowser(hosted.Browser):
    def add_field(self, *args, **kwargs):
        data = super().add_field(*args, **kwargs)
        data["element"] = NativeElement(data, self)
        return data
    def execute_script(self, script, *args):
        if script == SELECT_ANSWER_JS:
            element, labels = args
            for option in element.data["options"]:
                option["selected"] = option["label"] in labels and not option.get("disabled")
            selected = [option["label"] for option in element.data["options"] if option.get("selected")]
            element.data["value"] = selected[0] if selected else ""
            return selected
        return super().execute_script(script)


class NativeFormTests(unittest.TestCase):
    def setUp(self):
        # Reuse only synthetic setup/PDF helper, not the inherited baseline test methods.
        self.helper = hosted.HostedApplicationTests(methodName="test_discard_and_leave_open_do_not_submit")
        self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)
        self.browser = NativeBrowser()

    def apply(self, **kwargs):
        return apply_hosted_application(self.browser, self.browser.url, self.helper.applicant, self.helper.pdf,
                                        verify_pdf=lambda path: True, company="Example", title="Staff Platform Engineer", timeout=0,
                                        on_status=lambda result: None, **kwargs)

    def test_native_typed_controls_and_private_preview_across_three_providers(self):
        for provider in ("greenhouse", "lever", "ashby"):
            with self.subTest(provider=provider):
                self.browser = NativeBrowser(provider)
                text = self.browser.add_field("why", "textarea", True, "Why this role?")
                select = self.browser.add_field("focus", "select-one", True, "Engineering focus")
                select.update(tag="select", options=[{"label": "Choose", "value": ""}, {"label": "Infrastructure", "value": "infra"}, {"label": "Frontend", "value": "frontend"}])
                radios = [self.browser.add_field("preference", "radio", True, value) for value in ("Backend", "Frontend")]
                for radio in radios:
                    radio.update(group="preference", question="Which project area?", option_label=radio["label"], checked=False)
                checks = [self.browser.add_field("languages", "checkbox", True, value) for value in ("Python", "TypeScript")]
                for check in checks:
                    check.update(group="languages", question="Which languages?", option_label=check["label"], native_required=False, control_required=False, group_required=True, checked=False)
                single = self.browser.add_field("hands_on", "checkbox", False, "I have used Python")
                single["checked"] = False
                config = {"answers": [{"question": label, "type": kind, "answer": value} for label, kind, value in [
                    ("Why this role?", "textarea", "PRIVATE SYNTHETIC ANSWER"), ("Engineering focus", "select", "Infrastructure"),
                    ("Which project area?", "radio", "Backend"), ("Which languages?", "multiselect", ["Python"]), ("I have used Python", "checkbox", True)]]}
                preview = []
                result = self.apply(question_config=config, review=lambda details: preview.append(details) or "Submit application")
                self.assertEqual(result.status, "applied")
                self.assertEqual(text["value"], "PRIVATE SYNTHETIC ANSWER")
                self.assertEqual(select["value"], "Infrastructure")
                self.assertTrue(radios[0]["checked"] and not radios[1]["checked"])
                self.assertTrue(checks[0]["checked"] and not checks[1]["checked"])
                self.assertTrue(single["checked"])
                self.assertEqual(result.manual_questions, [])
                self.assertIn("PRIVATE SYNTHETIC ANSWER", json.dumps(preview))
                self.assertNotIn("PRIVATE SYNTHETIC ANSWER", json.dumps(result.to_dict()))

    def test_ai_draft_and_unresolved_legal_question_visible_but_no_submit(self):
        text = self.browser.add_field("why", "textarea", True, "Why this role?")
        authorization = self.browser.add_field("authorization", "text", True, "Work authorization")
        preview = []
        result = self.apply(question_config={"ai": {"enabled": True}}, question_context={"job_description": "Build reliable infrastructure"},
                            ai_answerer=lambda payload: {"answer": "The infrastructure mission interests me.", "source_ids": ["job_description"], "manual_review": False},
                            review=lambda details: preview.append(details) or "Submit application")
        self.assertEqual(result.status, "handoff")
        self.assertTrue(text["value"])
        self.assertEqual(authorization["value"], "")
        self.assertIn("Work authorization", result.manual_questions)
        self.assertEqual(self.browser.clicks, 0)
        self.assertTrue(any(item["source"].startswith("ai_draft:") for item in preview[0]["answer_preview"]))

    def test_no_review_never_clicks_and_existing_answer_avoids_ai(self):
        field = self.browser.add_field("why", "textarea", True, "Why this role?")
        field["value"] = "Existing operator answer"
        calls = []
        result = self.apply(question_config={"ai": {"enabled": True}}, question_context={"resume": "Synthetic"}, ai_answerer=lambda data: calls.append(data))
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual((field["value"], self.browser.clicks, calls), ("Existing operator answer", 0, []))

    def test_unsupported_combobox_and_unconfigured_consent_remain_manual(self):
        combo = self.browser.add_field("location", "text", True, "Location")
        combo["combobox"] = True
        consent = self.browser.add_field("consent", "checkbox", True, "I agree to the terms")
        result = self.apply(review=lambda details: "Submit application")
        self.assertEqual(result.status, "handoff")
        self.assertFalse(consent.get("checked"))
        self.assertIn("Location", result.manual_questions)
        self.assertEqual(self.browser.clicks, 0)

    def test_exact_configured_consent_is_checked_but_human_review_still_required(self):
        consent = self.browser.add_field("consent", "checkbox", True, "I agree to the terms")
        result = self.apply(question_config={"answers": [{"question": "I agree to the terms", "type": "checkbox", "answer": True}]})
        self.assertTrue(consent["checked"])
        self.assertEqual(result.status, "awaiting_review")
        self.assertEqual(self.browser.clicks, 0)

    def test_required_individual_checkbox_and_invalid_native_value_block_submission(self):
        fields = [{"visible": True, "type": "checkbox", "label": label, "required": True, "native_required": True, "group": "consents", "checked": checked} for label, checked in [("First", True), ("Second", False)]]
        self.assertEqual(missing_required(fields), ["Second"])
        field = self.browser.add_field("other_email", "email", False, "Other contact email")
        field.update(value="invalid email", valid=False)
        self.assertEqual(self.apply(review=lambda details: "Submit application").status, "handoff")
        self.assertEqual(self.browser.clicks, 0)

    def test_distinct_native_radio_names_sharing_container_do_not_bypass_required_question(self):
        a = self.browser.add_field("authorization", "radio", True, "Yes")
        b = self.browser.add_field("preference", "radio", False, "Backend")
        a.update(question="Authorization?", group="shared", native_required=False, valid=True, checked=False)
        b.update(question="Preference?", group="shared", native_required=False, valid=True, checked=True)
        self.assertEqual(len(collect_questions([a, b])), 2)
        self.assertIn("Authorization?", missing_required([a, b]))
        result = self.apply(review=lambda details: "Submit application")
        self.assertEqual(result.status, "handoff")
        self.assertEqual(self.browser.clicks, 0)

    def test_duplicate_identity_labels_are_not_filled_before_ambiguity_check(self):
        original = next(item for item in self.browser.fields if item["name"] == "email")
        original["label"] = "Email"
        reference = self.browser.add_field("reference_email", "text", True, "Email")
        result = self.apply()
        self.assertEqual((original["value"], reference["value"]), ("", ""))
        self.assertIn("Email", result.manual_questions)
        self.assertEqual(self.browser.clicks, 0)

    def test_individual_aria_required_checkboxes_do_not_become_one_group_requirement(self):
        fields = [{"visible": True, "type": "checkbox", "label": label, "question": "Policies", "required": True, "native_required": False, "control_required": True, "group_required": False, "valid": True, "group": "shared", "checked": checked} for label, checked in [("Privacy consent", True), ("Accuracy attestation", False)]]
        self.assertEqual(missing_required(fields), ["Policies"])


if __name__ == "__main__":
    unittest.main()
