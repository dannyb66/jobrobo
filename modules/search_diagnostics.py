"""Search-only browser diagnostics, isolated from application history and quotas."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


def diagnostic_url(url):
    """Keep search intent; omit selected job and opaque tracking identifiers."""
    parsed = urlsplit(url)
    query = {key: value for key, value in parse_qs(parsed.query).items()
             if key in {"keywords", "geoId", "location", "start"} or key.startswith("f_")}
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), ""))


def run_diagnostic(bot, limit=5, output_path=None):
    """Run one deterministic configured query and read cards; never open a form.

    A diagnostic is deliberately not a run manifest or a pipeline stage. It does
    not invoke application preparation, credential bootstrap for AI, or ledgers.
    Only a browser constructed by this invocation is closed on completion.
    """
    from config import search, search_profile, settings, job_pipeline
    from modules.search_planner import build_search_plan
    from modules.linkedin_search import prepare_search
    from modules.linkedin_modern_search import get_search_cards, read_search_card

    if type(limit) is not int or limit < 1:
        raise ValueError("Diagnostic limit must be a positive integer")
    target = Path(output_path).expanduser().resolve() if output_path else (
        Path(tempfile.mkdtemp(prefix="jobrobo-search-diagnostics-")) / "results.json")
    state_dir = Path(search_profile.search_state_dir).expanduser().resolve()
    if target == state_dir or state_dir in target.parents:
        raise ValueError("Diagnostic output must be outside the application run-manifest directory")
    ledgers = {Path(value).expanduser().resolve() for value in (
        settings.file_name, settings.failed_file_name, job_pipeline.db_path,
    ) if value}
    if target in ledgers:
        raise ValueError("Diagnostic output must not overwrite application or pipeline history")
    target.parent.mkdir(parents=True, exist_ok=True)
    report = {"diagnostic": "linkedin_search", "started_at": datetime.now(timezone.utc).isoformat(),
              "limit": limit, "query_id": None, "query_text": None, "search": {},
              "cards": [], "errors": [], "output_path": str(target)}
    screenshot = target.with_name(target.name + ".png")
    original_driver = bot.driver
    original_pause = getattr(bot, "pause_after_filters", None)
    created_driver = None
    try:
        profile = dict(vars(search_profile), ai_query_refinement_enabled=False)
        specs = build_search_plan(profile, vars(search))
        if not specs:
            raise ValueError("No configured searches are enabled")
        spec = specs[0]
        report.update(query_id=spec.query_id, query_text=spec.query_text)
        with redirect_stdout(sys.stderr):
            bot.load_runtime("search")
            bot.pause_after_filters = False
            browser = bot.initialize_browser(background=False)
            if browser is not original_driver:
                created_driver = browser
                browser.set_page_load_timeout(30)
            result = prepare_search(browser, spec, bot.wait_for_search, bot.wait_for_search_results,
                                    classic_filter_callback=bot.apply_filters)
            report["search"] = result.diagnostics()
            report["search"]["mode"] = result.mode
            report["search"]["warnings"] = list(result.warnings)
            report["search"]["fallback_reason"] = result.fallback_reason
            report["search"]["url"] = diagnostic_url(browser.current_url)
            seen = set()
            for card in get_search_cards(browser):
                metadata = read_search_card(card)
                metadata = {key: value for key, value in metadata.items()
                            if key in {"job_id", "id", "title", "company", "location", "workplace_type",
                                       "work_style", "link", "url", "applied", "easy_apply"}}
                identity = metadata.get("job_id") or metadata.get("id")
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                report["cards"].append(metadata)
                if len(report["cards"]) >= limit:
                    break
            if browser.save_screenshot(str(screenshot)):
                report["screenshot"] = str(screenshot)
    except Exception as error:
        report["errors"].append({"code": type(error).__name__, "message": str(error)})
        evidence = getattr(error, "diagnostics", None)
        if callable(evidence):
            evidence = evidence()
        if isinstance(evidence, dict):
            report["search"].update(evidence)
        if created_driver is not None:
            try:
                report["search"]["url"] = diagnostic_url(created_driver.current_url)
                if created_driver.save_screenshot(str(screenshot)):
                    report["screenshot"] = str(screenshot)
            except Exception:
                pass
    finally:
        bot.pause_after_filters = original_pause
        if created_driver is not None:
            try:
                created_driver.quit()
            except Exception as error:
                report["errors"].append({"code": type(error).__name__, "message": "Diagnostic browser cleanup failed"})
            finally:
                if bot.driver is created_driver:
                    bot.driver = bot.wait = bot.actions = None
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report
