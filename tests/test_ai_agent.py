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


def _install_fake_client(monkeypatch, responses):
    state = {"calls": 0, "closed": False, "kwargs": None, "models": []}

    class FakeModels:
        def generate_content(self, **kwargs):
            state["calls"] += 1
            state["kwargs"] = kwargs
            state["models"].append(kwargs["model"])
            item = responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

    class FakeClient:
        def __init__(self, **kwargs):
            state["client_kwargs"] = kwargs
            self.models = FakeModels()

        def close(self):
            state["closed"] = True

    monkeypatch.setattr(ai_agent.genai, "Client", FakeClient)
    return state


def _response(payload):
    class FakeResponse:
        text = json.dumps(payload)

    return FakeResponse()


def test_gemini_uses_google_genai_sdk_and_json_schema(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    state = _install_fake_client(
        monkeypatch, [_response({"summary": "ok", "files": []})]
    )

    result = ai_agent.call_gemini("Add a harmless unit test", [])

    assert result == {"summary": "ok", "files": []}
    assert state["calls"] == 1
    assert state["closed"] is True
    assert state["client_kwargs"]["api_key"] == "test-key"
    assert state["client_kwargs"]["http_options"].timeout == 90_000
    assert state["kwargs"]["model"] == ai_agent.MODEL
    assert state["kwargs"]["config"].response_mime_type == "application/json"


def test_gemini_retries_transient_connection_errors(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    state = _install_fake_client(
        monkeypatch,
        [TimeoutError("temporary timeout"), ConnectionError("temporary network"), _response({"summary": "ok", "files": []})],
    )
    monkeypatch.setattr(ai_agent.time, "sleep", lambda _seconds: None)

    result = ai_agent.call_gemini("Run a safe check", [])

    assert result["files"] == []
    assert state["calls"] == 3
    assert state["closed"] is True


def test_gemini_stops_on_free_tier_quota_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeAPIError(Exception):
        code = 429

    monkeypatch.setattr(ai_agent.errors, "APIError", FakeAPIError)
    state = _install_fake_client(monkeypatch, [FakeAPIError("quota")])

    with pytest.raises(SystemExit, match="HTTP 429"):
        ai_agent.call_gemini("Run a safe check", [])

    assert state["calls"] == 1
    assert state["closed"] is True


def test_gemini_retries_transient_api_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeAPIError(Exception):
        code = 503

    monkeypatch.setattr(ai_agent.errors, "APIError", FakeAPIError)
    state = _install_fake_client(
        monkeypatch,
        [FakeAPIError("temporarily unavailable"), _response({"summary": "ok", "files": []})],
    )
    monkeypatch.setattr(ai_agent.time, "sleep", lambda _seconds: None)

    result = ai_agent.call_gemini("Run a safe check", [])

    assert result["files"] == []
    assert state["calls"] == 2
    assert state["closed"] is True



def test_gemini_falls_back_after_repeated_503(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-3.6-flash")
    
    class FakeAPIError(Exception):
        code = 503

    monkeypatch.setattr(ai_agent.errors, "APIError", FakeAPIError)
    state = _install_fake_client(
        monkeypatch,
        [
            FakeAPIError("overloaded"),
            FakeAPIError("still overloaded"),
            _response({"summary": "fallback ok", "files": []}),
        ],
    )
    monkeypatch.setattr(ai_agent.time, "sleep", lambda _seconds: None)

    result = ai_agent.call_gemini("Run a safe check", [])

    assert result["summary"] == "fallback ok"
    assert state["models"] == [
        "gemini-3.8-flash",
        "gemini-3.8-flash",
        "gemini-3.6-flash",
    ]
    assert state["closed"] is True


def test_gemini_rejects_model_outside_free_tier_allowlist(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "unapproved-model")

    with pytest.raises(SystemExit, match="allowlist"):
        ai_agent.call_gemini("Run a safe check", [])
