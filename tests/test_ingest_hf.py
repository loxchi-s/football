import pandas as pd
import pytest

from scripts.ingest_hf import require_columns


def test_require_columns_accepts_complete_schema():
    frame = pd.DataFrame({"fixture_id": [1], "known_at": ["2026-01-01T00:00:00Z"]})
    require_columns(frame, "match_stats", {"fixture_id", "known_at"})


def test_require_columns_rejects_missing_fields():
    frame = pd.DataFrame({"fixture_id": [1]})
    with pytest.raises(ValueError, match="missing required columns"):
        require_columns(frame, "match_stats", {"fixture_id", "known_at"})

def test_fixture_schema_requires_btts_label():
    frame = pd.DataFrame(
        {
            "id": [1],
            "date_utc": ["2026-01-01T12:00:00Z"],
            "league_id": [1],
            "home_team_id": [10],
            "away_team_id": [20],
            "goals_home": [1],
            "goals_away": [0],
            "status_norm": ["FT"],
            "is_played": [True],
        }
    )
    with pytest.raises(ValueError, match="btts"):
        require_columns(
            frame,
            "fixtures",
            {
                "id", "date_utc", "league_id", "home_team_id", "away_team_id",
                "goals_home", "goals_away", "status_norm", "is_played", "btts",
            },
        )

def test_download_table_pins_huggingface_revision(monkeypatch):
    calls = {}

    def fake_download(**kwargs):
        calls.update(kwargs)
        return "/tmp/fixtures.parquet"

    def fake_read_parquet(path):
        return pd.DataFrame({"id": [1]})

    monkeypatch.setattr("scripts.ingest_hf.hf_hub_download", fake_download)
    monkeypatch.setattr("scripts.ingest_hf.pd.read_parquet", fake_read_parquet)

    result = __import__("scripts.ingest_hf", fromlist=["download_table"]).download_table(
        "fixtures", "immutable-revision"
    )

    assert calls["revision"] == "immutable-revision"
    assert result["id"].tolist() == [1]
