import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _requirements(name: str) -> set[str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.startswith(("#", "-r"))}


def test_requirements_files_match_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert _requirements("requirements.txt") == set(project["dependencies"])
    assert _requirements("requirements-dev.txt") == set(project["optional-dependencies"]["dev"])
