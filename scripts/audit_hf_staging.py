from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path("output")
MATCHES = OUT / "matches_delta.csv"
FIXTURE_SCOPE = OUT / "fixture_scope.csv"
STATS = OUT / "match_stats_delta.csv"
ODDS = OUT / "odds_delta.csv"

IMPORTANT_MATCH_FIELDS = [
    "kickoff_utc", "league", "home_team", "away_team",
    "goals_home", "goals_away", "btts",
]
IMPORTANT_STATS_FIELDS = [
    "fixture_id", "known_at", "home_xg", "away_xg",
    "home_possession", "away_possession",
]
IMPORTANT_ODDS_FIELDS = [
    "fixture_id", "known_at", "home_win", "draw", "away_win",
]
ODDS_UNIQUE_KEY = ["fixture_id", "bookmaker", "source", "known_at"]


def load_csv(path: Path) -> pd.DataFrame:
    """Load a required staging CSV or fail with its expected path."""
    if not path.is_file():
        raise FileNotFoundError(f"Required staging file not found: {path}")
    return pd.read_csv(path)


def null_rates(frame: pd.DataFrame, fields: list[str]) -> dict[str, dict[str, float | int]]:
    """Return null counts and rates for available fields."""
    result = {}
    for field in fields:
        if field in frame.columns:
            result[field] = {
                "null_count": int(frame[field].isna().sum()),
                "null_rate": round(float(frame[field].isna().mean()), 6) if len(frame) else 0.0,
            }
        else:
            result[field] = {"missing_column": 1}
    return result


def season_label(value: object) -> str | None:
    """Map a parsed kickoff timestamp to a July–June season label."""
    if pd.isna(value):
        return None
    year = value.year
    return f"{year}-{year + 1}" if value.month >= 7 else f"{year - 1}-{year}"


def timestamp_metrics(frame: pd.DataFrame, fixtures: pd.DataFrame, table: str) -> dict[str, int | str]:
    """Compare each row's known_at timestamp with its fixture kickoff."""
    duplicate_scope_ids = int(fixtures["hf_fixture_id"].duplicated().sum())
    if duplicate_scope_ids:
        return {
            "rows": int(len(frame)),
            "duplicate_fixture_scope_ids": duplicate_scope_ids,
            "temporal_check_status": "SKIPPED_INVALID_FIXTURE_SCOPE",
        }

    joined = frame[["fixture_id", "known_at"]].merge(
        fixtures[["hf_fixture_id", "kickoff_utc"]],
        left_on="fixture_id",
        right_on="hf_fixture_id",
        how="left",
        validate="many_to_one",
    )
    known_at = pd.to_datetime(joined["known_at"], utc=True, errors="coerce")
    valid = joined["kickoff_utc"].notna() & known_at.notna()
    before = valid & (known_at < joined["kickoff_utc"])
    at_or_after = valid & (known_at >= joined["kickoff_utc"])
    result: dict[str, int | str] = {
        "rows": int(len(joined)),
        "known_at_unparseable_rows": int(joined["known_at"].notna().sum() - known_at.notna().sum()),
        "rows_with_known_at_before_kickoff": int(before.sum()),
        "rows_with_known_at_at_or_after_kickoff": int(at_or_after.sum()),
        "rows_without_comparable_timestamp": int((~valid).sum()),
    }
    if table == "match_stats":
        result["usage_classification"] = "POST_MATCH_ONLY"
        result["pre_match_eligible_rows"] = 0
    else:
        result["usage_classification"] = "PRE_MATCH_ONLY_IF_STRICTLY_BEFORE_KICKOFF"
        result["pre_match_eligible_rows"] = int(before.sum())
        result["post_kickoff_rows_excluded_from_pre_match"] = int(at_or_after.sum())
    return result


def odds_identity_metrics(frame: pd.DataFrame) -> dict[str, int | list[str]]:
    """Measure odds uniqueness without treating valid multi-bookmaker rows as duplicates."""
    missing_columns = [column for column in ODDS_UNIQUE_KEY if column not in frame.columns]
    metrics: dict[str, int | list[str]] = {
        "odds_unique_key": ODDS_UNIQUE_KEY,
        "missing_odds_key_columns": missing_columns,
        "exact_duplicate_rows": int(frame.duplicated().sum()),
    }
    if missing_columns:
        return metrics
    complete_key = frame[ODDS_UNIQUE_KEY].notna().all(axis=1)
    metrics["null_odds_unique_key_rows"] = int((~complete_key).sum())

    # Normalize equivalent timestamp representations to UTC before key comparison.
    key_frame = frame.loc[complete_key, ODDS_UNIQUE_KEY].copy()
    parsed_known_at = pd.to_datetime(key_frame["known_at"], utc=True, errors="coerce")
    canonical_known_at = key_frame["known_at"].astype("string").copy()
    valid_timestamps = parsed_known_at.notna()
    canonical_known_at.loc[valid_timestamps] = parsed_known_at.loc[valid_timestamps].map(
        lambda timestamp: timestamp.isoformat()
    )
    key_frame["known_at"] = canonical_known_at
    metrics["duplicate_odds_key_rows"] = int(
        key_frame.duplicated(subset=ODDS_UNIQUE_KEY).sum()
    )
    return metrics


def main() -> int:
    """Audit staged rows, preserving valid multi-bookmaker odds and fixture scope."""
    matches = load_csv(MATCHES)
    fixture_scope = load_csv(FIXTURE_SCOPE)
    stats = load_csv(STATS)
    odds = load_csv(ODDS)

    required_matches = {"hf_fixture_id", "kickoff_utc", "league"}
    missing = sorted(required_matches.difference(matches.columns))
    if missing:
        raise ValueError(f"matches_delta.csv missing required columns: {missing}")
    required_scope = {"hf_fixture_id", "kickoff_utc"}
    missing = sorted(required_scope.difference(fixture_scope.columns))
    if missing:
        raise ValueError(f"fixture_scope.csv missing required columns: {missing}")

    matches["kickoff_utc"] = pd.to_datetime(matches["kickoff_utc"], utc=True, errors="coerce")
    fixture_scope["kickoff_utc"] = pd.to_datetime(
        fixture_scope["kickoff_utc"], utc=True, errors="coerce"
    )
    fixture_ids = set(fixture_scope["hf_fixture_id"].dropna())

    report: dict[str, object] = {
        "scope": "five-league staged rows; counts are not proof of historical completeness",
        "match_rows": int(len(matches)),
        "unique_match_ids": int(matches["hf_fixture_id"].nunique()),
        "null_match_ids": int(matches["hf_fixture_id"].isna().sum()),
        "duplicate_match_ids": int(matches["hf_fixture_id"].dropna().duplicated().sum()),
        "invalid_match_kickoff_rows": int(matches["kickoff_utc"].isna().sum()),
        "selected_fixture_scope_rows": int(len(fixture_scope)),
        "selected_fixture_scope_unique_ids": int(fixture_scope["hf_fixture_id"].nunique()),
        "missing_rates": {
            "matches": null_rates(matches, IMPORTANT_MATCH_FIELDS),
            "match_stats": null_rates(stats, IMPORTANT_STATS_FIELDS),
            "odds": null_rates(odds, IMPORTANT_ODDS_FIELDS),
        },
        "league_season": [],
        "tables": {},
        "temporal_checks": {},
        "limitations": [
            "No expected fixture-count baseline is supplied; season counts are descriptive, not completeness proof.",
            "Player, lineup, event and xG-training tables are not included in current staging output.",
            "Null values are measured and retained; they are not imputed as zero.",
            "Odds are pre-match eligible only when known_at is parseable and strictly before kickoff.",
            "Match stats are post-match observations and are never pre-match model features.",
        ],
    }

    matches["season"] = matches["kickoff_utc"].map(season_label)
    season_counts = (
        matches.dropna(subset=["season"])
        .groupby(["league", "season"], dropna=False)
        .size()
        .rename("played_fixture_rows")
        .reset_index()
    )
    report["league_season"] = season_counts.to_dict(orient="records")

    for name, frame in (("match_stats", stats), ("odds", odds)):
        if "fixture_id" not in frame.columns:
            report["tables"][name] = {"missing_fixture_id_column": True}
            continue
        ids = frame["fixture_id"]
        non_null_ids = ids.dropna()
        metrics: dict[str, int | list[str]] = {
            "rows": int(len(frame)),
            "unique_fixture_ids": int(ids.nunique()),
            "null_fixture_id_rows": int(ids.isna().sum()),
            "orphan_fixture_rows": int((ids.notna() & ~ids.isin(fixture_ids)).sum()),
        }
        if name == "match_stats":
            metrics["duplicate_fixture_id_rows"] = int(non_null_ids.duplicated().sum())
        else:
            metrics.update(odds_identity_metrics(frame))
        report["tables"][name] = metrics

    for name, frame in (("match_stats", stats), ("odds", odds)):
        if {"fixture_id", "known_at"}.issubset(frame.columns):
            report["temporal_checks"][name] = timestamp_metrics(frame, fixture_scope, name)

    hard_failures: list[str] = []
    if report["null_match_ids"]:
        hard_failures.append("null match IDs")
    if report["duplicate_match_ids"]:
        hard_failures.append("duplicate match IDs")
    if report["invalid_match_kickoff_rows"]:
        hard_failures.append("invalid match kickoff timestamps")
    if fixture_scope["hf_fixture_id"].isna().any():
        hard_failures.append("null selected fixture IDs")
    if fixture_scope["hf_fixture_id"].duplicated().any():
        hard_failures.append("duplicate selected fixture IDs")

    for table, metrics in report["tables"].items():
        if metrics.get("missing_fixture_id_column"):
            hard_failures.append(f"{table} missing fixture_id")
            continue
        if metrics.get("null_fixture_id_rows", 0):
            hard_failures.append(f"{table} null fixture IDs")
        if metrics.get("orphan_fixture_rows", 0):
            hard_failures.append(f"orphan {table} fixture IDs")
        if table == "match_stats" and metrics.get("duplicate_fixture_id_rows", 0):
            hard_failures.append("duplicate match_stats fixture IDs")
        if table == "odds":
            if metrics.get("missing_odds_key_columns"):
                hard_failures.append("odds missing composite-key columns")
            if metrics.get("null_odds_unique_key_rows", 0):
                hard_failures.append("odds rows with incomplete composite key")
            if metrics.get("duplicate_odds_key_rows", 0):
                hard_failures.append("duplicate odds composite keys")
            if metrics.get("exact_duplicate_rows", 0):
                hard_failures.append("exact duplicate odds rows")

    report["hard_failures"] = hard_failures
    report["status"] = "FAIL" if hard_failures else "REVIEW_REQUIRED"
    report["note"] = (
        "REVIEW_REQUIRED means structural checks passed, but expected per-season counts "
        "and completeness thresholds have not been established."
    )

    target = OUT / "data_completeness_audit.json"
    payload = json.dumps(report, ensure_ascii=False, indent=2, default=str, allow_nan=False)
    target.write_text(payload, encoding="utf-8")
    print(payload)
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
