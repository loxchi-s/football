from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download
import pandas as pd

REPO_ID = "eatpizzanot/soccer-dataset"
OUT = Path("output")
LEAGUE_IDS = {1, 5, 7, 9, 11}
LEAGUE_NAMES = {
    1: "Premier League",
    5: "La Liga",
    7: "Serie A",
    9: "Ligue 1",
    11: "Bundesliga",
}
BASE_URL = f"https://huggingface.co/datasets/{REPO_ID}/blob/main/"


def download_table(name: str) -> pd.DataFrame:
    path = hf_hub_download(repo_id=REPO_ID, repo_type="dataset", filename=f"{name}.parquet")
    return pd.read_parquet(path)


def require_columns(df: pd.DataFrame, table: str, columns: set[str]) -> None:
    missing = columns.difference(df.columns)
    if missing:
        raise ValueError(f"{table}: missing required columns: {sorted(missing)}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    api = HfApi()
    info = api.dataset_info(REPO_ID)
    revision = info.sha
    last_modified = info.last_modified.isoformat() if info.last_modified else None

    leagues = download_table("leagues")
    fixtures = download_table("fixtures")
    teams = download_table("teams")
    stats = download_table("match_stats")
    odds = download_table("odds")

    require_columns(leagues, "leagues", {"id", "name", "country"})
    require_columns(fixtures, "fixtures", {
        "id", "date_utc", "league_id", "home_team_id", "away_team_id",
        "goals_home", "goals_away", "status_norm", "is_played",
    })
    require_columns(teams, "teams", {"id", "name"})
    require_columns(stats, "match_stats", {"fixture_id", "known_at"})
    require_columns(odds, "odds", {
        "fixture_id", "home_win", "draw", "away_win", "bookmaker", "source", "known_at"
    })

    selected_leagues = leagues[leagues["id"].isin(LEAGUE_IDS)].copy()
    actual = dict(zip(selected_leagues["id"], selected_leagues["name"]))
    if set(actual) != LEAGUE_IDS:
        raise ValueError(f"Expected exactly five league IDs; got {actual}")
    for league_id, expected_name in LEAGUE_NAMES.items():
        if actual[league_id] != expected_name:
            raise ValueError(f"League ID {league_id} mismatch: {actual[league_id]!r}")

    selected = fixtures[fixtures["league_id"].isin(LEAGUE_IDS)].copy()
    if selected["id"].duplicated().any():
        raise ValueError("Duplicate stable fixture IDs in selected fixtures")

    played = selected[selected["is_played"].fillna(False)].copy()
    if played[["goals_home", "goals_away"]].isna().any().any():
        raise ValueError("Played fixture has missing full-time goals")

    team_map = teams.set_index("id")["name"]
    league_map = selected_leagues.set_index("id")["name"]
    played["league"] = played["league_id"].map(league_map)
    played["home_team"] = played["home_team_id"].map(team_map)
    played["away_team"] = played["away_team_id"].map(team_map)
    if played[["league", "home_team", "away_team"]].isna().any().any():
        raise ValueError("Unresolved league/team foreign key in played fixtures")

    matches = played[[
        "id", "date_utc", "league_id", "league", "home_team_id", "home_team",
        "away_team_id", "away_team", "goals_home", "goals_away", "status_norm",
        "btts",
    ]].rename(columns={"id": "hf_fixture_id", "date_utc": "kickoff_utc"})
    matches["source_dataset"] = REPO_ID
    matches["source_url"] = BASE_URL + "fixtures.parquet"
    matches["source_revision"] = revision
    matches["stable_key_note"] = "Use hf_fixture_id as source key; do not overwrite existing Master match_id."

    stats_delta = stats[stats["fixture_id"].isin(selected["id"])].copy()
    stats_delta["source_dataset"] = REPO_ID
    stats_delta["source_url"] = BASE_URL + "match_stats.parquet"
    stats_delta["source_revision"] = revision
    stats_delta["usage_guard"] = "POST_MATCH_ONLY: known_at is kickoff + 105 minutes; never use as pre-match predictor."

    odds_delta = odds[odds["fixture_id"].isin(selected["id"])].copy()
    odds_delta["source_dataset"] = REPO_ID
    odds_delta["source_url"] = BASE_URL + "odds.parquet"
    odds_delta["source_revision"] = revision
    odds_delta["usage_guard"] = "CLOSING/AROUND_KICKOFF: verify known_at < kickoff before any pre-match EV use."

    for name, frame in (
        ("matches_delta.csv", matches),
        ("match_stats_delta.csv", stats_delta),
        ("odds_delta.csv", odds_delta),
    ):
        frame.to_csv(OUT / name, index=False)

    audit = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": REPO_ID,
        "dataset_revision": revision,
        "dataset_last_modified": last_modified,
        "license": "CC-BY-4.0",
        "selected_leagues": LEAGUE_NAMES,
        "selected_fixture_rows": int(len(selected)),
        "played_fixture_rows": int(len(played)),
        "match_stats_rows": int(len(stats_delta)),
        "odds_rows": int(len(odds_delta)),
        "unique_hf_fixture_ids": int(matches["hf_fixture_id"].nunique()),
        "duplicate_hf_fixture_ids": int(matches["hf_fixture_id"].duplicated().sum()),
        "note": "Staging only. Master workbook is not included in this public repository and is not modified by this workflow.",
        "files": {
            "matches_delta.csv": BASE_URL + "fixtures.parquet",
            "match_stats_delta.csv": BASE_URL + "match_stats.parquet",
            "odds_delta.csv": BASE_URL + "odds.parquet",
        },
    }
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
