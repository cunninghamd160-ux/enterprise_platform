import tomllib
from pathlib import Path


class RepoRootNotFoundError(Exception):
    pass


def find_repo_root(start: Path | None = None) -> Path:
    origin = (start or Path.cwd()).resolve()
    for candidate in (origin, *origin.parents):
        pyproject = candidate / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            continue
        if "workspace" in data.get("tool", {}).get("uv", {}):
            return candidate
    raise RepoRootNotFoundError(
        f"no pyproject.toml with [tool.uv.workspace] found from {origin} upward"
    )
