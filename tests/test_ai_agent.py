import json

import pytest

from scripts import ai_agent
from scripts.ai_agent import allowed_path


def test_allowed_path_accepts_source_and_documentation():
    assert allowed_path("scripts/ingest_hf.py").as_posix() == "scripts/ingest_hf.py"
    assert allowed_path("docs/notes.md").as_posix() == "docs/notes.md"


@pytest.mark.parametrize(
    "path",
    [
        "../secrets.txt",
        ".github/workflows/ci.yml",
        "scripts/ai_agent.py",
        "data/private.csv",
        "/tmp/outside.py",
    ],
)
def test_allowed_path_rejects_paths_outside_policy(path):
    with pytest.raises(SystemExit):
        allowed_path(path)



def test_allowed_path_rejects_symlinked_parent(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    (repo / "scripts").mkdir(parents=True)
    outside.mkdir()
    (repo / "scripts" / "linked").symlink_to(outside, target_is_directory=True)
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit, match="Symbolic links"):
        allowed_path("scripts/linked/escape.py")


@pytest.mark.parametrize("path", ["scripts/bad\nname.py", "docs/bad\tname.md"])
def test_allowed_path_rejects_control_characters(path):
    with pytest.raises(SystemExit, match="Control characters"):
        allowed_path(path)



def test_gemini_request_uses_supported_generation_config(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response_body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps({"summary": "ok", "files": []})}]}}
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(response_body).encode("utf-8")

    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ai_agent.urllib.request, "urlopen", fake_urlopen)
    result = ai_agent.call_gemini("Add a harmless unit test", [])

    payload = json.loads(captured["request"].data)
    assert result["files"] == []
    assert captured["timeout"] == ai_agent.GEMINI_TIMEOUT_SECONDS
    assert "temperature" not in payload["generationConfig"]
    assert payload["generationConfig"]["responseMimeType"] == "application/json"



def test_gemini_retries_transient_connection_errors(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    response_body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps({"summary": "ok", "files": []})}]}}
        ]
    }

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(response_body).encode("utf-8")

    attempts = {"count": 0}

    def flaky_urlopen(_request, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("temporary network timeout")
        return FakeResponse()

    monkeypatch.setattr(ai_agent.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(ai_agent.time, "sleep", lambda _seconds: None)

    result = ai_agent.call_gemini("Run a safe check", [])

    assert result["files"] == []
    assert attempts["count"] == 3


def test_gemini_stops_on_free_tier_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def quota_error(_request, timeout):
        raise ai_agent.urllib.error.HTTPError(
            "https://example.invalid", 429, "quota", {}, None
        )

    monkeypatch.setattr(ai_agent.urllib.request, "urlopen", quota_error)

    with pytest.raises(SystemExit, match="HTTP 429"):
        ai_agent.call_gemini("Run a safe check", [])
