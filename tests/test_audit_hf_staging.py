import pandas as pd

from scripts.audit_hf_staging import odds_identity_metrics, orphan_id_rows, timestamp_metrics


def test_odds_from_multiple_bookmakers_are_not_duplicates() -> None:
    """Allow distinct bookmaker quotes for the same fixture."""
    frame = pd.DataFrame(
        [
            {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01T10:00:00Z"},
            {"fixture_id": 10, "bookmaker": "B", "source": "feed", "known_at": "2026-01-01T10:00:00Z"},
        ]
    )

    result = odds_identity_metrics(frame)

    assert result["duplicate_odds_key_rows"] == 0
    assert result["exact_duplicate_rows"] == 0


def test_duplicate_odds_composite_key_is_detected() -> None:
    """Reject repeated odds records with the same composite identity."""
    row = {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01T10:00:00Z"}
    result = odds_identity_metrics(pd.DataFrame([row, row]))

    assert result["duplicate_odds_key_rows"] == 1
    assert result["exact_duplicate_rows"] == 1


def test_odds_missing_composite_key_is_reported() -> None:
    """Report rows that cannot be assigned a complete odds identity."""
    frame = pd.DataFrame(
        [{"fixture_id": 10, "bookmaker": None, "source": "feed", "known_at": "2026-01-01T10:00:00Z"}]
    )

    result = odds_identity_metrics(frame)

    assert result["null_odds_unique_key_rows"] == 1

def test_same_fixture_bookmaker_source_is_duplicate_across_timestamps() -> None:
    """Use the upstream odds natural key and reject repeated source quotes."""
    frame = pd.DataFrame(
        [
            {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01T10:00:00Z"},
            {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01T10:01:00Z"},
        ]
    )

    result = odds_identity_metrics(frame)

    assert result["duplicate_odds_key_rows"] == 1




def test_pre_match_odds_require_timestamp_strictly_before_kickoff() -> None:
    """Exclude odds known at kickoff or later from pre-match inputs."""
    fixtures = pd.DataFrame(
        [{"hf_fixture_id": 10, "kickoff_utc": pd.Timestamp("2026-01-01T12:00:00Z")}]
    )
    odds = pd.DataFrame(
        [
            {"fixture_id": 10, "known_at": "2026-01-01T11:59:00Z"},
            {"fixture_id": 10, "known_at": "2026-01-01T12:00:00Z"},
            {"fixture_id": 10, "known_at": "2026-01-01T12:01:00Z"},
        ]
    )

    result = timestamp_metrics(odds, fixtures, "odds")

    assert result["pre_match_eligible_rows"] == 1
    assert result["rows_with_known_at_at_or_after_kickoff"] == 2


def test_timestamp_metrics_parse_mixed_timezone_formats() -> None:
    """Parse equivalent timestamps with mixed UTC offset representations."""
    fixtures = pd.DataFrame(
        [{"hf_fixture_id": 10, "kickoff_utc": pd.Timestamp("2026-01-01T12:00:00Z")}]
    )
    odds = pd.DataFrame(
        [
            {"fixture_id": 10, "known_at": "2026-01-01T10:00:00Z"},
            {"fixture_id": 10, "known_at": "2026-01-01 11:00:00+01:00"},
        ]
    )

    result = timestamp_metrics(odds, fixtures, "odds")

    assert result["rows_with_known_at_before_kickoff"] == 2
    assert result["known_at_unparseable_rows"] == 0


def test_match_stats_are_never_pre_match_features() -> None:
    """Classify match statistics as post-match-only observations."""
    fixtures = pd.DataFrame(
        [{"hf_fixture_id": 10, "kickoff_utc": pd.Timestamp("2026-01-01T12:00:00Z")}]
    )
    stats = pd.DataFrame(
        [{"fixture_id": 10, "known_at": "2026-01-01T13:45:00Z"}]
    )

    result = timestamp_metrics(stats, fixtures, "match_stats")

    assert result["pre_match_eligible_rows"] == 0
    assert result["usage_classification"] == "POST_MATCH_ONLY"

def test_timestamp_metrics_skip_duplicate_fixture_scope_without_crashing() -> None:
    """Skip temporal comparison when fixture IDs make kickoff mapping ambiguous."""
    fixtures = pd.DataFrame(
        [
            {"hf_fixture_id": 10, "kickoff_utc": pd.Timestamp("2026-01-01T12:00:00Z")},
            {"hf_fixture_id": 10, "kickoff_utc": pd.Timestamp("2026-01-01T13:00:00Z")},
        ]
    )
    odds = pd.DataFrame(
        [{"fixture_id": 10, "known_at": "2026-01-01T11:00:00Z"}]
    )

    result = timestamp_metrics(odds, fixtures, "odds")

    assert result["duplicate_fixture_scope_ids"] == 1
    assert result["temporal_check_status"] == "SKIPPED_INVALID_FIXTURE_SCOPE"


def test_orphan_id_rows_excludes_nulls_and_detects_unknown_ids() -> None:
    """Count only populated IDs that are absent from the selected fixture scope."""
    ids = pd.Series([10, 20, None, 30])

    assert orphan_id_rows(ids, {10, 20}) == 1

def test_empty_selected_fixture_scope_is_not_reported_as_review_required(tmp_path, monkeypatch) -> None:
    """Fail closed when the source selection produces no fixtures."""
    from scripts import audit_hf_staging

    monkeypatch.setattr(audit_hf_staging, "OUT", tmp_path)
    pd.DataFrame(
        columns=["hf_fixture_id", "kickoff_utc", "league", "home_team", "away_team",
                 "goals_home", "goals_away", "btts"]
    ).to_csv(tmp_path / "matches_delta.csv", index=False)
    pd.DataFrame(columns=["hf_fixture_id", "kickoff_utc"]).to_csv(
        tmp_path / "fixture_scope.csv", index=False
    )
    pd.DataFrame(columns=["fixture_id", "known_at"]).to_csv(
        tmp_path / "match_stats_delta.csv", index=False
    )
    pd.DataFrame(columns=["fixture_id", "known_at", "home_win", "draw", "away_win",
                          "bookmaker", "source"]).to_csv(tmp_path / "odds_delta.csv", index=False)

    assert audit_hf_staging.main() == 1
    report = __import__("json").loads((tmp_path / "data_completeness_audit.json").read_text())
    assert report["status"] == "FAIL"
    assert "selected fixture scope is empty" in report["hard_failures"]
