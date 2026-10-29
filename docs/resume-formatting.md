# Resume PDF formatting and reuse

The shared optimizer used by `runAiBot.py --configured-search-and-apply` reads the saved optimizer JSON. Bundled defaults fill missing settings; they do not overwrite an existing user configuration. All-bullets rewriting remains opt-in with `rewrite_all_bullets=true` and requires an original DOCX with its same-stem PDF.

## Formatting defaults

- PDF title metadata uses the candidate name from the source document's first nonempty paragraph.
- `rewrite_bullet_min_fill_ratio=0.90` and `rewrite_bullet_target_fill_ratio=0.97` guide candidate selection using measured line width. These are soft targets; a shorter complete safe candidate may be retained after bounded retries.
- Rewriting keeps the original font size, margins and line count. Academic Distinctions remain preserved. Rendered fullness and coverage appear in the verification report.
- `skills_expand_to_fill`, `skills_min_fill_ratio` and `skills_target_fill_ratio` independently control Skills packing. JD terms take priority, followed by applicable source and configured bank vocabulary.

When `rewrite_source_fallback_enabled=true`, failed bullet rewrites can retain their original text. The combined PDF must still pass layout, preserved-section, coverage and job/config binding checks. Fallback is reported explicitly; complete generation does not mean every bullet changed.

The Downloads-only role-title edits are a manually reviewed artifact. They do not set a global employer-to-title mapping for automatic generation.

## Verified resume cache

Before generating, LinkedIn upload checks for a verified PDF bound to the job ID, exact JD, source resume, names/title, effective configuration, prompt and optimizer helper code. A valid match skips duplicate API calls. Missing, modified or rejected artifacts are regenerated. A file lock serializes generation for matching requests.

`--fresh` starts a fresh search manifest; it does not clear verified resume cache entries. Source, JD, configuration, prompt or optimizer dependency changes invalidate the cache. Automatic generation does not pool candidates from historical manual review runs.

Review the [optimizer policies and runtime options](TASK11-README.md#current-optimizer-options) before choosing content and source-check settings. Layout verification does not validate the truth of generated claims.
