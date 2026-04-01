"""
Tests for requirements_installer.

Run with:
    pytest tests/
    pytest tests/ -v
"""

import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure the package root is importable regardless of how tests are run
sys.path.insert(0, str(Path(__file__).parent.parent))

from requirements_installer import (
    top_level_module,
    is_relative_import,
    find_dynamic_imports,
    parse_imports_from_code,
    parse_imports_from_file,
    parse_imports_from_notebook,
    is_stdlib_module,
    is_local_module,
    map_to_distribution,
    collect_requirements,
    generate_requirements_file,
    scan_project_config,
    _strip_dep_specifiers,
    is_conda_environment,
    invalidate_dist_cache,
    stdlib_names,
    load_module_mappings,
    MODULE_TO_DIST,
    summarize_install,
    install_packages,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_tmp(tmp_path: Path, filename: str, content: str) -> Path:
    p = tmp_path / filename
    p.write_text(content, encoding="utf-8")
    return p


def _make_notebook(cells: list) -> dict:
    """Minimal .ipynb structure with the given code cells."""
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [
            {"cell_type": "code", "source": src, "outputs": [], "metadata": {}}
            for src in cells
        ],
    }

# ---------------------------------------------------------------------------
# top_level_module
# ---------------------------------------------------------------------------

class TestTopLevelModule:
    def test_simple(self):
        assert top_level_module("numpy") == "numpy"

    def test_dotted(self):
        assert top_level_module("os.path") == "os"

    def test_deeply_dotted(self):
        assert top_level_module("a.b.c.d") == "a"

    def test_empty(self):
        assert top_level_module("") == ""

# ---------------------------------------------------------------------------
# is_relative_import
# ---------------------------------------------------------------------------

class TestIsRelativeImport:
    def test_relative(self):
        assert is_relative_import(".foo") is True
        assert is_relative_import("..bar") is True

    def test_absolute(self):
        assert is_relative_import("numpy") is False
        assert is_relative_import("os") is False

# ---------------------------------------------------------------------------
# find_dynamic_imports
# ---------------------------------------------------------------------------

class TestFindDynamicImports:
    def _parse(self, code: str) -> set:
        tree = ast.parse(code)
        return find_dynamic_imports(tree)

    def test_importlib_import_module(self):
        result = self._parse("import importlib; importlib.import_module('requests')")
        assert "requests" in result

    def test_bare_import_module(self):
        result = self._parse("from importlib import import_module; import_module('flask')")
        assert "flask" in result

    def test_dunder_import(self):
        result = self._parse("__import__('numpy')")
        assert "numpy" in result

    def test_dotted_module_extracts_top(self):
        result = self._parse("__import__('os.path')")
        assert "os" in result

    def test_variable_argument_ignored(self):
        result = self._parse("importlib.import_module(pkg_name)")
        assert len(result) == 0

    def test_no_dynamic_imports(self):
        result = self._parse("import os\nfrom sys import argv")
        assert len(result) == 0

# ---------------------------------------------------------------------------
# parse_imports_from_code
# ---------------------------------------------------------------------------

class TestParseImportsFromCode:
    def test_simple_import(self):
        result = parse_imports_from_code("import numpy")
        assert "numpy" in result

    def test_from_import(self):
        result = parse_imports_from_code("from flask import Flask")
        assert "flask" in result

    def test_dotted_from_import(self):
        result = parse_imports_from_code("from os.path import join")
        assert "os" in result

    def test_relative_import_excluded(self):
        result = parse_imports_from_code("from .utils import helper")
        assert len(result) == 0

    def test_relative_import_double_dot(self):
        result = parse_imports_from_code("from ..models import User")
        assert len(result) == 0

    def test_syntax_error_returns_empty(self):
        result = parse_imports_from_code("def foo(:\n    pass")
        assert result == set()

    def test_multiple_imports(self):
        code = "import numpy\nimport pandas\nfrom flask import Flask"
        result = parse_imports_from_code(code)
        assert {"numpy", "pandas", "flask"}.issubset(result)

    def test_import_as_alias(self):
        result = parse_imports_from_code("import numpy as np")
        assert "numpy" in result

    def test_dynamic_import_included(self):
        result = parse_imports_from_code("__import__('requests')")
        assert "requests" in result

    def test_none_module_from_import(self):
        # "from . import something" – node.module is None, should be skipped
        result = parse_imports_from_code("from . import utils")
        assert len(result) == 0

# ---------------------------------------------------------------------------
# parse_imports_from_file
# ---------------------------------------------------------------------------

class TestParseImportsFromFile:
    def test_reads_py_file(self, tmp_path):
        p = _write_tmp(tmp_path, "script.py", "import pandas\nfrom requests import get\n")
        modules, local = parse_imports_from_file(p)
        assert "pandas" in modules
        assert "requests" in modules
        assert local == set()

    def test_empty_file(self, tmp_path):
        p = _write_tmp(tmp_path, "empty.py", "")
        modules, local = parse_imports_from_file(p)
        assert modules == set()

# ---------------------------------------------------------------------------
# parse_imports_from_notebook
# ---------------------------------------------------------------------------

class TestParseImportsFromNotebook:
    def test_parses_code_cells(self, tmp_path):
        nb = _make_notebook(["import numpy\n", "from pandas import DataFrame\n"])
        p = tmp_path / "test.ipynb"
        p.write_text(json.dumps(nb), encoding="utf-8")
        result = parse_imports_from_notebook(p)
        assert "numpy" in result
        assert "pandas" in result

    def test_skips_magic_lines(self, tmp_path):
        nb = _make_notebook(["%matplotlib inline\nimport matplotlib\n", "!pip install foo\nimport bar\n"])
        p = tmp_path / "test.ipynb"
        p.write_text(json.dumps(nb), encoding="utf-8")
        result = parse_imports_from_notebook(p)
        assert "matplotlib" in result
        assert "bar" in result

    def test_skips_markdown_cells(self, tmp_path):
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {"cell_type": "markdown", "source": "import fake_package\n", "metadata": {}},
                {"cell_type": "code", "source": "import real_package\n", "outputs": [], "metadata": {}},
            ],
        }
        p = tmp_path / "test.ipynb"
        p.write_text(json.dumps(nb), encoding="utf-8")
        result = parse_imports_from_notebook(p)
        assert "real_package" in result
        assert "fake_package" not in result

    def test_missing_file_returns_empty(self, tmp_path):
        result = parse_imports_from_notebook(tmp_path / "nonexistent.ipynb")
        assert result == set()

    def test_invalid_json_returns_empty(self, tmp_path):
        p = _write_tmp(tmp_path, "broken.ipynb", "{not valid json")
        result = parse_imports_from_notebook(p)
        assert result == set()

    def test_source_as_list(self, tmp_path):
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {},
            "cells": [
                {
                    "cell_type": "code",
                    "source": ["import numpy\n", "import pandas\n"],
                    "outputs": [],
                    "metadata": {},
                }
            ],
        }
        p = tmp_path / "test.ipynb"
        p.write_text(json.dumps(nb), encoding="utf-8")
        result = parse_imports_from_notebook(p)
        assert {"numpy", "pandas"}.issubset(result)

# ---------------------------------------------------------------------------
# is_stdlib_module
# ---------------------------------------------------------------------------

class TestIsStdlibModule:
    def setup_method(self):
        self.stdlib = stdlib_names()

    def test_os_is_stdlib(self):
        assert is_stdlib_module("os", self.stdlib) is True

    def test_sys_is_stdlib(self):
        assert is_stdlib_module("sys", self.stdlib) is True

    def test_json_is_stdlib(self):
        assert is_stdlib_module("json", self.stdlib) is True

    def test_collections_is_stdlib(self):
        assert is_stdlib_module("collections", self.stdlib) is True

    def test_numpy_not_stdlib(self):
        assert is_stdlib_module("numpy", self.stdlib) is False

    def test_requests_not_stdlib(self):
        assert is_stdlib_module("requests", self.stdlib) is False

    def test_unknown_module_not_stdlib(self):
        assert is_stdlib_module("totally_fake_pkg_xyz123", self.stdlib) is False

# ---------------------------------------------------------------------------
# map_to_distribution
# ---------------------------------------------------------------------------

class TestMapToDistribution:
    def test_known_cv2(self):
        assert map_to_distribution("cv2") == "opencv-python"

    def test_known_sklearn(self):
        assert map_to_distribution("sklearn") == "scikit-learn"

    def test_known_pil(self):
        assert map_to_distribution("PIL") == "Pillow"

    def test_known_bs4(self):
        assert map_to_distribution("bs4") == "beautifulsoup4"

    def test_known_yaml(self):
        assert map_to_distribution("yaml") == "PyYAML"

    def test_unknown_passthrough(self):
        assert map_to_distribution("requests") == "requests"
        assert map_to_distribution("numpy") == "numpy"
        assert map_to_distribution("flask") == "Flask"

    def test_langchain_community(self):
        assert map_to_distribution("langchain_community") == "langchain-community"

    def test_langchain_openai(self):
        assert map_to_distribution("langchain_openai") == "langchain-openai"

# ---------------------------------------------------------------------------
# load_module_mappings
# ---------------------------------------------------------------------------

class TestLoadModuleMappings:
    def test_returns_dict(self):
        mappings = load_module_mappings()
        assert isinstance(mappings, dict)
        assert len(mappings) > 0

    def test_no_comment_keys(self):
        mappings = load_module_mappings()
        for key in mappings:
            assert not key.startswith("_"), f"Comment key leaked: {key!r}"

    def test_known_entries_present(self):
        mappings = load_module_mappings()
        assert mappings.get("cv2") == "opencv-python"
        assert mappings.get("sklearn") == "scikit-learn"

    def test_fallback_on_missing_file(self, tmp_path, monkeypatch):
        # Point __file__ to a directory without module_mappings.json
        import requirements_installer as ri
        monkeypatch.setattr(ri, "__file__", str(tmp_path / "requirements_installer.py"))
        mappings = ri.load_module_mappings()
        assert isinstance(mappings, dict)
        assert "cv2" in mappings  # fallback should still contain basics

    def test_fallback_on_corrupt_json(self, tmp_path, monkeypatch):
        bad_json = tmp_path / "module_mappings.json"
        bad_json.write_text("{broken", encoding="utf-8")
        import requirements_installer as ri
        monkeypatch.setattr(ri, "__file__", str(tmp_path / "requirements_installer.py"))
        mappings = ri.load_module_mappings()
        assert isinstance(mappings, dict)

# ---------------------------------------------------------------------------
# collect_requirements
# ---------------------------------------------------------------------------

class TestCollectRequirements:
    def test_third_party_detected(self, tmp_path):
        p = _write_tmp(tmp_path, "script.py", "import numpy\nimport pandas\n")
        result = collect_requirements(p, tmp_path)
        assert "numpy" in result
        assert "pandas" in result

    def test_stdlib_excluded(self, tmp_path):
        p = _write_tmp(tmp_path, "script.py", "import os\nimport sys\nimport json\n")
        result = collect_requirements(p, tmp_path)
        assert "os" not in result
        assert "sys" not in result
        assert "json" not in result

    def test_mapped_correctly(self, tmp_path):
        p = _write_tmp(tmp_path, "script.py", "import cv2\nfrom PIL import Image\n")
        result = collect_requirements(p, tmp_path)
        assert "opencv-python" in result
        assert "Pillow" in result

    def test_local_module_excluded(self, tmp_path):
        # Create a local module file
        _write_tmp(tmp_path, "mylocal.py", "# local helper\n")
        p = _write_tmp(tmp_path, "script.py", "import mylocal\nimport requests\n")
        result = collect_requirements(p, tmp_path)
        assert "mylocal" not in result
        assert "requests" in result

    def test_notebook_scanned(self, tmp_path):
        nb = _make_notebook(["import numpy\n", "from flask import Flask\n"])
        p = tmp_path / "notebook.ipynb"
        p.write_text(json.dumps(nb), encoding="utf-8")
        result = collect_requirements(p, tmp_path)
        assert "numpy" in result
        assert "Flask" in result

    def test_underscore_normalised_to_hyphen(self, tmp_path):
        p = _write_tmp(tmp_path, "script.py", "import langchain_community\n")
        result = collect_requirements(p, tmp_path)
        # langchain_community → langchain-community; underscores in result normalised
        assert all("-" in r or "_" not in r for r in result), \
            "Result should not contain underscores in distribution names"

# ---------------------------------------------------------------------------
# generate_requirements_file
# ---------------------------------------------------------------------------

class TestGenerateRequirementsFile:
    def test_creates_file(self, tmp_path):
        out = tmp_path / "requirements.txt"
        ok = generate_requirements_file({"numpy": "1.24.0", "requests": "2.28.0"}, out)
        assert ok is True
        assert out.exists()

    def test_file_content(self, tmp_path):
        out = tmp_path / "requirements.txt"
        generate_requirements_file({"numpy": "1.24.0", "requests": "2.28.0"}, out)
        content = out.read_text(encoding="utf-8")
        assert "numpy==1.24.0" in content
        assert "requests==2.28.0" in content

    def test_unknown_version_no_pin(self, tmp_path):
        out = tmp_path / "requirements.txt"
        generate_requirements_file({"mypkg": "unknown"}, out)
        content = out.read_text(encoding="utf-8")
        assert "mypkg" in content
        assert "==" not in content

    def test_sorted_alphabetically(self, tmp_path):
        out = tmp_path / "requirements.txt"
        generate_requirements_file({"zebra": "1.0", "apple": "2.0"}, out)
        lines = [ln for ln in out.read_text().splitlines() if not ln.startswith("#") and ln.strip()]
        assert lines[0].startswith("apple")
        assert lines[1].startswith("zebra")

    def test_returns_false_on_bad_path(self):
        bad = Path("/nonexistent_directory_xyz/requirements.txt")
        ok = generate_requirements_file({"pkg": "1.0"}, bad)
        assert ok is False

# ---------------------------------------------------------------------------
# scan_project_config
# ---------------------------------------------------------------------------

class TestScanProjectConfig:
    def test_pyproject_toml_pep621(self, tmp_path):
        toml = tmp_path / "pyproject.toml"
        toml.write_text(
            '[project]\ndependencies = [\n  "requests>=2.0",\n  "numpy",\n  "flask[async]>=2.0; python_version>\'3.7\'",\n]\n',
            encoding="utf-8",
        )
        result = scan_project_config(tmp_path)
        assert "requests" in result
        assert "numpy" in result
        assert "flask" in result

    def test_setup_cfg_install_requires(self, tmp_path):
        cfg = tmp_path / "setup.cfg"
        cfg.write_text(
            "[options]\ninstall_requires =\n    requests>=2.0\n    pandas\n",
            encoding="utf-8",
        )
        result = scan_project_config(tmp_path)
        assert "requests" in result
        assert "pandas" in result

    def test_empty_when_no_config_files(self, tmp_path):
        result = scan_project_config(tmp_path)
        assert result == set()

    def test_normalises_underscores_to_hyphens(self, tmp_path):
        cfg = tmp_path / "setup.cfg"
        cfg.write_text(
            "[options]\ninstall_requires =\n    my_package>=1.0\n",
            encoding="utf-8",
        )
        result = scan_project_config(tmp_path)
        assert "my-package" in result

# ---------------------------------------------------------------------------
# _strip_dep_specifiers
# ---------------------------------------------------------------------------

class TestStripDepSpecifiers:
    def test_plain_name(self):
        assert _strip_dep_specifiers("requests") == "requests"

    def test_version_ge(self):
        assert _strip_dep_specifiers("requests>=2.0") == "requests"

    def test_version_eq(self):
        assert _strip_dep_specifiers("requests==2.28.0") == "requests"

    def test_extras(self):
        assert _strip_dep_specifiers("flask[async]>=2.0") == "flask"

    def test_marker(self):
        assert _strip_dep_specifiers("pywin32; sys_platform=='win32'") == "pywin32"

    def test_empty_returns_empty(self):
        assert _strip_dep_specifiers("") == ""

    def test_comment_returns_empty(self):
        assert _strip_dep_specifiers("# a comment") == ""

    def test_underscore_normalised(self):
        assert _strip_dep_specifiers("my_package>=1.0") == "my-package"

# ---------------------------------------------------------------------------
# is_conda_environment
# ---------------------------------------------------------------------------

class TestIsCondaEnvironment:
    def test_detected_via_conda_default_env(self, monkeypatch):
        monkeypatch.setenv("CONDA_DEFAULT_ENV", "myenv")
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        assert is_conda_environment() is True

    def test_detected_via_conda_prefix(self, monkeypatch):
        monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
        monkeypatch.setenv("CONDA_PREFIX", "/opt/conda/envs/myenv")
        assert is_conda_environment() is True

    def test_not_detected_without_env_vars(self, monkeypatch, tmp_path):
        monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
        monkeypatch.delenv("CONDA_PREFIX", raising=False)
        # Patch sys.prefix to a temp dir without conda-meta
        monkeypatch.setattr(sys, "prefix", str(tmp_path))
        assert is_conda_environment() is False

# ---------------------------------------------------------------------------
# invalidate_dist_cache
# ---------------------------------------------------------------------------

class TestInvalidateDistCache:
    def test_clears_all(self):
        import requirements_installer as ri
        ri._dist_cache["fake_key"] = {"pkg"}
        invalidate_dist_cache()
        assert ri._dist_cache == {}

    def test_clears_specific_key(self):
        import requirements_installer as ri
        # Use Path objects as keys so the string representation matches on all platforms
        path1 = Path(sys.executable)
        path2 = Path(sys.executable + "_other")
        key1, key2 = str(path1), str(path2)
        ri._dist_cache[key1] = {"pkg_a"}
        ri._dist_cache[key2] = {"pkg_b"}
        invalidate_dist_cache(path1)
        assert key1 not in ri._dist_cache
        assert key2 in ri._dist_cache
        # Cleanup
        ri._dist_cache.clear()

# ---------------------------------------------------------------------------
# summarize_install
# ---------------------------------------------------------------------------

class TestSummarizeInstall:
    def test_newly_installed(self):
        before = {"existing"}
        after = {"existing", "newpkg"}
        requested = {"newpkg"}
        newly, already = summarize_install(before, after, requested)
        assert "newpkg" in newly
        assert already == set()

    def test_already_present(self):
        before = {"requests"}
        after = {"requests"}
        requested = {"requests"}
        newly, already = summarize_install(before, after, requested)
        assert newly == set()
        assert "requests" in already

    def test_case_insensitive(self):
        before = {"numpy"}
        after = {"numpy"}
        requested = {"NumPy"}  # different case in requested
        newly, already = summarize_install(before, after, requested)
        assert "NumPy" in already

# ---------------------------------------------------------------------------
# install_packages (dry-run only — we don't want real pip calls in tests)
# ---------------------------------------------------------------------------

class TestInstallPackages:
    def test_dry_run_returns_true(self):
        ok, output = install_packages(
            [sys.executable, "-m", "pip"], {"requests"}, dry_run=True
        )
        assert ok is True
        assert output == ""

    def test_empty_pkgs_returns_true(self):
        ok, output = install_packages([sys.executable, "-m", "pip"], set())
        assert ok is True

    def test_dry_run_does_not_call_subprocess(self, monkeypatch):
        calls = []
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: calls.append(a))
        install_packages([sys.executable, "-m", "pip"], {"fake_pkg_xyz"}, dry_run=True)
        assert calls == []

# ---------------------------------------------------------------------------
# Module-level mappings completeness
# ---------------------------------------------------------------------------

class TestModuleMappingsCompleteness:
    """Smoke-test that key ecosystem entries are present in the loaded mappings."""

    @pytest.mark.parametrize("import_name,expected_pkg", [
        ("cv2", "opencv-python"),
        ("PIL", "Pillow"),
        ("sklearn", "scikit-learn"),
        ("bs4", "beautifulsoup4"),
        ("yaml", "PyYAML"),
        ("langchain_community", "langchain-community"),
        ("langchain_openai", "langchain-openai"),
        ("langchain_anthropic", "langchain-anthropic"),
        ("sentence_transformers", "sentence-transformers"),
        ("huggingface_hub", "huggingface-hub"),
        ("dotenv", "python-dotenv"),
        ("jwt", "PyJWT"),
        ("psycopg2", "psycopg2-binary"),
        ("serial", "pyserial"),
        ("git", "GitPython"),
        ("factory", "factory-boy"),
        ("pytest_mock", "pytest-mock"),
        ("pytest_asyncio", "pytest-asyncio"),
    ])
    def test_mapping_present(self, import_name, expected_pkg):
        assert MODULE_TO_DIST.get(import_name) == expected_pkg, (
            f"Expected MODULE_TO_DIST[{import_name!r}] == {expected_pkg!r}, "
            f"got {MODULE_TO_DIST.get(import_name)!r}"
        )
