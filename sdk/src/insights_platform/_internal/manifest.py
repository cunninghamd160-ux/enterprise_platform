import inspect
from pathlib import Path

from insights_platform import config


def caller_file(depth: int = 2) -> str | None:
    frame = inspect.currentframe()
    for _ in range(depth):
        frame = frame.f_back if frame is not None else None
    return frame.f_code.co_filename if frame is not None else None


def resolve(manifest: Path | None, caller: str | None) -> Path:
    if manifest is not None:
        return manifest
    # Tests and CI run from the repo root, so the caller's own directory is searched before cwd.
    starts = [Path.cwd()]
    if caller is not None and (path := Path(caller)).is_file():
        starts.insert(0, path.resolve().parent)
    errors: list[str] = []
    for start in starts:
        try:
            return config.locate(start)
        except config.ConfigError as exc:
            errors.append(str(exc))
    raise config.ConfigError("; ".join(errors))
