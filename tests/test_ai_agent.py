import pytest

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
