# Evidence manifest

Generated 2026-09-13T13:01:40.868569+00:00 by `scripts/build_evidence_pack.py`.

Every claim below was checked by running something. A reviewer can regenerate this file and get the same answers, or find out that they no longer hold.

## Verified

| Claim | Check | Result |
|---|---|---|
| Every test passes. | `-m pytest -q --tb=no` | 1049 passed, 2 warnings in 16.37s |
| Hand-calculated golden values still hold: stratum 102.484143, route 100.414024, headline 100.103506, contributions summing exactly to the movement. | `-m pytest tests/unit/test_index_engine_golden.py -q --tb=no` | 26 passed in 0.07s |
| A static scan finds no override flag, no permissive environment variable, and exactly one place that mints a compliance token. | `-m pytest tests/unit/test_no_bypass_path_exists.py -q --tb=no` | 9 passed in 0.47s |
| An AST scan finds no float arithmetic on any money-handling module. | `-m pytest tests/unit/test_no_float_in_money_path.py -q --tb=no` | 51 passed in 0.21s |
| Certificate verification cannot be turned off anywhere in the codebase. | `-m pytest tests/unit/test_tls_ladder.py -q --tb=no` | 11 passed in 2.49s |
| Append-only tables reject UPDATE and DELETE from the application role, and simulated data cannot reach a headline index. | `-m pytest tests/integration/test_constraints.py tests/integration/test_roles_and_privileges.py -q --tb=no` | 81 passed in 1.70s |
| Every text/background pair meets 4.5:1 contrast, measured from the stylesheet tokens. | `-m pytest tests/unit/test_accessibility.py -q --tb=no` | 40 passed in 0.07s |
| The schema migrates up, down and up again cleanly. | `-m pytest tests/integration/test_migrations.py -q --tb=no` | 6 passed in 3.31s |
| mypy --strict reports no issues. | `-m mypy --strict packages/` | Success: no issues found in 54 source files |
| ruff reports no issues. | `-m ruff check .` | All checks passed! |
| The outlier threshold does not affect the published index under methodology 1.1.0. | `scripts/outlier_sensitivity.py` | a substantive modelling choice and must be presented as one. |

## Not verified in this run

A skipped check is not a passed check.

| Claim | Why |
|---|---|
| Each source's robots.txt, fetched and evaluated against the paths an adapter would request. | needs outbound network access |

## Not verifiable by running anything

Listed so that absence from the table above never silently means *not checked*.

| Claim | Why it cannot be verified here |
|---|---|
| The index measures Indian domestic airfare inflation | Requires two quarters of parallel running against the CPI airfare item on real observations. No live source exists yet, so external validity is not established and is not claimed. |
| Route weights represent traffic | Weights are a gravity proxy on AAI airport throughput (evidence rung 3). Airport throughput is not city-pair traffic, and the figures include international passengers. Rung 1 needs DGCA city-pair volumes. |
| The airfare item weight in CPI | Not known. CPI contributions are reported as a range across an assumed weight, never as a point estimate. |
| GIGW and CERT-In conformity | Requires an STQC engagement and a CERT-In empanelled audit. Automated accessibility checks reduce the findings those audits will return; they do not substitute for them. |

## Standing evidence files

Dated records of findings that are not re-derivable on demand, because they capture what an external source said at a moment in time:

- `docs\evidence\O1-mospi-api.md`
- `docs\evidence\O2-cpi-airfare-item.md`
- `docs\evidence\O2b-cpi-airfare-series.md`
- `docs\evidence\O3-amadeus-decommissioned.md`
- `docs\evidence\O6-outlier-sensitivity.md`
- `docs\evidence\O7-screen-suppresses-real-events.md`
- `docs\evidence\O8-source-permissions.md`
