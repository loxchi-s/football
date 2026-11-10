# Football — Hugging Face ingestion

Stages the public `eatpizzanot/soccer-dataset` for the P-Model five-league workflow.

## Run
GitHub → Actions → **Hugging Face football data staging** → **Run workflow** on `main`. Download the `football-hf-staging` artifact after completion.

No HF token, HF Jobs, GPU, paid runner, or repository secret is required.

## Data controls
- League IDs: 1 Premier League, 5 La Liga, 7 Serie A, 9 Ligue 1, 11 Bundesliga.
- `hf_fixture_id` is the source's stable key. Do not replace the Master workbook's existing `match_id`.
- `match_stats.known_at` is kickoff + 105 minutes: post-match only, never a pre-match predictor.
- Odds are closing/around-kickoff records. Verify `known_at < kickoff` before using for pre-match EV.
- Outputs are staging CSVs plus an audit JSON. The Master workbook is not included in this public repository and is not modified by this workflow.
- Dataset metadata currently reports last modification on 2026-07-05. This workflow is manual-only; a stale snapshot cannot supply new daily matches.

## Outputs
`matches_delta.csv`, `match_stats_delta.csv`, `odds_delta.csv`, `audit.json`.
