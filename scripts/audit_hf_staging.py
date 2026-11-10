from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

OUT = Path("output")
MATCHES = OUT / "matches_delta.csv"
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


def load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Required staging file not found: {path}")
    return pd.read_csv(path)


def null_rates(frame: pd.DataFrame, fields: list[str]) -> dict[str, dict[str, float | int]]:
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
    if pd.isna(value):
        return None
    year = value.year
    return f"{year}-{year + 1}" if value.month >= 7 else f"{year - 1}-{year}"


def main() -> int:
    matches = load_csv(MATCHES)
    stats = load_csv(STATS)
    odds = load_csv(ODDS)

    required = {"hf_fixture_id", "kickoff_utc", "league"}
    missing = sorted(required.difference(matches.columns))
    if missing:
        raise ValueError(f"matches_delta.csv missing required columns: {missing}")

    matches["kickoff_utc"] = pd.to_datetime(matches["kickoff_utc"], utc=True, errors="coerce")
    matches["season"] = matches["kickoff_utc"].map(season_label)

    match_ids = set(matches["hf_fixture_id"].dropna())
    report: dict[str, object] = {
        "scope": "staged five-league rows only; not proof of complete historical coverage",
        "match_rows": int(len(matches)),
        "unique_match_ids": int(matches["hf_fixture_id"].nunique()),
        "duplicate_match_ids": int(matches["hf_fixture_id"].duplicated().sum()),
        "invalid_kickoff_rows": int(matches["kickoff_utc"].isna().sum()),
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
            "Player, lineup, event and xG-training tables are not included in current staging ingestion.",
            "Null values are measured and retained; they are not imputed as zero.",
        ],
    }

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
        report["tables"][name] = {
            "rows": int(len(frame)),
            "unique_fixture_ids": int(ids.nunique()),
            "duplicate_fixture_id_rows": int(ids.duplicated().sum()),
            "orphan_fixture_rows": int((~ids.isin(match_ids)).sum()),
        }

    for name, frame in (("match_stats", stats), ("odds", odds)):
        if {"fixture_id", "known_at"}.issubset(frame.columns):
            joined = frame[["fixture_id", "known_at"]].merge(
                matches[["hf_fixture_id", "kickoff_utc"]],
                left_on="fixture_id",
                right_on="hf_fixture_id",
                how="left",
            )
            known_at = pd.to_datetime(joined["known_at"], utc=True, errors="coerce")
            valid = joined["kickoff_utc"].notna() & known_at.notna()
            report["temporal_checks"][name] = {
                "known_at_unparseable_rows": int(joined["known_at"].notna().sum() - known_at.notna().sum()),
                "rows_with_known_at_before_kickoff": int((valid & (known_at < joined["kickoff_utc"])).sum()),
                "rows_with_known_at_at_or_after_kickoff": int((valid & (known_at >= joined["kickoff_utc"])).sum()),
                "rows_without_comparable_timestamp": int((~valid).sum()),
            }

    hard_failures = []
    if report["duplicate_match_ids"]:
        hard_failures.append("duplicate match IDs")
    for table, metrics in report["tables"].items():
        if metrics.get("duplicate_fixture_id_rows", 0):
            hard_failures.append(f"duplicate {table} fixture IDs")
        if metrics.get("orphan_fixture_rows", 0):
            hard_failures.append(f"orphan {table} fixture IDs")
        if metrics.get("missing_fixture_id_column"):
            hard_failures.append(f"{table} missing fixture_id")
    report["hard_failures"] = hard_failures
    report["status"] = "FAIL" if hard_failures else "REVIEW_REQUIRED"
    report["note"] = (
        "REVIEW_REQUIRED means structural checks passed, but completeness thresholds "
        "and expected per-season counts have not been established."
    )

    target = OUT / "data_completeness_audit.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
