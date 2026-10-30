# Programme task progress logging

For current/future work on this tracked programme, follow the user-requested shared progress convention in `/Users/deepakbasavaraju/Documents/Codex/2026-10-14/task/task-progress/README.md`.

Use its `progress_log.py log` helper with the actual task ID, worker/thread ID and run ID at start, meaningful milestones, blockers and terminal outcomes. During long work, write an honest checkpoint about every two minutes; if nothing new is known, state that. Never fabricate work, historic timestamps or completion. Do not log secrets, raw credentials, private reasoning or gratuitous personal data.

One JSONL file per task is append-only; call the helper rather than editing it. Static views regenerate after logging and need browser reload; no live polling is implemented. Logging never changes task status or authorizes employer actions/submission. Task 2 is Parked; pause Baseten work until user resumes. Task 10 Pick it up later is distinct.

The tracker owner maintains `TASKS.md` and tracker statuses; use `task-progress/render.lock` for tracker HTML mutations to avoid racing automatic log rendering. When assigning future workers, provide the helper/contract path and require this convention in the task handoff.

Future human task routing preference: all coding tasks use Sol with medium reasoning; medium noncoding tasks use Sol with medium reasoning; small noncoding tasks use Luna with low reasoning. Put this in new human task handoffs using supported available models. Do not alter runtime configuration or existing workers. Explicit user overrides take precedence.
