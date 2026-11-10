# Data Completeness Audit — Hugging Face staging

## Purpose

Run structural and descriptive quality checks against the five-league CSV staging output. This is an audit of the rows actually staged by `scripts/ingest_hf.py`; it is not proof that every historical fixture or season is present.

## Execution

The manual `Hugging Face football data staging` workflow now runs:

1. `scripts/ingest_hf.py` to download and stage fixtures, match statistics and odds.
2. `scripts/audit_hf_staging.py` to produce `output/data_completeness_audit.json`.
3. Uploads the staging CSVs and audit JSON as the `football-hf-staging` artifact.

## Checks

- Played-match counts grouped by league and derived season (July–June boundary).
- Stable source fixture ID duplicates.
- Duplicate and orphan `fixture_id` rows in match_stats and odds.
- Null counts/rates for selected important fields; absent columns are explicitly reported.
- Timestamp comparability and whether `known_at` is before or at/after kickoff.
- No null imputation: missing values remain missing.

## Status semantics

- `FAIL`: duplicate stable IDs, duplicate child fixture IDs, orphan child rows, or missing child fixture key.
- `REVIEW_REQUIRED`: structural checks pass, but no trusted expected-count baseline exists to prove per-season completeness.

## Known limitations

- Current ingestion stages only `leagues`, `fixtures`, `teams`, `match_stats` and `odds`.
- Player, lineup, event and xG-training tables are not yet staged.
- Counts by league-season are descriptive. A complete coverage claim requires an authoritative expected fixture baseline and comparison by league-season.
- This workflow is manual-only. It does not provide daily refresh.
- It does not modify the canonical P-Model workbook.
- `match_stats.known_at` is post-match and must not be used as a pre-match feature. Odds must be filtered by verified availability timestamp before pre-match EV use.

## Validation boundary

The audit script is executed in GitHub Actions against the downloaded source snapshot. Until that workflow has completed successfully and its artifact has been inspected, no actual row-level completeness result is claimed.
