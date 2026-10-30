# Preserve source resume density

DOCX optimization now compares each source bullet and Skills paragraph with its actual PDF rendering. A two-page result alone is insufficient: sparse rewrites may have the same page count.

- Prompts supply inclusive character minima/maxima and actual source rendered line/width targets. Normal bullets must keep at least 92% of source characters, and preserve technical context, scope, metrics and outcomes. Small labels allow token-level freedom. The existing maximum remains configurable.
- Responses have at most two model attempts. Invalid individual bullets retain their source text after the last attempt. No filler or fabricated facts should be used to meet a bound.
- PDF verification requires identical bullet counts, each paragraph's rendered line count and page placement, occupied text width within 92–108% of the source, and final-line width within 90–110%. Missing paragraph matches fail verification. Width is measured from actual PDF word coordinates, excluding bullet markers.
- Source fonts and margins must remain unchanged within numeric rounding tolerance. Existing page-count, clipping, content, heading and clickable-link checks still apply.
- Skills retain the source inventory's visual space. `max_skills` caps the priority selection, rather than deleting the rest of a longer source section. JD-relevant source skills move first. Source-supported JD terms may replace repeated source labels when their lengths fit; new unsupported skills remain blocked in grounded mode. Explicit review-draft proposals keep their existing opt-in semantics and review flags.
- One bounded local recovery may restore source paragraphs that fail measured density. It makes no new model request and changes no font, margin or spacing. It preserves the initial failed DOCX/PDF and verification diagnostics as `.before_density.*`, then renders and validates the recovery. Bank attempts that change paragraph identity/count are not guessed at; existing bank/source-section retries handle those cases.

The match report distinguishes ranking candidates, actual output Skills, retained source paragraphs, initial rejection, and final acceptance. A retained paragraph is not a successful rewrite. PDF-only inputs cannot establish paragraph-level density without paired DOCX; their report explicitly says density is unverified.

This validates layout and source-relative wording, not the truth of externally unverified claims or a commercial ATS rank. Continue to review the content and rendered pages before using a generated resume.
