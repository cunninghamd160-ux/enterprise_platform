import ast
from collections.abc import Iterator

from insights_platform.check.core import AppContext, ImportTable, Rule, Violation

_NAME = "api-prefix"
_ADR = "ADR-0003"
_PREFIX = "/api"
_CREATE_APP = frozenset({"insights_platform.web.create_app"})
_API_ROUTER = frozenset({"fastapi.APIRouter", "fastapi.routing.APIRouter"})
_ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
)
_ADD_ROUTE = "add_api_route"
_INCLUDE = "include_router"
_WHY = "because the SPA owns / (ADR-0009)"
_ROUTERS = f"routers must be included under {_PREFIX} {_WHY}"
_ROUTES = f"routes on the app must live under {_PREFIX} {_WHY}"


def _under_api(path: str) -> bool:
    return path == _PREFIX or path.startswith(f"{_PREFIX}/")


def _literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((kw.value for kw in call.keywords if kw.arg == name), None)


def _bindings(tree: ast.Module, table: ImportTable, targets: frozenset[str]) -> dict[str, ast.Call]:
    bound: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign | ast.AnnAssign):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        value = node.value
        if not (isinstance(target, ast.Name) and isinstance(value, ast.Call)):
            continue
        if table.resolve(value.func) in targets:
            bound[target.id] = value
    return bound


def _check(ctx: AppContext) -> Iterator[Violation]:
    for path in ctx.source_files:
        tree = ctx.tree(path)
        if tree is None:
            continue
        table = ctx.imports(path)
        apps = _bindings(tree, table, _CREATE_APP)
        if not apps:
            continue
        routers = _bindings(tree, table, _API_ROUTER)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in apps
            ):
                continue
            problem = _problem(node, node.func.attr, routers)
            if problem is not None:
                yield Violation(_NAME, _ADR, ctx.rel(path), node.lineno, problem)


def _problem(call: ast.Call, method: str, routers: dict[str, ast.Call]) -> str | None:
    if method == _INCLUDE:
        return _include_problem(call, routers)
    if method in _ROUTE_METHODS or method == _ADD_ROUTE:
        return _route_problem(call)
    return None


def _include_problem(call: ast.Call, routers: dict[str, ast.Call]) -> str | None:
    router = call.args[0] if call.args else _keyword(call, "router")
    shown = f"{ast.unparse(call.func)}({'' if router is None else ast.unparse(router)})"
    prefix = _keyword(call, "prefix")
    if prefix is None:
        # A router's own APIRouter(prefix=...) is only visible when it is built in this module.
        own = routers.get(router.id) if isinstance(router, ast.Name) else None
        own_prefix = _literal(_keyword(own, "prefix")) if own is not None else None
        if own_prefix is not None and _under_api(own_prefix):
            return None
        return f"{_ROUTERS}; {shown} passes no prefix"
    value = _literal(prefix)
    if value is None:
        return (
            f"{_ROUTERS}; {shown} passes a prefix that is not a string literal, "
            "so the check cannot read it"
        )
    if _under_api(value):
        return None
    return f"{_ROUTERS}; {shown} uses prefix {value!r}"


def _route_problem(call: ast.Call) -> str | None:
    shown = f"{ast.unparse(call.func)}(...)"
    value = _literal(call.args[0] if call.args else _keyword(call, "path"))
    if value is None:
        return (
            f"{_ROUTES}; {shown} has a path that is not a string literal, "
            "so the check cannot read it"
        )
    if _under_api(value):
        return None
    return f"{_ROUTES}; {shown} registers {value!r}"


RULE = Rule(_NAME, _ADR, _check)
