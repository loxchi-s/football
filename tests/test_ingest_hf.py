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
