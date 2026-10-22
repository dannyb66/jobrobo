"""Composable, persisted job pipeline. Bare invocation shows help without Chrome."""

import argparse
import json
import sys
from pathlib import Path

from modules.job_pipeline.models import LinkedInRunRequest, StageResult, write_artifact


def _positive(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _nonnegative(value):
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a nonnegative integer; 0 disables the target") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be a nonnegative integer; 0 disables the target")
    return number


def build_parser():
    from config import job_pipeline as config

    parser = argparse.ArgumentParser(description="Discover companies, verify and rank careers, then apply directly or search/apply on LinkedIn.")
    verbs = parser.add_subparsers(dest="verb")
    groups = {}
    for verb, noun in (("discover", "companies"), ("verify", "careers"), ("rank", "careers"),
                       ("search", "linkedin"), ("apply", "linkedin"), ("run", "linkedin"), ("apply", "careers")):
        if verb not in groups:
            parent = verbs.add_parser(verb)
            groups[verb] = parent.add_subparsers(dest="target", required=True)
        commands = groups[verb]
        command = commands.add_parser(noun)
        command.add_argument("--input", action="append", default=[], metavar="JSON_OR_SET", help="Versioned stage JSON or saved input set; repeat to merge")
        command.add_argument("--set", dest="set_name", default=None if (verb,noun)==('apply','careers') else config.default_set, help="Cumulative output set name")
        command.add_argument("--output", dest="output_path", help="Export a portable versioned StageResult JSON")
        limit_field = {"discover": "discovery_limit_per_source", "verify": "verification_limit_companies"}.get(verb)
        stage_limit = getattr(config, limit_field, config.default_limit) if limit_field else config.default_limit
        if verb != "rank":
            direct_careers = (verb,noun)==('apply','careers')
            command.add_argument("--limit", type=_positive, default=None if limit_field or direct_careers else stage_limit,
                                 help="Maximum selected direct jobs (default: all selected)" if direct_careers else f"Maximum records/companies/jobs processed this invocation (configured default: {stage_limit})")
        command.add_argument("--db", dest="db_path", default=None if (verb,noun)==('apply','careers') else config.db_path, help="SQLite pipeline store")
        if verb == 'apply' and noun == 'careers':
            command.add_argument('--run-dir')
            command.add_argument('--resume', dest='resume_dir')
            command.add_argument('--pause-before-submit', choices=('always','unknown','never'))
            command.add_argument('--role', action='append', default=[])
            command.add_argument('--max-applications', type=_positive)
            command.add_argument('--config-dir')
            command.add_argument('--chrome-profile')
            command.add_argument('--browser',dest='browser_backend',choices=('local','kernel'))
            command.add_argument('--browser-config')
        if verb in {"discover", "verify"}:
            stage = "discovery" if verb == "discover" else "verification"
            command.add_argument("--refresh", action=argparse.BooleanOptionalAction,
                                 default=None,
                                 help=f"Restart saved stage checkpoints (default follows {stage}_refresh); --no-refresh preserves progress")
            command.add_argument("--render-public", dest="render_enabled", action=argparse.BooleanOptionalAction,
                                 default=None, help=f"Allow bounded public-page rendering (default follows {stage}_render_enabled)")
        elif verb in {"search", "run"}:
            command.add_argument("--refresh", action="store_true", help="Refresh discovery/verification/search checkpoints; application history stays intact")
        if verb == "discover":
            command.add_argument("--source", action="append", choices=["greylock", "sequoia", "a16z", "yc", "hn", "hiringcafe", "wellfound", "crunchbase", "import"],
                                 help="Select sources; repeat to combine. 'import' only imports --input")
            command.add_argument("--target-companies", type=_nonnegative, default=None,
                                 help="Cumulative company target for this set; 0 disables it (default follows discovery_target_companies)")
        elif verb == "verify":
            command.add_argument("--prioritize-established", action=argparse.BooleanOptionalAction, default=None,
                                 help="Verify established companies first (default follows verification_prioritize_established)")
        if verb in {"verify", "rank"}:
            command.add_argument("--resume", dest="resume_path", help="Local original DOCX/PDF/text resume for optional lexical review affinity; never an ATS score")
        if verb == "rank":
            command.add_argument("--as-of", help="ISO timestamp with timezone for reproducible posting-age buckets; default now")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verb is None:
        parser.print_help()
        return 0
    if args.set_name is not None and not args.set_name.strip():
        parser.error("--set must be nonempty")
    try:
        if args.verb == "discover":
            from modules.job_pipeline.service import discover_companies
            sources = None if args.source is None else [value for value in args.source if value != "import"]
            if args.source == ["import"] and not args.input:
                parser.error("--source import requires --input")
            options = {"sources": sources, "refresh": args.refresh}
            if args.target_companies is not None:
                options["target_companies"] = args.target_companies
            if args.render_enabled is not None:
                options["render_enabled"] = args.render_enabled
            result = discover_companies(args.input, args.set_name, args.limit, args.db_path,
                                        **options)
        elif args.verb == "verify":
            from modules.job_pipeline.service import verify_careers
            options = {"refresh": args.refresh}
            if args.render_enabled is not None:
                options["render_enabled"] = args.render_enabled
            if args.prioritize_established is not None:
                options["prioritize_established"] = args.prioritize_established
            if args.resume_path is not None:
                options["resume_path"] = args.resume_path
            result = verify_careers(args.input, args.set_name, args.limit, args.db_path, **options)
        elif args.verb == "rank":
            from modules.job_pipeline.service import rank_careers
            result = rank_careers(args.input, args.set_name, args.db_path, args.resume_path, args.as_of)
        elif args.verb == 'apply' and args.target == 'careers':
            from modules.generic_inputs import load_jobs
            from modules.submit_runner import run_submissions
            from config import job_pipeline as pipeline_config
            if args.resume_dir and (args.input or args.role or args.limit):
                raise ValueError('Resume uses the saved selection; omit new inputs/roles/limit')
            database = args.db_path or (None if args.resume_dir else pipeline_config.db_path)
            jobs = None if args.resume_dir else load_jobs(args.input,db_path=database,selected_roles=args.role,limit=args.limit)
            progress = run_submissions(jobs,run_dir=args.run_dir,resume_dir=args.resume_dir,
                pause=args.pause_before_submit,max_applications=args.max_applications,config_dir=args.config_dir,
                chrome_profile=args.chrome_profile,set_name=args.set_name,export_path=args.output_path,db_path=database,
                browser_backend=args.browser_backend,browser_config=args.browser_config)
            from modules.job_pipeline.models import read_artifact
            result = read_artifact(progress['options'].get('export_path') or Path(progress['run_dir'])/'applications.json')
        else:
            from modules.job_pipeline.service import load_inputs
            from modules.job_pipeline.store import PipelineStore
            expected_stage = "linkedin_jobs" if args.verb == "apply" else "verified_roles"
            with PipelineStore(args.db_path) as store:
                artifacts = load_inputs(store, args.input, expected_stage)
            request = LinkedInRunRequest(
                mode="search-and-apply" if args.verb == "run" else args.verb,
                input_sets=[artifact.to_dict() for artifact in artifacts], set_name=args.set_name,
                output_path=args.output_path, limit=args.limit, db_path=args.db_path,
                refresh=getattr(args, "refresh", False),
            )
            from runAiBot import run_pipeline
            result = run_pipeline(request)
        result = StageResult.from_dict(result)
        if args.output_path and not (args.verb == 'apply' and args.target == 'careers'):
            write_artifact(result, args.output_path)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 1 if result.errors else 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"job_pipeline: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
