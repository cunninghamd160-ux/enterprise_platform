import json
import shutil
import sqlite3
import tomllib
from contextlib import closing
from importlib.metadata import entry_points
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

import insights_platform
from insights_platform.check import discover_apps, run
from insights_platform.cli import app
from insights_platform.cli.new import sdk_pin
from insights_platform.data.registry import KNOWN_CONNECTIONS

FIXTURES = Path(__file__).parent / "fixtures" / "broken_apps"
PLACEHOLDERS = ("__NAME__", "__PKG__", "__TEAM__", "__SCAFFOLD_VERSION__", "__SDK_PIN__")
EXPECTED_FILES = (
    "Dockerfile",
    "README.md",
    "platform.toml",
    "pyproject.toml",
    "src/{pkg}/__init__.py",
    "src/{pkg}/main.py",
    "tests/test_main.py",
)
MIGRATION_FILES = (
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/0001_records.py",
)
FRONTEND_FILES = (
    "frontend/.env.local",
    "frontend/.prettierignore",
    "frontend/eslint.config.js",
    "frontend/index.html",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/src/api/client.ts",
    "frontend/src/components/RecordsTable.tsx",
    "frontend/src/index.css",
    "frontend/src/main.tsx",
    "frontend/src/pages/Records.test.tsx",
    "frontend/src/pages/Records.tsx",
    "frontend/src/test/setup.ts",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts",
)

runner = CliRunner()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["sdk", "apps/*"]\n', encoding="utf-8"
    )
    (tmp_path / "apps").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


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


def violations(repo_root: Path) -> list[str]:
    return [
        str(v)
        for v in run(
            discover_apps(repo_root),
            repo_root=repo_root,
            known_connections=frozenset(KNOWN_CONNECTIONS),
            current_scaffold_version=insights_platform.__version__,
            sdk_version=insights_platform.__version__,
        )
    ]


def files_under(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def expected_files(kind: str, name: str | None = None, *, frontend: bool = True) -> list[str]:
    pkg = (name or f"demo-{kind}").replace("-", "_")
    files = [f.format(pkg=pkg) for f in EXPECTED_FILES]
    if kind == "web":
        files.extend(MIGRATION_FILES)
    if kind == "web" and frontend:
        files.extend(FRONTEND_FILES)
    return sorted(files)


def assert_fully_substituted(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            assert not path.name.endswith(".tmpl"), path
            text = path.read_text(encoding="utf-8")
            assert not any(p in text for p in PLACEHOLDERS), path


def generate(kind: str, name: str | None = None, *extra: str) -> tuple[Path, str]:
    name = name or f"demo-{kind}"
    result = runner.invoke(app, ["new", name, "--kind", kind, *extra])
    assert result.exit_code == 0, result.output
    return Path("apps") / name, result.output


@pytest.mark.parametrize("kind", ["web", "job"])
def test_new_generates_expected_tree(repo: Path, kind: str) -> None:
    target, output = generate(kind, None, "--team", "people-analytics")
    assert files_under(repo / target) == expected_files(kind)
    assert_fully_substituted(repo / target)
    assert f"Created {target.as_posix()}" in output
    assert f"uv run insights check {target.as_posix()}" in output
    assert (f"npm ci --prefix {target.as_posix()}/frontend" in output) == (kind == "web")


def test_web_frontend_is_wired_to_its_app(repo: Path) -> None:
    target, _ = generate("web", None, "--team", "people-analytics")
    frontend = repo / target / "frontend"
    dockerfile = (repo / target / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM node:24-alpine AS frontend\n")
    assert "COPY --from=frontend /fe/dist apps/demo-web/frontend/dist" in dockerfile
    assert "## Frontend" in (repo / target / "README.md").read_text(encoding="utf-8")
    package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((frontend / "package-lock.json").read_text(encoding="utf-8"))
    assert package["name"] == lock["name"] == lock["packages"][""]["name"] == "demo-web"
    assert lock["packages"][""]["dependencies"] == package["dependencies"]
    assert lock["packages"][""]["devDependencies"] == package["devDependencies"]
    lines = (frontend / ".env.local").read_text(encoding="utf-8").splitlines()
    env_local = {key: value for key, _, value in (line.partition("=") for line in lines)}
    assert env_local == {"VITE_INSIGHTS_USER": "dev", "VITE_INSIGHTS_TEAM": "people-analytics"}


def test_no_frontend_generates_an_api_only_web_app(repo: Path) -> None:
    target, output = generate("web", None, "--no-frontend")
    assert files_under(repo / target) == expected_files("web", frontend=False)
    assert_fully_substituted(repo / target)
    dockerfile = (repo / target / "Dockerfile").read_text(encoding="utf-8")
    assert dockerfile.startswith("FROM python:")
    assert dockerfile.count("FROM ") == 1
    assert "## Frontend" not in (repo / target / "README.md").read_text(encoding="utf-8")
    assert "npm" not in output


def test_no_frontend_is_a_no_op_for_jobs(repo: Path) -> None:
    generate("job", "nightly", "--no-frontend")
    result = runner.invoke(app, ["new", "nightly", "--kind", "job", "--dest", "reference"])
    assert result.exit_code == 0, result.output
    flagged, reference = repo / "apps" / "nightly", repo / "reference" / "nightly"
    assert files_under(flagged) == files_under(reference) == expected_files("job", "nightly")
    for relative in files_under(flagged):
        assert (flagged / relative).read_bytes() == (reference / relative).read_bytes(), relative


@pytest.mark.parametrize("kind", ["web", "job"])
def test_new_writes_valid_manifest_and_pyproject(repo: Path, kind: str) -> None:
    target, _ = generate(kind, None, "--team", "people-analytics")
    manifest = tomllib.loads((repo / target / "platform.toml").read_text(encoding="utf-8"))
    assert manifest["app"] == {
        "name": f"demo-{kind}",
        "team": "people-analytics",
        "kind": kind,
        "scaffold_version": insights_platform.__version__,
        "connections": ["warehouse"],
    }
    assert manifest.get("database") == ({"enabled": True} if kind == "web" else None)
    pyproject = tomllib.loads((repo / target / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == f"demo-{kind}"
    assert pyproject["project"]["dependencies"] == [
        f"insights-platform{sdk_pin(insights_platform.__version__)}"
    ]
    assert pyproject["tool"]["uv"]["sources"]["insights-platform"] == {"workspace": True}
    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        f"src/demo_{kind}"
    ]


@pytest.mark.parametrize("args", [("web",), ("web", "--no-frontend"), ("job",)])
def test_generated_app_passes_platform_check(repo: Path, args: tuple[str, ...]) -> None:
    generate(args[0], None, *args[1:])
    assert violations(repo) == []


def test_generated_apps_are_independent_of_each_other(repo: Path) -> None:
    generate("web")
    generate("job")
    assert violations(repo) == []


def test_team_defaults_to_name(repo: Path) -> None:
    target, _ = generate("web", "finance-rollup")
    manifest = tomllib.loads((repo / target / "platform.toml").read_text(encoding="utf-8"))
    assert manifest["app"]["team"] == "finance-rollup"


def test_dest_overrides_apps_dir(repo: Path) -> None:
    result = runner.invoke(app, ["new", "elsewhere", "--kind", "job", "--dest", "sandbox"])
    assert result.exit_code == 0, result.output
    assert (repo / "sandbox" / "elsewhere" / "platform.toml").is_file()
    assert "Created sandbox/elsewhere" in result.output


@pytest.mark.parametrize("name", ["Bad", "1abc", "has_underscore", "has space", "dots.here"])
def test_new_rejects_invalid_name(repo: Path, name: str) -> None:
    result = runner.invoke(app, ["new", name, "--kind", "web"])
    assert result.exit_code == 1
    assert "kebab-case" in result.output
    assert not (repo / "apps" / name).exists()


def test_new_refuses_existing_directory(repo: Path) -> None:
    (repo / "apps" / "taken").mkdir()
    result = runner.invoke(app, ["new", "taken", "--kind", "web"])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_new_requires_a_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["new", "orphan", "--kind", "web"])
    assert result.exit_code == 1
    assert "[tool.uv.workspace]" in result.output


def test_check_reports_clean_apps(repo: Path) -> None:
    generate("web")
    generate("job")
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "2 app(s) checked, no violations"


def test_check_reports_violations_with_adr(repo: Path) -> None:
    materialize(FIXTURES / "no-client-construction", repo)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 1
    assert "violates ADR-0005" in result.output
    assert "no violations" not in result.output


def test_check_accepts_explicit_paths(repo: Path) -> None:
    generate("web")
    generate("job")
    result = runner.invoke(app, ["check", "apps/demo-web"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "1 app(s) checked, no violations"


def test_check_rejects_missing_path(repo: Path) -> None:
    result = runner.invoke(app, ["check", "apps/nope"])
    assert result.exit_code == 1
    assert "is not a directory" in result.output


def test_check_with_no_apps(repo: Path) -> None:
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "0 app(s) checked, no violations"


def test_console_script_and_pytest_plugin_are_registered() -> None:
    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts")}
    assert scripts["insights"] == "insights_platform.cli:app"
    plugins = {ep.name: ep.value for ep in entry_points(group="pytest11")}
    assert plugins["insights_platform"] == "insights_platform.testing"


@pytest.mark.parametrize(
    ("version", "pin"),
    [("0.1.0", ">=0.1,<0.2"), ("0.9.3", ">=0.9,<0.10"), ("2.0.0", ">=2.0,<2.1")],
)
def test_sdk_pin_admits_the_release_and_its_patches(version: str, pin: str) -> None:
    assert sdk_pin(version) == pin


def owned_tables(url: str) -> set[str]:
    with closing(sqlite3.connect(str(make_url(url).database))) as conn:
        rows = conn.execute("select name from sqlite_master where type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_db_commands_migrate_the_generated_app(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, _ = generate("web", "demo-db", "--team", "people-analytics")
    url = f"sqlite+aiosqlite:///{(repo / 'migrations.db').as_posix()}"
    monkeypatch.setenv("INSIGHTS_DB_URL", url)

    upgrade = runner.invoke(app, ["db", "upgrade", "--app", target.as_posix()])
    assert upgrade.exit_code == 0, upgrade.output
    assert {"alembic_version", "records"} <= owned_tables(url)

    monkeypatch.chdir(repo / target / "src")
    current = runner.invoke(app, ["db", "current"])
    assert current.exit_code == 0, current.output
    assert "0001" in current.output
    monkeypatch.chdir(repo)

    revision = runner.invoke(app, ["db", "revision", "-m", "add notes", "--app", target.as_posix()])
    assert revision.exit_code == 0, revision.output
    versions = sorted((repo / target / "migrations" / "versions").glob("*.py"))
    assert [v.name for v in versions][:1] == ["0001_records.py"]
    assert len(versions) == 2 and versions[1].name.endswith("_add_notes.py")
    added = versions[1].read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "0001"' in added
    assert "import sqlalchemy" not in added

    downgrade = runner.invoke(app, ["db", "downgrade", "base", "--app", target.as_posix()])
    assert downgrade.exit_code == 0, downgrade.output
    assert "records" not in owned_tables(url)


def test_db_requires_an_enabled_database(repo: Path) -> None:
    target, _ = generate("job", "nightly")
    result = runner.invoke(app, ["db", "upgrade", "--app", target.as_posix()])
    assert result.exit_code == 1
    assert "[database] enabled = true" in result.output


def test_db_requires_the_url(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target, _ = generate("web", "web-app")
    monkeypatch.delenv("INSIGHTS_DB_URL")
    result = runner.invoke(app, ["db", "current", "--app", target.as_posix()])
    assert result.exit_code == 1
    assert "INSIGHTS_DB_URL" in result.output


def test_db_without_a_manifest_fails_cleanly(repo: Path) -> None:
    result = runner.invoke(app, ["db", "current"])
    assert result.exit_code == 1
    assert "no platform.toml" in result.output


def test_db_reports_database_errors_in_one_line(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target, _ = generate("web", "unreachable-db")
    monkeypatch.setenv(
        "INSIGHTS_DB_URL", f"sqlite+aiosqlite:///{(repo / 'missing' / 'x.db').as_posix()}"
    )
    result = runner.invoke(app, ["db", "upgrade", "--app", target.as_posix()])
    assert result.exit_code == 1
    assert "error: OperationalError: unable to open database file" in result.output
    assert "Traceback" not in result.output
