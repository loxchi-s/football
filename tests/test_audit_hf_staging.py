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

def test_equivalent_odds_timestamps_are_normalized_before_duplicate_check() -> None:
    """Detect duplicate odds identities expressed with equivalent UTC timestamps."""
    frame = pd.DataFrame(
        [
            {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01T10:00:00Z"},
            {"fixture_id": 10, "bookmaker": "A", "source": "feed", "known_at": "2026-01-01 11:00:00+01:00"},
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
