# Technology/date guard

Task 42 extension, 2 November 2026. Applies to every generated resume path,
including direct apply and LinkedIn search. It does not change title handling,
fill targets or any other acceptance rule.

## Behavior

1. The current experience's start/end dates are read from its immutable title
   line.
2. A sourced catalogue at `config/technology_timeline.json` provides each
   listed product's earliest public date.
3. If a rewrote bullet names a catalogued product released after the role ended,
   the candidate is rejected and the term is sent back as
   `forbidden_technologies` on the next request.
4. The prompt must rewrite the bullet without that term and without substituting
   a different late tool.
5. One extra wave is allowed only for a bullet that consumed its retry on this
   correction, so fill recovery still has a chance.
6. A successful retry is accepted normally. If every attempt remains late, the
   existing all-bullets contract rejects the resume.
7. `verify_strict_attachment()` rechecks the final DOCX section by section before
   upload. Both application paths call this verifier.

Technology names outside the catalogue remain allowed. The catalogue is an
availability bound, not an allowlist and not proof of personal use.

## Catalogue policy

Each entry needs:

- canonical names and aliases;
- the earliest defensible public release or announcement date;
- a primary source URL.

The role end month is inclusive. A release on the final day is allowed. Roles
without a parseable date are left unchecked rather than guessed.

## Coverage

- Shared all-bullets validator: late term detected after ordinary fact and JD
  checks.
- Legacy grounded optimizer: late term triggers its bounded response retry.
- Final artifact selection: company-section audit before attachment.
- Direct apply and LinkedIn: both inherit the final artifact verifier.

## Tests

`tests/test_resume_technology_dates.py` covers boundaries, aliases, unknown
terms, the second attempt carrying the forbidden term, a corrected candidate
being accepted, and a final audit under changed paragraph counts.

## Limits

- Only catalogued products are checked. An uncatalogued tool can still be
  anachronistic.
- Release availability is necessary but does not prove the candidate used it.
- A date-correct bullet can still be factually weak; human review remains
  required.
