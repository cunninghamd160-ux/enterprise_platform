import ast
import shutil
from pathlib import Path

import pytest

from insights_platform.check import RULES, Violation, discover_apps, run
from insights_platform.check.core import AppContext, import_table

FIXTURES = Path(__file__).parent / "fixtures" / "broken_apps"
KNOWN = frozenset({"warehouse", "hr-api"})
CURRENT = "0.3.0"
PIN = ">=0.3,<0.4"


def materialize(fixture_dir: Path, dest: Path) -> Path:
    for src in fixture_dir.rglob("*"):
        if src.is_dir():
            continue
        target = dest / src.relative_to(fixture_dir)
        if target.suffixes[-2:] == [".py", ".txt"]:
            target = target.with_suffix("")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    return dest


def check(repo_root: Path) -> list[Violation]:
    return run(
        discover_apps(repo_root),
        repo_root=repo_root,
        known_connections=KNOWN,
        current_scaffold_version=CURRENT,
        sdk_version=CURRENT,
    )


def make_app(
    repo_root: Path,
    name: str,
    source: str,
    *,
    scaffold_version: str = CURRENT,
    pin: str = PIN,
) -> Path:
    app = repo_root / "apps" / name
    pkg = app / "src" / name.replace("-", "_")
    pkg.mkdir(parents=True)
    (app / "platform.toml").write_text(
        "[app]\n"
        f'name = "{name}"\n'
        'team = "platform"\n'
        'kind = "web"\n'
        f'scaffold_version = "{scaffold_version}"\n'
        'connections = ["warehouse"]\n'
    )
    (app / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        f'dependencies = ["insights-platform{pin}"]\n'
    )
    (pkg / "main.py").write_text(source)
    return app


def make_sliced_app(repo_root: Path, name: str, files: dict[str, str]) -> Path:
    app = make_app(repo_root, name, "")
    pkg = app / "src" / name.replace("-", "_")
    for relative, source in files.items():
        target = pkg / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    return app


def test_rules_are_in_table_order() -> None:
    assert [r.name for r in RULES] == [
        "no-raw-drivers",
        "no-client-construction",
        "use-create-app",
        "no-private-imports",
        "apps-independent",
        "manifest-valid",
        "scaffold-supported",
        "sdk-pin-declared",
        "slice-layering",
        "features-independent",
        "api-prefix",
    ]


@pytest.mark.parametrize(
    ("fixture", "adr", "count"),
    [
        ("no-raw-drivers", "ADR-0003", 1),
        ("no-client-construction", "ADR-0005", 1),
        ("use-create-app", "ADR-0003", 1),
        ("no-private-imports", "ADR-0001", 1),
        ("apps-independent", "ADR-0004", 1),
        ("manifest-valid", "ADR-0002", 4),
        ("scaffold-supported", "ADR-0001", 1),
        ("sdk-pin-declared", "ADR-0001", 1),
        ("slice-layering", "ADR-0003", 1),
        ("features-independent", "ADR-0003", 1),
        ("api-prefix", "ADR-0003", 1),
    ],
)
def test_broken_fixture_fires_exactly_its_rule(
    tmp_path: Path, fixture: str, adr: str, count: int
) -> None:
    violations = check(materialize(FIXTURES / fixture, tmp_path))
    assert len(violations) == count
    assert {v.rule for v in violations} == {fixture}
    assert {v.adr for v in violations} == {adr}
    for violation in violations:
        assert str(violation).startswith(f"violates {adr}: ")


def test_good_app_is_clean(tmp_path: Path) -> None:
    assert check(materialize(FIXTURES / "good_app", tmp_path)) == []


def test_violation_str_uses_repo_relative_posix_path_and_line(tmp_path: Path) -> None:
    (violation,) = check(materialize(FIXTURES / "use-create-app", tmp_path))
    assert str(violation) == (
        f"violates ADR-0003: {violation.message} (apps/create-app/src/create_app/main.py:3)"
    )


def test_manifest_violations_have_no_line(tmp_path: Path) -> None:
    violations = check(materialize(FIXTURES / "manifest-valid", tmp_path))
    assert all(v.line is None for v in violations)
    assert all(str(v).endswith("(apps/manifest-invalid/platform.toml)") for v in violations)


def test_construction_rule_ignores_type_hints_and_exceptions(tmp_path: Path) -> None:
    make_app(
        tmp_path,
        "typed",
        "import httpx\n"
        "from insights_platform.web import create_app\n"
        "\n"
        "app = create_app()\n"
        "\n"
        "\n"
        "def use(client: httpx.Client) -> None:\n"
        '    raise httpx.HTTPError("no")\n',
    )
    assert check(tmp_path) == []


def test_construction_rule_resolves_from_import_alias(tmp_path: Path) -> None:
    make_app(
        tmp_path,
        "aliased",
        "from sqlalchemy import create_engine as ce\n\nengine = ce('sqlite://')\n",
    )
    assert [v.rule for v in check(tmp_path)] == ["no-client-construction"]


def test_construction_rule_catches_httpx_module_shortcuts(tmp_path: Path) -> None:
    make_app(tmp_path, "shortcut", 'import httpx\n\nhttpx.get("http://hr-api.fixture")\n')
    (violation,) = check(tmp_path)
    assert violation.rule == "no-client-construction"
    assert "httpx.get" in violation.message


def test_raw_driver_rule_catches_from_urllib_import_request(tmp_path: Path) -> None:
    make_app(tmp_path, "urllib-app", "from urllib import request\n\nrequest.urlopen\n")
    (violation,) = check(tmp_path)
    assert violation.rule == "no-raw-drivers"
    assert "urllib.request" in violation.message


def test_sdk_must_not_import_app_packages(tmp_path: Path) -> None:
    make_app(tmp_path, "alpha", "")
    sdk = tmp_path / "sdk" / "src" / "insights_platform"
    sdk.mkdir(parents=True)
    (sdk / "leak.py").write_text("import alpha\n")
    assert [(v.rule, v.path.as_posix(), v.line) for v in check(tmp_path)] == [
        ("apps-independent", "sdk/src/insights_platform/leak.py", 1)
    ]


def test_missing_manifest_is_reported(tmp_path: Path) -> None:
    app = tmp_path / "apps" / "nomanifest"
    (app / "src" / "nomanifest").mkdir(parents=True)
    (app / "pyproject.toml").write_text(
        '[project]\nname = "nomanifest"\ndependencies = ["insights-platform>=0.3,<0.4"]\n'
    )
    violations = run(
        [app],
        repo_root=tmp_path,
        known_connections=KNOWN,
        current_scaffold_version=CURRENT,
        sdk_version=CURRENT,
    )
    assert [v.rule for v in violations] == ["manifest-valid"]
    assert "missing" in violations[0].message


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    app = make_app(tmp_path, "badtoml", "")
    (app / "platform.toml").write_text("[app\nname = \n")
    violations = check(tmp_path)
    assert [v.rule for v in violations] == ["manifest-valid"]
    assert "not valid TOML" in violations[0].message


def test_discover_apps_skips_directories_without_manifest(tmp_path: Path) -> None:
    make_app(tmp_path, "b-app", "")
    make_app(tmp_path, "a-app", "")
    (tmp_path / "apps" / "no-manifest").mkdir()
    assert [p.name for p in discover_apps(tmp_path)] == ["a-app", "b-app"]
    assert discover_apps(tmp_path / "nowhere") == []


@pytest.mark.parametrize(
    ("version", "supported"),
    [("0.3.0", True), ("0.1.0", True), ("0.0.9", False), ("1.0.0", False), ("x.y", False)],
)
def test_scaffold_support_window(tmp_path: Path, version: str, supported: bool) -> None:
    make_app(tmp_path, "s", "", scaffold_version=version)
    rules = [v.rule for v in check(tmp_path)]
    assert ("scaffold-supported" in rules) is (not supported)


@pytest.mark.parametrize(
    ("pin", "ok"),
    [
        (">=0.3,<0.4", True),
        ("==0.3.0", True),
        (">=0.1,<0.2", False),
        (">=9", False),
        ("", False),
    ],
)
def test_pin_must_admit_the_current_sdk_release(tmp_path: Path, pin: str, ok: bool) -> None:
    make_app(tmp_path, "pinned", "", pin=pin)
    assert ("sdk-pin-declared" in [v.rule for v in check(tmp_path)]) is (not ok)


def test_missing_pyproject_is_reported(tmp_path: Path) -> None:
    app = make_app(tmp_path, "nopyproject", "")
    (app / "pyproject.toml").unlink()
    (violation,) = check(tmp_path)
    assert violation.rule == "sdk-pin-declared"
    assert str(violation).endswith("(apps/nopyproject/pyproject.toml)")


def test_app_not_depending_on_the_sdk_is_reported(tmp_path: Path) -> None:
    app = make_app(tmp_path, "unpinned", "")
    (app / "pyproject.toml").write_text(
        '[project]\nname = "unpinned"\nversion = "0.1.0"\ndependencies = ["httpx"]\n'
    )
    (violation,) = check(tmp_path)
    assert violation.rule == "sdk-pin-declared"
    assert "declares no dependency" in violation.message


def test_pin_matching_ignores_name_normalisation(tmp_path: Path) -> None:
    app = make_app(tmp_path, "normalised", "")
    (app / "pyproject.toml").write_text(
        '[project]\nname = "normalised"\nversion = "0.1.0"\n'
        'dependencies = ["Insights_Platform>=0.3,<0.4"]\n'
    )
    assert check(tmp_path) == []


def test_relative_imports_resolve_against_the_package() -> None:
    tree = ast.parse(
        "from .service import fetch\n"
        "from . import repository\n"
        "from ..headcount import router\n"
        "from ... import top\n"
        "from .... import beyond\n"
        "from fastapi import APIRouter\n"
    )
    table = import_table(tree, package="demo.features.records")
    assert table.modules == (
        ("demo.features.records.service", 1),
        ("demo.features.records", 2),
        ("demo.features.headcount", 3),
        ("demo", 4),
        ("fastapi", 6),
    )
    assert table.imported == (
        ("demo.features.records.service", 1),
        ("demo.features.records.service.fetch", 1),
        ("demo.features.records", 2),
        ("demo.features.records.repository", 2),
        ("demo.features.headcount", 3),
        ("demo.features.headcount.router", 3),
        ("demo", 4),
        ("demo.top", 4),
        ("fastapi", 6),
        ("fastapi.APIRouter", 6),
    )
    assert table.aliases == {
        "fetch": "demo.features.records.service.fetch",
        "repository": "demo.features.records.repository",
        "router": "demo.features.headcount.router",
        "top": "demo.top",
        "APIRouter": "fastapi.APIRouter",
    }
    assert import_table(tree).modules == (("fastapi", 6),)


def test_module_and_package_names_follow_the_src_layout(tmp_path: Path) -> None:
    app = make_sliced_app(
        tmp_path, "demo-web", {"features/records/__init__.py": "", "features/records/router.py": ""}
    )
    ctx = AppContext.load(
        app,
        tmp_path,
        known_connections=KNOWN,
        current_scaffold_version=CURRENT,
        sdk_version=CURRENT,
        shared={},
    )
    records = app.resolve() / "src" / "demo_web" / "features" / "records"
    assert ctx.module_name(records / "router.py") == "demo_web.features.records.router"
    assert ctx.package_name(records / "router.py") == "demo_web.features.records"
    assert ctx.module_name(records / "__init__.py") == "demo_web.features.records"
    assert ctx.package_name(records / "__init__.py") == "demo_web.features.records"
    assert ctx.module_name(app.resolve() / "tests" / "test_main.py") is None
    assert ctx.package_name(app.resolve() / "tests" / "test_main.py") is None


def test_resolved_relative_imports_do_not_trip_absolute_prefix_rules(tmp_path: Path) -> None:
    make_app(tmp_path, "beta", "")
    make_sliced_app(
        tmp_path,
        "alpha",
        {
            "features/__init__.py": "",
            "features/x/__init__.py": "",
            "features/x/service.py": "from . import _private, beta, requests\n",
            "features/x/_private.py": "",
            "features/x/beta.py": "",
            "features/x/requests.py": "",
        },
    )
    assert check(tmp_path) == []


SLICE = {
    "features/__init__.py": "",
    "features/comp/__init__.py": "from . import models, repository, router, schemas, service\n",
    "features/comp/router.py": "from . import service\nfrom .schemas import Row\n",
    "features/comp/service.py": "from . import repository\nfrom .schemas import Row\n",
    "features/comp/repository.py": "from . import models, queries\n",
    "features/comp/queries.py": "from . import models, schemas\n",
    "features/comp/models.py": "",
    "features/comp/schemas.py": "",
}


def test_layered_feature_is_clean(tmp_path: Path) -> None:
    make_sliced_app(tmp_path, "sliced", SLICE)
    assert check(tmp_path) == []


@pytest.mark.parametrize(
    ("module", "source", "expected"),
    [
        (
            "router.py",
            "from . import repository\n",
            "router must not import repository inside feature 'comp'; "
            "router may import service, schemas or a helper module",
        ),
        (
            "service.py",
            "from .router import router\n",
            "service must not import router inside feature 'comp'; "
            "service may import repository, models, schemas or a helper module",
        ),
        (
            "repository.py",
            "from . import service\n",
            "repository must not import service inside feature 'comp'; "
            "repository may import models or a helper module",
        ),
        (
            "schemas.py",
            "from . import models\n",
            "schemas must not import models inside feature 'comp'; "
            "schemas imports nothing inside its feature",
        ),
        (
            "models.py",
            "from sliced.features.comp.repository import list_comp\n",
            "models must not import repository inside feature 'comp'; "
            "models imports nothing inside its feature",
        ),
        (
            "queries.py",
            "from . import repository\n",
            "queries must not import repository inside feature 'comp'; "
            "queries is a helper module and may import only models or schemas",
        ),
    ],
)
def test_slice_layering_names_the_layer_pair(
    tmp_path: Path, module: str, source: str, expected: str
) -> None:
    make_sliced_app(tmp_path, "sliced", {**SLICE, f"features/comp/{module}": source})
    (violation,) = check(tmp_path)
    assert violation.rule == "slice-layering"
    assert violation.adr == "ADR-0003"
    assert violation.message == expected
    assert str(violation).endswith(f"(apps/sliced/src/sliced/features/comp/{module}:1)")


def test_slice_layering_reports_one_violation_per_line_and_layer(tmp_path: Path) -> None:
    router = "from .repository import a, b\nfrom . import models\n"
    make_sliced_app(tmp_path, "sliced", {**SLICE, "features/comp/router.py": router})
    assert [(v.line, v.message.split(";")[0]) for v in check(tmp_path)] == [
        (1, "router must not import repository inside feature 'comp'"),
        (2, "router must not import models inside feature 'comp'"),
    ]


TWO = {
    "features/__init__.py": "",
    "features/comp/__init__.py": "from .router import router\n",
    "features/comp/router.py": "from . import service\n",
    "features/comp/service.py": "",
    "features/headcount/__init__.py": "from .router import router\n",
    "features/headcount/router.py": "",
    "features/headcount/service.py": "",
}


@pytest.mark.parametrize(
    "source",
    [
        "from ..headcount import router\n",
        "from ..headcount import service\n",
        "from .. import headcount\n",
        "from two.features import headcount\n",
        "from two.features.headcount import router\n",
        "import two.features.headcount\n",
    ],
)
def test_features_reach_each_other_through_the_package(tmp_path: Path, source: str) -> None:
    make_sliced_app(tmp_path, "two", {**TWO, "features/comp/service.py": source})
    assert check(tmp_path) == []


@pytest.mark.parametrize(
    ("source", "module"),
    [
        ("from ..headcount.service import x\n", "two.features.headcount.service"),
        ("from two.features.headcount.router import router\n", "two.features.headcount.router"),
        ("import two.features.headcount.service\n", "two.features.headcount.service"),
    ],
)
def test_features_must_not_reach_inside_each_other(
    tmp_path: Path, source: str, module: str
) -> None:
    make_sliced_app(tmp_path, "two", {**TWO, "features/comp/service.py": source})
    (violation,) = check(tmp_path)
    assert violation.rule == "features-independent"
    assert violation.adr == "ADR-0003"
    assert violation.message == (
        "feature 'comp' must import feature 'headcount' only as two.features.headcount, "
        f"the package whose __init__ is its public surface; {module} reaches inside it"
    )
    assert str(violation).endswith("(apps/two/src/two/features/comp/service.py:1)")


def test_modules_outside_features_may_reach_inside_them(tmp_path: Path) -> None:
    make_sliced_app(
        tmp_path, "two", {**TWO, "main.py": "from .features.headcount.router import router\n"}
    )
    assert check(tmp_path) == []


APP = (
    "from fastapi import APIRouter\n"
    "from insights_platform.web import create_app\n"
    "\n"
    "app = create_app()\n"
)
ROUTER_ROUTE = 'r = APIRouter()\n\n\n@r.get("/x")\ndef x() -> None: ...\n\n\n'


@pytest.mark.parametrize(
    "source",
    [
        '@app.get("/api")\ndef root() -> None: ...\n',
        '@app.post("/api/records", status_code=201)\ndef create() -> None: ...\n',
        'app.add_api_route("/api/x", root)\n',
        'r = APIRouter()\napp.include_router(r, prefix="/api")\n',
        'r = APIRouter()\napp.include_router(r, prefix="/api/v1")\n',
        'r = APIRouter(prefix="/api/x")\napp.include_router(r)\n',
        'r = APIRouter(prefix="/x")\napp.include_router(r, prefix="/api")\n',
        ROUTER_ROUTE + 'app.include_router(r, prefix="/api")\n',
    ],
)
def test_api_prefix_accepts_routes_and_routers_under_api(tmp_path: Path, source: str) -> None:
    make_app(tmp_path, "prefixed", APP + source)
    assert check(tmp_path) == []


@pytest.mark.parametrize(
    ("source", "detail"),
    [
        ('@app.get("/")\ndef root() -> None: ...\n', "app.get(...) registers '/'"),
        ('@app.post("/apix")\ndef x() -> None: ...\n', "app.post(...) registers '/apix'"),
        ('app.add_api_route("/x", root)\n', "app.add_api_route(...) registers '/x'"),
        (
            'PATH = "/x"\n\n\n@app.get(PATH)\ndef x() -> None: ...\n',
            "app.get(...) has a path that is not a string literal, so the check cannot read it",
        ),
        ("r = APIRouter()\napp.include_router(r)\n", "app.include_router(r) passes no prefix"),
        (
            'r = APIRouter(prefix="/x")\napp.include_router(r)\n',
            "app.include_router(r) passes no prefix",
        ),
        (
            'r = APIRouter()\napp.include_router(r, prefix="/v1")\n',
            "app.include_router(r) uses prefix '/v1'",
        ),
        (
            'P = "/api"\nr = APIRouter()\napp.include_router(r, prefix=P)\n',
            "app.include_router(r) passes a prefix that is not a string literal, "
            "so the check cannot read it",
        ),
    ],
)
def test_api_prefix_rejects_routes_and_routers_outside_api(
    tmp_path: Path, source: str, detail: str
) -> None:
    make_app(tmp_path, "prefixed", APP + source)
    (violation,) = check(tmp_path)
    assert violation.rule == "api-prefix"
    assert violation.adr == "ADR-0003"
    routers = "include_router" in detail
    what = "routers must be included" if routers else "routes on the app must live"
    assert violation.message == f"{what} under /api because the SPA owns / (ADR-0009); {detail}"


ROUTE_AT_ROOT = '@app.get("/")\ndef r() -> None: ...\n'


@pytest.mark.parametrize(
    "source",
    [
        "import insights_platform.web as w\n\napp = w.create_app()\n\n\n" + ROUTE_AT_ROOT,
        "from fastapi import FastAPI\nfrom insights_platform.web import create_app\n\n"
        "app: FastAPI = create_app()\n\n\n" + ROUTE_AT_ROOT,
    ],
)
def test_api_prefix_finds_the_app_through_aliases_and_annotations(
    tmp_path: Path, source: str
) -> None:
    make_app(tmp_path, "aliased", source)
    assert [v.rule for v in check(tmp_path)] == ["api-prefix"]


def test_api_prefix_ignores_routes_on_objects_it_cannot_identify(tmp_path: Path) -> None:
    make_app(tmp_path, "unknown", "from .elsewhere import app\n\n\n" + ROUTE_AT_ROOT)
    assert check(tmp_path) == []
