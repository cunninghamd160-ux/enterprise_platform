import shutil
from pathlib import Path

import pytest

from insights_platform.check import RULES, Violation, discover_apps, run

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
        "no-raw-alembic",
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
        ("no-raw-alembic", "ADR-0003", 1),
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


def with_database(app: Path, table: str) -> None:
    manifest = app / "platform.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + table, encoding="utf-8")


def test_manifest_accepts_an_enabled_database(tmp_path: Path) -> None:
    with_database(make_app(tmp_path, "owned", ""), "\n[database]\nenabled = true\n")
    assert check(tmp_path) == []


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("\n[database]\n", ["[database].enabled is missing"]),
        ('\n[database]\nenabled = "yes"\n', ["[database].enabled must be true or false"]),
        (
            "\n[database]\nenabled = true\nschema = 'x'\nurl = 'y'\n",
            [
                "[database].schema is not a recognised key (known: enabled)",
                "[database].url is not a recognised key (known: enabled)",
            ],
        ),
    ],
)
def test_manifest_database_table_is_validated(
    tmp_path: Path, table: str, expected: list[str]
) -> None:
    with_database(make_app(tmp_path, "owned", ""), table)
    violations = check(tmp_path)
    assert [v.rule for v in violations] == ["manifest-valid"] * len(expected)
    assert [v.message for v in violations] == expected


def test_manifest_database_must_be_a_table(tmp_path: Path) -> None:
    manifest = make_app(tmp_path, "owned", "") / "platform.toml"
    manifest.write_text(
        "database = true\n" + manifest.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (violation,) = check(tmp_path)
    assert violation.message == "[database] must be a table"


def test_alembic_rule_ignores_migrations_outside_src(tmp_path: Path) -> None:
    app = make_app(tmp_path, "migrated", "from insights_platform.web import create_app\n")
    (app / "migrations").mkdir()
    (app / "migrations" / "env.py").write_text("from alembic import context\n")
    assert check(tmp_path) == []


def test_alembic_rule_catches_submodule_imports_once_per_line(tmp_path: Path) -> None:
    make_app(
        tmp_path,
        "migrating",
        "import alembic.command\nfrom alembic.config import Config\nimport alembic\n",
    )
    violations = check(tmp_path)
    assert [(v.rule, v.line) for v in violations] == [("no-raw-alembic", n) for n in (1, 2, 3)]
    assert all("insights db" in v.message for v in violations)
