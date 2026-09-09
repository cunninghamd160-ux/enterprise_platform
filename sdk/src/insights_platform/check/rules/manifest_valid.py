from collections.abc import Iterator

from insights_platform.check.core import AppContext, Rule, Violation

_NAME = "manifest-valid"
_ADR = "ADR-0002"
_REQUIRED = ("name", "team", "kind", "scaffold_version", "connections")
_STRING_KEYS = ("name", "team", "kind", "scaffold_version")
_KINDS = frozenset({"web", "job"})


def _check(ctx: AppContext) -> Iterator[Violation]:
    path = ctx.rel(ctx.manifest_path)

    def problem(message: str) -> Violation:
        return Violation(_NAME, _ADR, path, None, message)

    if ctx.manifest is None:
        if ctx.manifest_error is None:
            yield problem("platform.toml is missing")
        else:
            yield problem(f"platform.toml is not valid TOML: {ctx.manifest_error}")
        return

    app = ctx.manifest.get("app")
    if not isinstance(app, dict):
        yield problem("[app] table is missing")
        return

    for key in _REQUIRED:
        if key not in app:
            yield problem(f"[app].{key} is missing")
    for key in _STRING_KEYS:
        if key in app and not isinstance(app[key], str):
            yield problem(f"[app].{key} must be a string")

    kind = app.get("kind")
    if isinstance(kind, str) and kind not in _KINDS:
        yield problem(f"[app].kind must be 'web' or 'job', got {kind!r}")

    name = app.get("name")
    if isinstance(name, str) and name != ctx.app_dir.name:
        yield problem(f"[app].name {name!r} does not match directory {ctx.app_dir.name!r}")

    connections = app.get("connections")
    if connections is None:
        return
    if not isinstance(connections, list) or not all(isinstance(c, str) for c in connections):
        yield problem("[app].connections must be a list of strings")
        return
    known = ", ".join(sorted(ctx.known_connections))
    for connection in connections:
        if connection not in ctx.known_connections:
            yield problem(
                f"connection {connection!r} is not in the platform registry (known: {known})"
            )


RULE = Rule(_NAME, _ADR, _check)
