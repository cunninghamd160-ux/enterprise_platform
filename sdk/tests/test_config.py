from collections.abc import Iterator
from pathlib import Path

import pytest

from insights_platform import config, context

VALID = """
[app]
name = "demo"
team = "people-analytics"
kind = "web"
scaffold_version = "0.1.0"
connections = ["warehouse"]
"""


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(config, "_current", None)
    tokens = [(var, var.set(None)) for var in (context.app, context.team)]
    yield
    for var, token in reversed(tokens):
        var.reset(token)


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "platform.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_load_valid(tmp_path: Path) -> None:
    cfg = config.load(write(tmp_path, VALID))
    assert cfg == config.AppConfig("demo", "people-analytics", "web", "0.1.0", ("warehouse",))
    assert config.current() is cfg
    assert context.app.get() == "demo"
    assert context.team.get() == "people-analytics"


def test_load_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, VALID)
    monkeypatch.chdir(tmp_path)
    assert config.load().name == "demo"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="not found"):
        config.load(tmp_path / "platform.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="invalid TOML"):
        config.load(write(tmp_path, "[app\n"))


def test_missing_app_table(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match=r"\[app\]"):
        config.load(write(tmp_path, "[other]\nx = 1\n"))


def test_missing_key(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="team"):
        config.load(write(tmp_path, VALID.replace('team = "people-analytics"\n', "")))


def test_bad_kind(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="kind"):
        config.load(write(tmp_path, VALID.replace('"web"', '"cron"')))


def test_connections_must_be_list_of_strings(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="connections"):
        config.load(write(tmp_path, VALID.replace('["warehouse"]', '"warehouse"')))


def test_current_before_load() -> None:
    with pytest.raises(config.ConfigError, match="not loaded"):
        config.current()
