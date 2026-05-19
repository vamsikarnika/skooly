# Skooly Backlog

Prioritized list of items deferred from earlier modules or flagged for revisit. Lower number = higher priority. **P1** is reserved for blocking issues that must be addressed before the next release.

## P1 — Blocking

_None._

## P2 — Important, schedule when capacity opens

- **Mid-year admission pro-rating** (Module 7) — A student joining in Nov is currently charged the full year's structure and given a manual discount. Auto pro-rate by months remaining (with admission fee handled separately) once a real school requests it. Needs a per-component `is_proratable` flag and a hook in the apply-to-class flow.

## P3 — Nice to have, revisit later

- **Revisit receipt number format** — Currently `{SCHOOL_PREFIX}/{academicYearLabel}/{seq:04d}` (e.g. `VB/2025-26/0042`). Some schools have legal/auditor preferences (sequential-only, specific prefix, no separator). Consider per-school configurable format string with template variables, or a callable. Triggered by: first school onboarding that has a specific format requirement.

## P4 — Low priority

_None._

## Done (moved out of backlog)

_None yet._
