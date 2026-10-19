# Optimizer defaults and final application review

The repository defaults and this user's saved runtime configuration use
`optimization_mode: "full"`, `replace_job_title: true`, and `max_skills: 65`.
Full mode and title replacement were already enabled; the skills cap increased
from 50 to 65, exactly 30%. This baseline comes from the actual repository and
runtime configuration. The Task 2 live navigation check did not generate a resume.

`max_skills` is an upper bound, not a target. Selection remains bounded by source
evidence and the source skills pool. It does not authorize unsupported skills,
filler, extra rendered lines, or layout expansion. The separate layout-preservation
work controls original rendered line use and visual density; a higher entry cap
does not override those acceptance checks.

Other optimizer parameters and match weights are unchanged. Existing explicit
saved user settings remain authoritative when defaults are merged.

The optimization report's `auto_submission_authorized` remains false. It is an
artifact-authority statement, not a switch for automating preparation. Application
preparation and final submission are separate: only an explicit **Submit
application** decision in the application review can authorize the website Submit
click. Leave open, discard, absent review, and unanswered required fields do not
submit. No unattended submission setting is enabled by these defaults.
