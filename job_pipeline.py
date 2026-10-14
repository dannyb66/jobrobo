"""Composable, persisted job pipeline. Bare invocation shows help without Chrome."""

import argparse
import json
import sys

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

    parser = argparse.ArgumentParser(description="Discover companies, verify careers, then search or apply on LinkedIn.")
    verbs = parser.add_subparsers(dest="verb")
    for verb, noun in (("discover", "companies"), ("verify", "careers"),
                       ("search", "linkedin"), ("apply", "linkedin"), ("run", "linkedin")):
        parent = verbs.add_parser(verb)
        commands = parent.add_subparsers(dest="target", required=True)
        command = commands.add_parser(noun)
        command.add_argument("--input", action="append", default=[], metavar="JSON_OR_SET", help="Versioned stage JSON or saved input set; repeat to merge")
        command.add_argument("--set", dest="set_name", default=config.default_set, help="Cumulative output set name")
        command.add_argument("--output", dest="output_path", help="Export a portable versioned StageResult JSON")
        limit_field = {"discover": "discovery_limit_per_source", "verify": "verification_limit_companies"}.get(verb)
        stage_limit = getattr(config, limit_field, config.default_limit) if limit_field else config.default_limit
        command.add_argument("--limit", type=_positive, default=None if limit_field else stage_limit,
                             help=f"Maximum records/companies/jobs processed this invocation (configured default: {stage_limit})")
        command.add_argument("--db", dest="db_path", default=config.db_path, help="SQLite pipeline store")
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
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verb is None:
        parser.print_help()
        return 0
    if not args.set_name.strip():
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
            result = verify_careers(args.input, args.set_name, args.limit, args.db_path, **options)
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
        if args.output_path:
            write_artifact(result, args.output_path)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 1 if result.errors else 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"job_pipeline: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
