import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from insights_platform import context

type Kind = Literal["web", "job"]

_REQUIRED = ("name", "team", "kind", "scaffold_version", "connections")


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AppConfig:
    name: str
    team: str
    kind: Kind
    scaffold_version: str
    connections: tuple[str, ...]


_current: AppConfig | None = None


def load(path: Path | None = None) -> AppConfig:
    global _current
    path = path or Path.cwd() / "platform.toml"
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"{path} not found") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from None
    app = raw.get("app")
    if not isinstance(app, dict):
        raise ConfigError(f"{path}: missing [app] table")
    missing = [key for key in _REQUIRED if key not in app]
    if missing:
        raise ConfigError(f"{path}: [app] is missing {', '.join(missing)}")
    config = AppConfig(
        name=_string(app, "name", path),
        team=_string(app, "team", path),
        kind=_kind(app, path),
        scaffold_version=_string(app, "scaffold_version", path),
        connections=_connections(app, path),
    )
    _current = config
    context.app.set(config.name)
    context.team.set(config.team)
    return config


def current() -> AppConfig:
    if _current is None:
        raise ConfigError("platform.toml is not loaded; call config.load() at startup")
    return _current


def locate(start: Path) -> Path:
    for directory in (start, *start.parents):
        candidate = directory / "platform.toml"
        if candidate.is_file():
            return candidate
    raise ConfigError(f"no platform.toml found in {start} or any parent directory")


def _string(app: dict[str, Any], key: str, path: Path) -> str:
    value = app[key]
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{path}: [app].{key} must be a non-empty string")
    return value


def _kind(app: dict[str, Any], path: Path) -> Kind:
    value = _string(app, "kind", path)
    if value == "web":
        return "web"
    if value == "job":
        return "job"
    raise ConfigError(f"{path}: [app].kind must be 'web' or 'job', got {value!r}")


def _connections(app: dict[str, Any], path: Path) -> tuple[str, ...]:
    value = app["connections"]
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError(f"{path}: [app].connections must be a list of non-empty strings")
    return tuple(value)
