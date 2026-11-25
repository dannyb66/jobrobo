"""Compose or send the faculty outreach drafts through Gmail in the JobRobo profile."""
import argparse
import sys

from modules import outreach_mail


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def seconds(value):
    parts = [float(part) for part in str(value).split("-", 1)]
    if len(parts) == 1:
        parts.append(parts[0])
    if min(parts) < 0 or parts[0] > parts[1]:
        raise argparse.ArgumentTypeError("use SECONDS or MIN-MAX with MIN <= MAX")
    return tuple(parts)


def parser():
    result = argparse.ArgumentParser(
        description=__doc__, allow_abbrev=False,
        epilog="Always dry-run a batch first; a dry run sends nothing.")
    result.add_argument("--source", default=outreach_mail.DEFAULT_SOURCE,
                        help="Draft JSON ledger (default: the Task 7 faculty ledger)")
    result.add_argument("--from-html", help="Also import the review HTML and report drift from JSON")
    result.add_argument("--dry-run", action="store_true",
                        help="Compose and verify each draft, then discard it")
    result.add_argument("--limit", type=positive, default=25, help="Messages this run (default 25)")
    result.add_argument("--start", type=positive, default=1, help="1-based draft position to start at")
    result.add_argument("--only", action="append", default=[], metavar="DRAFT_ID",
                        help="Send exactly this draft id; repeatable, ignores --limit/--start")
    result.add_argument("--attach", metavar="PDF", help="Attach this PDF to every message in the run")
    result.add_argument("--no-attach", action="store_true",
                        help="Send without an attachment; removes the 'I have attached my research "
                             "resume.' sentence from each body")
    result.add_argument("--no-contact", action="store_true",
                        help="Do not add the phone/LinkedIn lines copied from the Gmail signature")
    result.add_argument("--delay", type=seconds, default=outreach_mail.DEFAULT_DELAY, metavar="SECONDS",
                        help="Pause between messages as SECONDS or MIN-MAX, e.g. 10 or 5-20 "
                             "(default 0-30)")
    result.add_argument("--logs", default="logs/outreach", help="Run output root")
    result.add_argument("--seed", type=int, help="Fix the random pacing for repeatable runs")
    result.add_argument("--include-held", action="store_true",
                        help="Allow held drafts, only when also named with --only")
    result.add_argument("--from", dest="expected_from", metavar="EMAIL",
                        help="Abort unless Gmail is signed in as this address")
    result.add_argument("--open-chrome", action="store_true",
                        help="Open the JobRobo Chrome profile at Gmail with a debug port, then exit")
    result.add_argument("--write-remaining", metavar="PATH",
                        help="Write the source drafts minus those recorded as sent to PATH, then exit")
    result.add_argument("--verify", metavar="RUN",
                        help="Re-check a past send run in Gmail Sent (run id, run folder or 'latest'), then exit")
    result.add_argument("--import-html", nargs=2, metavar=("HTML", "OUT_JSON"),
                        help="Convert a review page with embedded COPIES data into a draft JSON, then exit")
    result.add_argument("--exclude", action="append", default=[], metavar="DRAFT_ID_OR_EMAIL",
                        help="Permanently drop a draft (by id or recipient address); repeatable, then exit")
    result.add_argument("--requeue", metavar="RUN",
                        help="Put sends that --verify found missing from Gmail back in the queue, then exit")
    result.add_argument("--no-verify", action="store_true",
                        help="Skip the automatic Gmail Sent check after a real batch")
    result.add_argument("--check", action="store_true",
                        help="Read-only draft and ledger checks; no browser")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.open_chrome:
        try:
            address, started = outreach_mail.open_chrome_window(outreach_mail.profile_path())
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        print(f"{'Opened' if started else 'Already open:'} JobRobo Chrome at {address}. "
              "Sign in to Gmail there if needed and keep the window open while sending.")
        return 0
    if args.verify:
        try:
            summary = outreach_mail.verify_run(args.verify, logs_root=args.logs)
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        return 0 if summary["verdict"] == "BATCH VERIFIED" else 1
    if args.import_html:
        html_path, out_path = args.import_html
        try:
            drafts = outreach_mail.drafts_from_copies_html(html_path)
            target = outreach_mail.write_drafts_file(drafts, out_path, html_path)
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        held = [d["draft_id"] for d in drafts if d["readiness"].startswith("Hold")]
        print(f"wrote {len(drafts)} draft(s) to {target}; {len(held)} held: {', '.join(held) or 'none'}")
        return 0
    if args.exclude:
        try:
            dropped = outreach_mail.exclude(args.exclude, args.source, args.logs)
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        print(f"excluded {', '.join(dropped)}; they will never be sent and are dropped from "
              "--write-remaining files")
        return 0
    if args.requeue:
        try:
            requeued = outreach_mail.requeue_missing(args.requeue, logs_root=args.logs)
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        print(f"requeued {len(requeued)} draft(s): {', '.join(requeued) or 'none'}")
        return 0
    if args.write_remaining:
        try:
            kept, dropped = outreach_mail.write_remaining(args.source, args.logs, args.write_remaining)
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        print(f"wrote {len(kept)} draft(s) to {args.write_remaining}; "
              f"dropped {len(dropped)} sent or excluded")
        return 0
    if args.check:
        try:
            records = outreach_mail.load_drafts(args.source)
            if args.no_attach:
                if args.attach:
                    raise outreach_mail.PreflightError("--attach and --no-attach cannot be combined")
                records = outreach_mail.without_attachment_claim(records)
            attach, warned = outreach_mail.validate(records, args.attach)
            already = outreach_mail.read_ledger(args.logs)
            chosen, skipped = outreach_mail.select(
                records, already_sent=already, limit=args.limit, start=args.start, only=args.only,
                include_held=args.include_held, exclusions=outreach_mail.read_exclusions(args.logs))
        except outreach_mail.PreflightError as error:
            print(f"outreach: {error}", file=sys.stderr)
            return 2
        mine = sum((record["draft_id"], record["email"]) in already for record in records)
        print(f"{len(records)} draft(s) in source; {mine} of them already sent "
              f"({len(already)} sends recorded across all sources)")
        held = sum(1 for record in records if record.get("hold"))
        print(f"{len(chosen)} selected, {len(skipped)} not attempted ({held} on hold); "
              f"attachment: {attach or 'none'}")
        if not attach and warned:
            print("note: a real send will refuse these drafts until --attach is given")
        for line in warned[:5]:
            print(f"warning: {line}")
        if len(warned) > 5:
            print(f"warning: ...and {len(warned) - 5} more attachment-wording drafts")
        return 0
    try:
        summary = outreach_mail.run(
            source=args.source, from_html=args.from_html, logs_root=args.logs,
            limit=args.limit, start=args.start, only=args.only, attach=args.attach,
            dry_run=args.dry_run, delay=args.delay, seed=args.seed,
            include_held=args.include_held, expected_from=args.expected_from,
            no_attach=args.no_attach, contact=not args.no_contact,
            verify_sent=not args.no_verify)
    except outreach_mail.PreflightError as error:
        print(f"outreach: {error}", file=sys.stderr)
        return 2
    print(f"run {summary['run_id']}: {len(summary['sent'])} sent, "
          f"{len(summary['failed'])} failed; report {summary['directory']}/report.md")
    verification = summary.get("verification")
    if verification and verification["verdict"] != "BATCH VERIFIED":
        return 1
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
