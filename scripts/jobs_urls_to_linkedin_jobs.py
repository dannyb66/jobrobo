#!/usr/bin/env python3
"""Convert job URLs into an offline linkedin_jobs pipeline artifact."""

from argparse import ArgumentParser, ArgumentTypeError
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.external_apply import identify_ats
from modules.job_pipeline.models import StageResult, write_artifact


def positive_int(value):
    try:
        number = int(value)
    except ValueError as error:
        raise ArgumentTypeError("must be a positive integer") from error
    if number < 1:
        raise ArgumentTypeError("must be a positive integer")
    return number


def read_urls(path):
    suffix = path.suffix.lower()
    if suffix == ".txt":
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            if set(payload) != {"urls"}:
                raise ValueError('JSON input must be a URL array or an object with one "urls" array')
            payload = payload["urls"]
        if not isinstance(payload, list) or any(not isinstance(value, str) for value in payload):
            raise ValueError("JSON input must contain a URL array")
        return payload
    raise ValueError("Input must be a .txt or .json file")


def convert(raw_urls, set_name):
    records = []
    skipped = []
    seen = set()
    for raw in raw_urls:
        url = raw.strip()
        if not url:
            continue
        if url in seen:
            skipped.append({"url": url, "reason": "duplicate URL"})
            continue
        seen.add(url)
        if not url.lower().startswith(("http://", "https://")):
            skipped.append({"url": url, "reason": "not an http(s) URL"})
            continue
        identity = identify_ats(url)
        if identity is None:
            skipped.append({"url": url, "reason": "unsupported ATS URL"})
            continue
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        records.append({
            "id": "linkedin-job:" + digest,
            "job_url": url,
            "career_url": url,
            "title": "",
            "company": "",
            "provider": identity.provider,
        })
    errors = [
        {
            "source": row["url"],
            "code": "duplicate_url" if row["reason"] == "duplicate URL" else "unsupported_url",
            "message": row["reason"],
            "retryable": False,
        }
        for row in skipped
    ]
    artifact = StageResult.create(
        "linkedin_jobs",
        set_name,
        "linkedin-urls:" + str(uuid4()),
        records,
        delta=records,
        errors=errors,
        input_set_ids=["url-input:" + set_name],
    )
    return artifact, skipped


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--set", dest="set_name")
    parser.add_argument("--limit", type=positive_int)
    args = parser.parse_args(argv)

    try:
        raw_urls = read_urls(args.input)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    if args.limit:
        raw_urls = raw_urls[:args.limit]
    set_name = args.set_name or args.input.stem
    artifact, skipped = convert(raw_urls, set_name)
    write_artifact(artifact, args.output)
    summary = {
        "accepted_count": len(artifact.records),
        "skipped_count": len(skipped),
        "skipped": skipped,
        "output": str(args.output),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if artifact.records else 1


if __name__ == "__main__":
    raise SystemExit(main())
