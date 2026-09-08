# O2D-R051N4 — Jobs + Event Stream

`cortex_jobs` is the canonical durable authority for long-running job lifecycle, progress, cancellation requests and Cortex events. `cortex_activity` and `cortex_task` are compatibility facades; CLI and desktop consume `cortex_jobs` directly.
