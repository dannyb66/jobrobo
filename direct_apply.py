"""Prepare or submit job URLs and saved careers inventories using shared configuration."""
import argparse
import json
from pathlib import Path
import sys


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    validate = commands.add_parser('validate',help='Read-only job URL and application-input checks; no resumes or submissions')
    validation_source = validate.add_mutually_exclusive_group(required=True)
    validation_source.add_argument('--urls-file',help='TXT URLs or job JSON')
    validation_source.add_argument('--input',action='append',dest='inputs')
    validate.add_argument('--company',action='extend',nargs='+',metavar='NAME')
    validate.add_argument('--limit',type=positive)
    validate.add_argument('--check-inputs',action='store_true',help='Also verify candidate and resume-upload controls; render JavaScript pages if needed')
    validate.add_argument('--workers',type=positive,default=8,help='HTTP/API workers (default 8)')
    validate.add_argument('--browser-workers',type=positive,default=2,help='Isolated browser workers for --check-inputs (default 2)')
    validate.add_argument('--timeout',type=positive,default=12,help='HTTP/page timeout in seconds')
    validate.add_argument('--output-dir',default='logs/job-url-validation/phase1')
    validate.add_argument('--resume',action='store_true',help='Continue the same input/check mode; reuse verified results for up to six hours')
    validate.add_argument('--refresh',action='store_true',help='With --resume, recheck all URLs')
    validate.add_argument('--screenshots',action='store_true',help='Save browser-check screenshots')
    prepare = commands.add_parser("prepare", help="Prepare external job URLs with submission permanently disabled")
    urls = prepare.add_mutually_exclusive_group(required=True)
    urls.add_argument("--url", help="One external job posting URL")
    urls.add_argument("--urls-file", help="TXT URLs (one per line) or job JSON")
    urls.add_argument("--input", action="append", dest="inputs", help="TXT, job JSON, verified/ranked JSON or legacy queue; repeat to merge")
    prepare.add_argument('--db', help='Existing pipeline database for a saved verified-role set')
    prepare.add_argument('--role', action='append', default=[])
    prepare.add_argument('--limit', type=positive)
    prepare.add_argument("--config-dir", default=str(Path(__file__).resolve().parent / "config"))
    prepare.add_argument("--output-dir", default="logs/url_preparations")
    prepare.add_argument("--questions", help="Private typed per-question overrides")
    prepare.add_argument("--captcha-solver", action="store_true",
                         help="Clear vendor access challenges on employer pages (needs CAPTCHA_KRAKEN_API_KEY)")
    prepare.add_argument("--discovery-source", help="Actual source of this job URL, used only for referral-source questions")
    prepare.add_argument("--chrome-profile", help="Dedicated browser profile")
    prepare.add_argument("--leave-open", action="store_true", help="Keep the dedicated final draft open after saving evidence; close it before reusing its profile")
    prepare.add_argument("--grounded-resume", action="store_true", help="Deprecated compatibility flag; the shared LinkedIn resume optimizer JSON is used without overrides")
    submit = commands.add_parser('submit', help='Real application submission with durable progress and resume')
    source = submit.add_mutually_exclusive_group(required=True)
    source.add_argument('--url')
    source.add_argument('--urls-file', help='TXT URLs (one per line) or job JSON')
    source.add_argument('--input', action='append', dest='inputs')
    source.add_argument('--resume', dest='resume_dir', help='Existing submission run directory')
    submit.add_argument('--retry-failed', action='store_true', help='With --resume, retry eligible failures before submission; confirmed applications are skipped')
    submit.add_argument('--run-dir', help='Optional destination; an existing path gets a unique sibling. Omit for an automatic fresh run')
    submit.add_argument('--pause-before-submit', choices=('always','unknown','never'), default=None, help='Default always: fill separate tabs for manual Submit; resume keeps saved policy')
    submit.add_argument('--role', action='append', default=[])
    submit.add_argument('--company', action='extend', nargs='+', metavar='NAME',
                        help='Exact company names; accepts a list or repeated flags, ignoring case and surrounding whitespace; applied before the global --limit')
    submit.add_argument('--limit', type=positive)
    submit.add_argument('--max-applications', type=positive)
    history = submit.add_mutually_exclusive_group()
    history.add_argument('--history-root', help='Protect prior postings in this run directory root, including concurrent CLI claims')
    history.add_argument('--independent-run', action='store_true', help='Use an independent fresh run without a history scope; uncertain retry files still require reconciliation')
    submit.add_argument('--captcha-max-requests', type=positive, help='Maximum model requests per job across solver calls (default 36; saved on resume)')
    submit.add_argument('--workers', type=positive, help='Parallel isolated workers (local Chrome 1-16; Kernel 1-4; default 1)')
    submit.add_argument('--config-dir')
    submit.add_argument('--output-dir', help='Shared preparation/resume cache, default logs/url_preparations')
    submit.add_argument('--chrome-profile')
    submit.add_argument('--questions')
    submit.add_argument('--captcha-solver', action='store_true',
                        help='Clear vendor access challenges on employer pages (needs CAPTCHA_KRAKEN_API_KEY)')
    submit.add_argument('--discovery-source')
    submit.add_argument('--db')
    submit.add_argument('--ledger', help='Deprecated for submit; each run uses its own ledger')
    submit.add_argument('--set', dest='set_name')
    submit.add_argument('--output', dest='export_path', help='Applications StageResult JSON')
    for command in (prepare,submit):
        from modules.resume_provider import add_cli_arguments
        add_cli_arguments(command)
        command.add_argument('--browser',dest='browser_backend',choices=('local','kernel'),help='Browser backend; default local, resume retains its backend')
        command.add_argument('--browser-config',help='Optional browser_runtime.json configuration')
    reconcile = commands.add_parser('reconcile', help='Record an inspected uncertain outcome; never opens a browser')
    reconcile.add_argument('--run', dest='run_dir', required=True)
    reconcile.add_argument('--role', required=True, help='Exact job ID from progress.json')
    reconcile.add_argument('--outcome', choices=('applied','not-submitted'), required=True)
    reconcile.add_argument('--reason', required=True, help='Evidence from your manual inspection')
    review_resume = commands.add_parser("record-resume-review", help="Optionally record a completed visual PDF inspection; preparation does not require it")
    review_resume.add_argument("--report", required=True, help="Preparation report containing the generated resume")
    review_resume.add_argument("--pdf-sha256", required=True, help="SHA256 of the PDF you visually inspected")
    copy_resume = commands.add_parser('copy-resume', help='Copy a saved optimized PDF to Downloads using its recorded upload filename')
    copy_resume.add_argument('--url', required=True, help='Job posting or application URL')
    copy_resume.add_argument('--run-dir', help='Select a specific direct-submit run instead of the latest matching run')
    copy_resume.add_argument('--destination', default=str(Path.home() / 'Downloads'), help='Destination directory (default ~/Downloads)')
    copy_resume.add_argument('--config-dir', default=str(Path(__file__).resolve().parent / 'config'))
    plan = commands.add_parser("plan", help="Snapshot validated resumes and all verified roles; no browser or AI")
    plan.add_argument("--input", required=True, help="Versioned verified_roles JSON, optionally ranked")
    plan.add_argument("--queue", required=True)
    plan.add_argument("--source-docx", required=True)
    plan.add_argument("--source-pdf", required=True)
    plan.add_argument("--resume-mode", choices=("original", "optimized", "generated"), default="original")
    plan.add_argument("--optimized-map", help="Role ID to selected PDF/DOCX/match-report/JD hash JSON; missing selections remain handoffs")
    plan.add_argument("--expected-pages", type=positive, default=2)
    plan.add_argument("--freshness-days", type=positive, default=7)
    for command in ("run", "status", "export"):
        item = commands.add_parser(command)
        if command == 'status':
            target = item.add_mutually_exclusive_group(required=True)
            target.add_argument('--queue'); target.add_argument('--run', dest='run_dir')
        else:
            item.add_argument("--queue", required=True)
        if command == "run":
            item.add_argument("--execute", action="store_true", help="Open employer forms; every Submit still requires explicit application review")
            item.add_argument("--generate-resume", action="store_true", help="For a generated-mode queue, lazily generate one selected role's resume using the reviewed optimizer and local key; may incur API cost")
            item.add_argument("--role", action="append", default=[], help="Explicit role ID; repeat to select multiple queue rows")
            item.add_argument("--rewrite-all-bullets",action=argparse.BooleanOptionalAction,default=None)
            item.add_argument("--rewrite-experience-concurrency",type=int,choices=range(1,5),default=None)
            item.add_argument("--max-attempts", type=positive, default=1)
            item.add_argument("--max-applications", type=positive, default=1, help="Further restrict the configured per-run application cap")
            item.add_argument("--config-dir", default=str(Path(__file__).resolve().parent / "config"))
            item.add_argument("--questions", help="Private external-question JSON; defaults to external_questions_config_path")
            item.add_argument("--enable-question-ai", action="store_true", help="Also honor an explicitly enabled AI stanza in question JSON; never enables resume generation")
            item.add_argument("--ledger", help="Shared hosted ATS ledger; defaults to configured search_state_dir/external/applications.json")
            item.add_argument("--chrome-profile", help="Dedicated Chrome user-data directory; does not open your ordinary Chrome profile")
        if command == "export":
            item.add_argument("--output", required=True, help="Versioned applications StageResult with role/queue/resume provenance")
    return result


def _free_port():
    import socket
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def _port_is_bound(port):
    import socket
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def browser_factory(profile_path=None, *, debugger_address=None, worker_index=None):
    """Visible Chrome with a dedicated profile and a reattachable endpoint.

    Worker profiles are fresh directories, never copies of a running profile.
    Port allocation happens per creation so factories can be constructed safely
    before workers start. Retained browsers are attached without relaunching.
    """
    profile = Path(profile_path or Path.home() / "Library/Application Support/JobRobo/ChromeProfileDirect").expanduser().resolve()
    if worker_index is not None:
        if type(worker_index) is not int or worker_index < 1:
            raise ValueError('worker_index must be a positive integer')
        profile = profile.with_name(profile.name + f'-w{worker_index}')

    def create():
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
        if not debugger_address:
            profile.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            options = webdriver.ChromeOptions()
            port = None if debugger_address else _free_port()
            create.port = port
            if debugger_address:
                options.debugger_address = debugger_address
            else:
                if _port_is_bound(port):
                    if attempt == 0:
                        continue
                    raise OSError(f'Chrome debugging port {port} is already bound')
                options.add_argument("--user-data-dir=" + str(profile))
                options.add_argument(f"--remote-debugging-port={port}")
                options.add_argument("--remote-debugging-address=127.0.0.1")
                options.add_experimental_option("detach", True)
            try:
                driver = webdriver.Chrome(options=options)
            except WebDriverException as error:
                message = str(error).lower()
                collision = any(reason in message for reason in (
                    'address already in use', 'bind() failed', 'port is already in use'))
                if not debugger_address and attempt == 0 and collision and _port_is_bound(port):
                    continue
                raise
            address = getattr(driver, 'capabilities', {}).get('goog:chromeOptions', {}).get('debuggerAddress')
            if address:
                create.port = int(address.rsplit(':', 1)[1])
            create.debugger_address = address or debugger_address
            return driver

    create.port = None
    create.profile_path = str(profile)
    create.debugger_address = debugger_address
    return create


def main(argv=None):
    args = parser().parse_args(argv)
    from modules.resume_provider import cli_overrides, override_settings
    with override_settings(cli_overrides(args)):
        return _main(args)


def _main(args):
    from modules.direct_careers_apply import (export_applications, literal_config, load_queue, local_candidate,
                                               plan_queue, run_queue, summarize)
    try:
        if args.command == 'validate':
            from modules.generic_inputs import load_jobs
            from modules.job_url_validation import validate_jobs
            jobs=load_jobs(args.inputs or [args.urls_file],company=args.company,limit=args.limit,allow_invalid_urls=True)
            report=validate_jobs(jobs,output_dir=args.output_dir,check_inputs=args.check_inputs,
                                 workers=args.workers,browser_workers=args.browser_workers,timeout=args.timeout,
                                 resume=args.resume,refresh=args.refresh,screenshots=args.screenshots)
            print(json.dumps(report,indent=2))
            print('Open jobs: '+str(Path(args.output_dir).resolve()/'jobs-open.json'))
            print('Application inputs verified: '+str(Path(args.output_dir).resolve()/'jobs-apply-ready.json'))
            return 0 if report['complete'] else 1
        elif args.command == 'copy-resume':
            from modules.resume_export import copy_resume
            print(json.dumps(copy_resume(args.url, run_dir=args.run_dir,
                destination=args.destination, config_dir=args.config_dir), indent=2))
            return 0
        elif args.command == "record-resume-review":
            from modules.generic_prepare import record_resume_review
            record_resume_review(args.report, args.pdf_sha256)
            print('Recorded visual resume inspection; no browser or upload started.')
            return 0
        elif args.command == 'status' and args.run_dir:
            from modules.submit_state import status
            print(json.dumps(status(args.run_dir), indent=2)); return 0
        elif args.command == 'reconcile':
            from modules.submit_runner import reconcile_run
            print(json.dumps(reconcile_run(args.run_dir,args.role,outcome=args.outcome,reason=args.reason),indent=2))
            return 0
        elif args.command == 'submit':
            from modules.resume_provider import cli_overrides
            from modules.generic_inputs import load_jobs
            from modules.submit_runner import run_submissions
            if args.resume_dir and (args.role or args.limit or args.company is not None or args.history_root or args.independent_run):
                raise ValueError('Resume uses its saved selection; start a new run to change input roles/limit/company')
            if args.retry_failed and not args.resume_dir:
                raise ValueError('--retry-failed requires --resume RUN_DIR')
            jobs = None if args.resume_dir else load_jobs(args.inputs or ([args.urls_file] if args.urls_file else []),
                url=args.url, db_path=args.db, selected_roles=args.role, limit=args.limit, company=args.company)
            result = run_submissions(jobs,run_dir=args.run_dir,resume_dir=args.resume_dir,config_dir=args.config_dir,
                output_dir=args.output_dir,chrome_profile=args.chrome_profile,questions_path=args.questions,
                discovery_source=args.discovery_source,pause=args.pause_before_submit,max_applications=args.max_applications,
                workers=args.workers,
                set_name=args.set_name,export_path=args.export_path,db_path=args.db,ledger_path=args.ledger,
                browser_backend=args.browser_backend,browser_config=args.browser_config,retry_failed=args.retry_failed,
                captcha_solver=args.captcha_solver,history_root=args.history_root,
                independent_run=args.independent_run,captcha_max_requests=args.captcha_max_requests,
                resume_options=cli_overrides(args) or None)
            print(json.dumps(result,indent=2))
            from modules.submit_state import format_run_summary
            print(format_run_summary(result), flush=True)
            return 0 if all(j['status'] in {'applied','duplicate','discarded'} for j in result['jobs']) else 1
        elif args.command == "prepare":
            from modules.generic_prepare import run_preparations
            from modules.generic_inputs import load_jobs
            if args.captcha_solver:
                from modules import captcha_solver as solver
                solver.enable()
                ready, why = solver.available()
                if not ready:
                    raise ValueError(f'--captcha-solver is unavailable: {why}')
            urls = load_jobs(args.inputs or ([args.urls_file] if args.urls_file else []), url=args.url,
                db_path=args.db, selected_roles=args.role, limit=args.limit)
            results = run_preparations(urls, config_dir=args.config_dir, output_dir=args.output_dir,
                chrome_profile=args.chrome_profile, questions_path=args.questions, grounded_resume=args.grounded_resume,
                discovery_source=args.discovery_source, leave_open=args.leave_open,
                browser_backend=args.browser_backend,browser_config=args.browser_config)
            print(json.dumps({'submission_disabled': True, 'prepared': sum(r['status'] == 'prepared' for r in results),
                'attempted': len(results), 'summary': str(Path(args.output_dir).resolve() / 'summary.json')}, indent=2))
            return 0 if all(r['status'] == 'prepared' for r in results) else 1
        elif args.command == "plan":
            selected = json.loads(Path(args.optimized_map).expanduser().read_text(encoding="utf-8")) if args.optimized_map else None
            queue = plan_queue(args.input, args.queue, args.source_docx, args.source_pdf,
                               resume_mode=args.resume_mode, optimized_map=selected,
                               expected_pages=args.expected_pages, freshness_days=args.freshness_days)
        elif args.command == "run":
            if not args.execute:
                raise ValueError("Use --execute to open employer forms; plan/status do not run applications")
            config_dir = Path(args.config_dir).expanduser()
            settings = literal_config(config_dir / "settings.py")
            search = literal_config(config_dir / "search.py")
            search_profile = literal_config(config_dir / "search_profile.py")
            configured_limit = search.get("max_applications_per_run", 1)
            if configured_limit is not None and (type(configured_limit) is not int or configured_limit < 1):
                raise ValueError("Configured application cap must be positive or None")
            limit = min(args.max_applications, configured_limit) if configured_limit is not None else args.max_applications
            from modules.external_questions import load_question_config, review_answer_preview
            questions = load_question_config(args.questions or settings.get("external_questions_config_path", "~/.jobrobo/external-questions.json"))
            state = Path(search_profile.get("search_state_dir", "logs/search_runs")).expanduser()
            generate_override = None
            if args.rewrite_all_bullets is not None or args.rewrite_experience_concurrency is not None:
                from modules.direct_careers_apply import generate_local_resume
                def generate_override(**arguments):
                    return generate_local_resume(**arguments,rewrite_all_bullets=args.rewrite_all_bullets,
                        rewrite_experience_concurrency=args.rewrite_experience_concurrency)
            queue = run_queue(args.queue, execute=True, browser_factory=browser_factory(args.chrome_profile),
                              candidate=local_candidate(config_dir), review=review_answer_preview,
                              selected_role_ids=args.role, max_attempts=args.max_attempts, max_applications=limit,
                              question_config=questions, enable_question_ai=args.enable_question_ai,
                              generate_resumes=args.generate_resume, generate=generate_override,
                              ledger_path=args.ledger or state / "external/applications.json")
        elif args.command == "export":
            from modules.job_pipeline.models import write_artifact
            queue = load_queue(args.queue)
            write_artifact(export_applications(queue), args.output)
        else:
            queue = load_queue(args.queue)
        print(json.dumps(summarize(queue), indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        # Exceptions from provider/browser code are sanitized by the runner; this is local validation.
        print("direct_apply: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
