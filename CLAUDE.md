# CHILE-OEF agent entry point

Before changing this repository, read `docs/PROJECT_STATE.md` in full. It is the
authoritative continuity log: current milestone, scientific constraints, verified
data releases, implemented modules, validation status, known issues, and the exact
next actions are recorded there.

The non-negotiable invariant is `forecast_time < event_time`. Never use a revised
catalog value before its recorded `available_at`, never describe anomaly as hazard,
and never present an uncalibrated tectonic score as an empirically calibrated
probability.

Update `docs/PROJECT_STATE.md` whenever a milestone, decision, data release,
test result, blocker, or next action changes. Do not infer that later phases are
implemented merely because their directories or design documents exist.
