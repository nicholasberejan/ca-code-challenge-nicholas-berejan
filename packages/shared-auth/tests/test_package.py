"""Packaging tests: the package installs as a typed, Django-free distribution."""

import subprocess
import sys
import tomllib
from importlib.metadata import files, version
from pathlib import Path

import shared_auth

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_installed_version_matches_pyproject() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    assert version("shared-auth") == pyproject["project"]["version"]
    assert shared_auth.__version__ == pyproject["project"]["version"]


def test_tests_run_against_the_installed_package_not_the_source_tree() -> None:
    module_path = Path(shared_auth.__file__).resolve()

    assert PROJECT_ROOT / "src" not in module_path.parents


def test_distribution_ships_py_typed_marker() -> None:
    installed = files("shared-auth") or []

    assert any(path.name == "py.typed" for path in installed)


def test_core_import_does_not_load_django() -> None:
    code = "import sys, shared_auth; print('django' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "False"
