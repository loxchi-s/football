# Data Completeness Audit — Hugging Face staging

## Purpose

Run structural and descriptive quality checks against the five-league CSV staging output. This audits the rows actually staged; it does not prove every historical fixture or season is present.

## Execution

The manual `Hugging Face football data staging` workflow:

1. Downloads five source tables: `leagues`, `fixtures`, `teams`, `match_stats`, and `odds`.
2. Writes four CSV files: `matches_delta.csv` (played fixtures), `fixture_scope.csv` (all selected fixtures, including unplayed fixtures), `match_stats_delta.csv`, and `odds_delta.csv`.
3. Runs `scripts/audit_hf_staging.py` to produce `data_completeness_audit.json`.
4. Attempts artifact upload even when ingestion or audit fails, so partial diagnostics remain available. The job still fails when the audit step fails.

## Checks

- Played-match counts grouped by league and derived season (July–June boundary).
- Stable fixture ID nulls and duplicates.
- Child-row orphan checks against the full selected fixture scope, not only played matches.
- `match_stats`: one row per fixture ID; duplicate fixture IDs fail.
- `odds`: multiple rows per fixture are valid. Uniqueness is checked using `fixture_id + bookmaker + source + known_at`; exact duplicate rows and incomplete composite keys fail.
- Null counts/rates for selected important fields; absent columns are explicitly reported.
- Timestamp comparability against the kickoff timestamp from the full fixture scope.
- No null imputation: missing values remain missing.

## Timestamp and model-usage rules

- `match_stats` is post-match data. It is never eligible as a pre-match predictor.
- An odds row is eligible for pre-match pricing only when `known_at` parses successfully and is strictly earlier than kickoff.
- Odds at or after kickoff, and odds with missing/unparseable timestamps, are excluded from pre-match EV/model inputs.
- A run with zero pre-match-eligible odds is reported as a data limitation, not treated as a structural audit failure. It must not be interpreted as pre-match odds coverage.

## Status semantics

- `FAIL`: null/duplicate stable match IDs, invalid match kickoff, invalid selected fixture IDs, missing child fixture key, null/orphan child IDs, duplicate match_stats fixture IDs, or duplicate/incomplete odds composite keys.
- `REVIEW_REQUIRED`: structural checks pass, but no trusted expected-count baseline exists to prove per-season completeness. This is not a PASS.

## Known limitations

- The workflow stages only fixtures, match statistics and odds as analytical CSVs, plus the full fixture scope used for referential checks.
- Player, lineup, event and xG-training tables are not yet staged.
- Counts by league-season are descriptive. A complete coverage claim requires an authoritative expected fixture baseline and comparison by league-season.
- This workflow is manual-only. It does not provide daily refresh.
- It does not modify the canonical P-Model workbook.

## Validation boundary

Static code and CI checks do not validate current source-data completeness. The manual workflow must run on this branch and its uploaded artifact must be inspected before reporting actual coverage or declaring the audit validated.
