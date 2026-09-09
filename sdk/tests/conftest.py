from collections.abc import Callable
from pathlib import Path

import pytest

from insights_platform import config

pytest_plugins = ["insights_platform.testing"]

MANIFEST = """
[app]
name = "{name}"
team = "people-analytics"
kind = "{kind}"
scaffold_version = "0.1.0"
connections = [{connections}]
"""

type ManifestWriter = Callable[..., Path]


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "_current", None)


@pytest.fixture
def write_manifest(tmp_path: Path) -> ManifestWriter:
    def write(
        directory: Path | None = None,
        *,
        name: str = "demo",
        kind: str = "web",
        connections: tuple[str, ...] = ("warehouse",),
    ) -> Path:
        directory = directory or tmp_path
        directory.mkdir(parents=True, exist_ok=True)
        body = MANIFEST.format(
            name=name, kind=kind, connections=", ".join(f'"{c}"' for c in connections)
        )
        path = directory / "platform.toml"
        path.write_text(body, encoding="utf-8")
        return path

    return write
