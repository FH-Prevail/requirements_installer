#!/usr/bin/env python3
"""
requirements_installer
======================

A zero-dependency utility that automatically detects and installs missing
third-party packages from Python scripts and Jupyter notebooks.

Architecture
------------
1. **Import detection** – AST-based parsing of ``import`` / ``from … import``
   statements plus dynamic-import detection (``importlib.import_module``,
   ``__import__``).
2. **Filtering** – stdlib and project-local modules are excluded.
3. **Mapping** – import names are resolved to PyPI distribution names via
   ``module_mappings.json``.
4. **Installation** – missing distributions are installed via pip (optionally
   inside a fresh virtual environment or conda environment).
5. **Reporting** – a concise summary is logged; an optional ``requirements.txt``
   can be generated with pinned versions.

Usage
-----
Command line::

    requirements_installer --file mycode.py
    requirements_installer --file mycode.py --use-venv
    requirements_installer --file mycode.py --dry-run
    requirements_installer --file notebook.ipynb --generate-requirements
    requirements_installer --file mycode.py --scan-config

Inside Python code::

    from requirements_installer import auto_install
    auto_install()

In Jupyter / Colab::

    !pip install requirements_installer
    from requirements_installer import auto_install
    auto_install()
"""

import argparse
import ast
import importlib.util
import logging
import os
import sys
import subprocess
import textwrap
import inspect
import json
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("requirements_installer")


def _setup_logger(quiet: bool = False, verbose: bool = False) -> None:
    """Configure the module-level logger (idempotent)."""
    if logger.handlers:
        # Already configured – just adjust level
        if quiet:
            logger.setLevel(logging.ERROR)
        elif verbose:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    if quiet:
        logger.setLevel(logging.ERROR)
    elif verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)


# Initialise with INFO so the logger is usable when the module is imported
# without explicitly calling auto_install().
_setup_logger()

# ---------------------------------------------------------------------------
# Module-name → PyPI distribution-name mappings
# ---------------------------------------------------------------------------

def load_module_mappings() -> Dict[str, str]:
    """
    Load module-to-package mappings from ``module_mappings.json``.

    Falls back to a minimal hard-coded set if the file is missing or corrupt.
    Only entries where the import name **differs** from the PyPI package name
    are stored – everything else is handled by the identity fallback in
    :func:`map_to_distribution`.
    """
    _FALLBACK: Dict[str, str] = {
        "cv2": "opencv-python",
        "PIL": "Pillow",
        "sklearn": "scikit-learn",
        "yaml": "PyYAML",
        "bs4": "beautifulsoup4",
    }
    try:
        mappings_file = Path(__file__).parent / "module_mappings.json"
        if mappings_file.exists():
            with open(mappings_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return {k: v for k, v in data.items() if not k.startswith("_")}
        logger.debug("module_mappings.json not found; using built-in fallback.")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load module mappings (%s); using fallback.", exc)
    return dict(_FALLBACK)


MODULE_TO_DIST: Dict[str, str] = load_module_mappings()

# ---------------------------------------------------------------------------
# Standard-library detection
# ---------------------------------------------------------------------------

STDLIB_FALLBACK: Set[str] = {
    "abc", "argparse", "array", "asyncio", "base64", "binascii", "bisect",
    "builtins", "calendar", "cmath", "collections", "concurrent", "configparser",
    "contextlib", "copy", "csv", "ctypes", "datetime", "decimal", "difflib",
    "email", "enum", "errno", "faulthandler", "fnmatch", "fractions", "functools",
    "gc", "getopt", "getpass", "gettext", "glob", "gzip", "hashlib", "heapq",
    "hmac", "html", "http", "imaplib", "importlib", "inspect", "io", "ipaddress",
    "itertools", "json", "keyword", "linecache", "locale", "logging", "lzma",
    "math", "mimetypes", "multiprocessing", "numbers", "operator", "os",
    "pathlib", "pickle", "pkgutil", "platform", "plistlib", "pprint", "profile",
    "pstats", "queue", "random", "re", "resource", "sched", "secrets", "select",
    "selectors", "shlex", "shutil", "signal", "site", "smtplib", "socket",
    "sqlite3", "ssl", "stat", "statistics", "string", "stringprep", "struct",
    "subprocess", "sys", "sysconfig", "tarfile", "tempfile", "textwrap",
    "threading", "time", "timeit", "tkinter", "token", "traceback", "types",
    "typing", "unicodedata", "unittest", "urllib", "uuid", "venv", "warnings",
    "weakref", "xml", "xmlrpc", "zipfile", "zoneinfo",
}


def stdlib_names() -> Set[str]:
    """Return the set of standard-library module names for the running interpreter."""
    names: Set[str] = set()
    try:
        names.update(sys.stdlib_module_names)  # type: ignore[attr-defined]  # Py 3.10+
    except AttributeError:
        pass
    if not names:
        names.update(STDLIB_FALLBACK)
    return names

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def top_level_module(name: str) -> str:
    """Return the top-level component of a dotted module name."""
    return name.split(".", 1)[0]


def is_relative_import(mod: str) -> bool:
    """Return True when *mod* starts with a dot (relative import)."""
    return mod.startswith(".")


def find_dynamic_imports(node: ast.AST) -> Set[str]:
    """
    Detect dynamic imports in an AST tree.

    Handles:

    * ``importlib.import_module("pkg")``
    * ``import_module("pkg")``
    * ``__import__("pkg")``

    Only string-literal arguments are processed; variable-based dynamic
    imports cannot be resolved statically.
    """
    found: Set[str] = set()
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        func = n.func
        is_importlib_call = (
            isinstance(func, ast.Attribute)
            and getattr(func.value, "id", None) == "importlib"
            and func.attr == "import_module"
        )
        is_import_module = isinstance(func, ast.Name) and func.id == "import_module"
        is_dunder_import = isinstance(func, ast.Name) and func.id == "__import__"

        if (is_importlib_call or is_import_module or is_dunder_import) and n.args:
            first_arg = n.args[0]
            if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                found.add(top_level_module(first_arg.value))
    return found


def parse_imports_from_code(code: str, filename: str = "<string>") -> Set[str]:
    """Return all absolute top-level module names imported by *code*."""
    modules: Set[str] = set()
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError:
        return modules  # skip unparseable cells / snippets silently
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = top_level_module(alias.name)
                if not is_relative_import(mod):
                    modules.add(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None or (node.level and node.level > 0):
                continue
            mod = top_level_module(node.module)
            if not is_relative_import(mod):
                modules.add(mod)
    modules |= find_dynamic_imports(tree)
    return modules


def parse_imports_from_file(path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Return ``(all_modules, local_modules)`` parsed from *path*.

    ``local_modules`` is always empty – local detection is handled separately
    by :func:`is_local_module`.
    """
    code = path.read_text(encoding="utf-8", errors="ignore")
    return parse_imports_from_code(code, str(path)), set()


def parse_imports_from_notebook(notebook_path: Path) -> Set[str]:
    """Parse all imports from a Jupyter notebook (``.ipynb``)."""
    modules: Set[str] = set()
    try:
        with open(notebook_path, "r", encoding="utf-8") as fh:
            notebook = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not parse notebook %s: %s", notebook_path, exc)
        return modules

    for cell in notebook.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = cell.get("source", [])
        raw = "".join(source) if isinstance(source, list) else source
        # Strip IPython magic / shell lines before AST parsing
        clean_lines = [
            ln for ln in raw.splitlines()
            if not ln.strip().startswith(("!", "%"))
        ]
        modules |= parse_imports_from_code("\n".join(clean_lines), str(notebook_path))
    return modules

# ---------------------------------------------------------------------------
# pyproject.toml / setup.cfg dependency scanning
# ---------------------------------------------------------------------------

def scan_project_config(project_root: Path) -> Set[str]:
    """
    Extract declared dependencies from ``pyproject.toml`` and/or ``setup.cfg``
    found in *project_root*.

    Supports:

    * PEP 621 ``[project] dependencies``
    * setuptools ``[options] install_requires``

    Returns a set of lower-cased, normalised distribution names.
    """
    declared: Set[str] = set()

    # --- pyproject.toml ---
    toml_path = project_root / "pyproject.toml"
    if toml_path.exists():
        try:
            try:
                import tomllib  # type: ignore[import]  # Py 3.11+
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[import, no-redef]
                except ImportError:
                    tomllib = None  # type: ignore[assignment]

            if tomllib is not None:
                with open(toml_path, "rb") as fh:
                    data = tomllib.load(fh)
                deps: List[str] = data.get("project", {}).get("dependencies", [])
                for dep in deps:
                    pkg = _strip_dep_specifiers(dep)
                    if pkg:
                        declared.add(pkg)
            else:
                # Last-resort line-based parser (no tomllib / tomli installed)
                _parse_toml_deps_text(toml_path, declared)
        except Exception as exc:
            logger.debug("Could not parse pyproject.toml: %s", exc)

    # --- setup.cfg ---
    cfg_path = project_root / "setup.cfg"
    if cfg_path.exists():
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(str(cfg_path), encoding="utf-8")
            raw = cp.get("options", "install_requires", fallback="")
            for line in raw.splitlines():
                pkg = _strip_dep_specifiers(line)
                if pkg:
                    declared.add(pkg)
        except Exception as exc:
            logger.debug("Could not parse setup.cfg: %s", exc)

    return declared


def _strip_dep_specifiers(dep: str) -> str:
    """
    Strip version specifiers, extras, and environment markers from a PEP 508
    dependency string.  Returns the normalised (lower-case, hyphenated) name.
    """
    pkg = dep.strip()
    if not pkg or pkg.startswith("#"):
        return ""
    # Remove environment markers
    pkg = pkg.split(";")[0]
    # Remove extras
    pkg = pkg.split("[")[0]
    # Remove version specifiers
    for op in (">=", "<=", "!=", "==", "~=", ">", "<"):
        pkg = pkg.split(op)[0]
    return pkg.strip().replace("_", "-").lower()


def _parse_toml_deps_text(path: Path, target: Set[str]) -> None:
    """Minimal line-based fallback parser for pyproject.toml ``dependencies``."""
    in_deps = False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped in ("dependencies = [", 'dependencies = ['):
                in_deps = True
                continue
            if in_deps:
                if stripped.startswith("]"):
                    break
                pkg = _strip_dep_specifiers(stripped.strip('",\' '))
                if pkg:
                    target.add(pkg)
    except OSError:
        pass

# ---------------------------------------------------------------------------
# Module classification
# ---------------------------------------------------------------------------

def is_stdlib_module(mod: str, stdlib: Set[str]) -> bool:
    """Return True if *mod* is part of the Python standard library."""
    if mod in stdlib or mod in sys.builtin_module_names:
        return True
    try:
        spec = importlib.util.find_spec(mod)
        if spec and spec.origin:
            origin = str(spec.origin).lower()
            base = str(Path(sys.base_prefix)).lower()
            if "python" in origin and base in origin and "site-packages" not in origin:
                return True
    except (ModuleNotFoundError, ValueError):
        pass
    return False


def is_local_module(mod: str, project_root: Path) -> bool:
    """
    Return True when *mod* resolves to a file/package inside *project_root*
    that is **not** inside a virtual environment or conda environment.
    """
    VENV_INDICATORS = {
        "venv", ".venv", "env", ".env", "virtualenv", ".virtualenv",
        "conda", "miniconda", "anaconda", ".conda",
    }
    try:
        spec = importlib.util.find_spec(mod)
        if not spec or not spec.origin:
            pkg_dir = project_root / mod
            py_file = project_root / f"{mod}.py"
            return pkg_dir.exists() or py_file.exists()

        origin = Path(spec.origin).resolve()
        try:
            root = project_root.resolve()
            if root not in origin.parents:
                return False
            for parent in origin.parents:
                if parent == root:
                    break
                if parent.name.lower() in VENV_INDICATORS:
                    return False
                if (parent / "pyvenv.cfg").exists():
                    return False
                if (parent / "conda-meta").exists():
                    return False
            return True
        except (ValueError, OSError):
            return False
    except (ModuleNotFoundError, ValueError):
        pkg_dir = project_root / mod
        py_file = project_root / f"{mod}.py"
        return pkg_dir.exists() or py_file.exists()


def map_to_distribution(mod: str) -> str:
    """Map an import name to its PyPI distribution name."""
    return MODULE_TO_DIST.get(mod, mod)

# ---------------------------------------------------------------------------
# Conda / environment detection
# ---------------------------------------------------------------------------

def is_conda_environment() -> bool:
    """Return True when the current interpreter lives inside a conda environment."""
    return (
        os.environ.get("CONDA_DEFAULT_ENV") is not None
        or os.environ.get("CONDA_PREFIX") is not None
        or (Path(sys.prefix) / "conda-meta").exists()
    )


def _conda_installed_lower() -> Optional[Set[str]]:
    """
    Return the set of lower-cased package names known to conda, or ``None``
    if conda is not available / not active.
    """
    try:
        out = subprocess.check_output(
            ["conda", "list", "--json"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        entries = json.loads(out)
        return {e["name"].lower() for e in entries if "name" in e}
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None

# ---------------------------------------------------------------------------
# Package management
# ---------------------------------------------------------------------------

# In-process cache: {python_exe_path: frozenset_of_dist_names}
_dist_cache: Dict[str, Set[str]] = {}


def installed_distributions_lower(pip_python: Path) -> Set[str]:
    """
    Return the lower-cased distribution names visible to *pip_python*.

    Results are cached per interpreter path for the lifetime of the process
    so that repeated calls within the same session are cheap.  Call
    :func:`invalidate_dist_cache` after installing new packages.
    """
    key = str(pip_python)
    if key in _dist_cache:
        return _dist_cache[key]

    code = (
        "import importlib.metadata as m, json; "
        "print(json.dumps([d.metadata['Name'].lower() for d in m.distributions()"
        " if 'Name' in d.metadata]))"
    )
    out = subprocess.check_output([str(pip_python), "-c", code], text=True)
    result: Set[str] = set(json.loads(out))
    _dist_cache[key] = result
    return result


def invalidate_dist_cache(pip_python: Optional[Path] = None) -> None:
    """
    Invalidate the installed-distributions cache.

    Pass *pip_python* to invalidate only that interpreter's entry, or omit it
    to clear the entire cache.
    """
    if pip_python is None:
        _dist_cache.clear()
    else:
        _dist_cache.pop(str(pip_python), None)


def get_installed_versions(pip_python: Path, packages: Set[str]) -> Dict[str, str]:
    """Return ``{package_name: version}`` for each name in *packages*."""
    packages_list = list(packages)
    code = f"""
import importlib.metadata as m
import json
result = {{}}
for pkg in {packages_list!r}:
    try:
        result[pkg] = m.version(pkg)
    except Exception:
        result[pkg] = "unknown"
print(json.dumps(result))
""".strip()
    try:
        out = subprocess.check_output([str(pip_python), "-c", code], text=True)
        return json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {pkg: "unknown" for pkg in packages}


def ensure_venv(venv_path: Path) -> Tuple[Path, List[str]]:
    """
    Create a virtual environment at *venv_path* if it does not already exist.

    Handles concurrent creation gracefully (``FileExistsError`` is swallowed).
    Returns ``(python_exe, pip_cmd_list)``.
    """
    from venv import EnvBuilder

    if not venv_path.exists():
        logger.info("Creating virtual environment at: %s", venv_path)
        try:
            EnvBuilder(with_pip=True, clear=False, upgrade=False, symlinks=True).create(
                str(venv_path)
            )
        except FileExistsError:
            # Another process created the venv between our check and create.
            logger.debug("venv already exists (concurrent creation): %s", venv_path)
        except OSError as exc:
            logger.error("Failed to create venv at %s: %s", venv_path, exc)
            raise

    py_exe = venv_path / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    return py_exe, [str(py_exe), "-m", "pip"]


def current_pip_cmd() -> Tuple[Path, List[str]]:
    """Return ``(python_exe, pip_cmd_list)`` for the current interpreter."""
    py = Path(sys.executable)
    return py, [str(py), "-m", "pip"]


def collect_requirements(entry_file: Path, project_root: Path) -> Set[str]:
    """
    Parse *entry_file* (and any directly imported local files) for third-party
    distribution names.

    Notebooks (``.ipynb``) are handled separately.  For regular Python files,
    a single one-hop follow of local imports is performed to catch transitive
    dependencies declared inside local helper modules.
    """
    stdlib = stdlib_names()
    all_modules: Set[str] = set()

    if entry_file.suffix == ".ipynb":
        all_modules.update(parse_imports_from_notebook(entry_file))
    else:
        def _add(path: Path) -> None:
            mods, _ = parse_imports_from_file(path)
            all_modules.update(mods)

        _add(entry_file)
        # One-hop: follow local imports
        for mod in list(all_modules):
            if is_local_module(mod, project_root):
                pkg_dir = project_root / mod
                if (pkg_dir / "__init__.py").exists():
                    _add(pkg_dir / "__init__.py")
                elif (project_root / f"{mod}.py").exists():
                    _add(project_root / f"{mod}.py")

    third_party: Set[str] = {
        mod for mod in all_modules
        if mod
        and not is_stdlib_module(mod, stdlib)
        and not is_local_module(mod, project_root)
    }

    dists = {map_to_distribution(m) for m in third_party}
    return {d.replace("_", "-") for d in dists}


def generate_requirements_file(packages_versions: Dict[str, str], output_path: Path) -> bool:
    """
    Write a pinned ``requirements.txt`` to *output_path*.

    Returns ``True`` on success, ``False`` on ``OSError``.
    """
    try:
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write("# Generated by requirements_installer\n")
            fh.write("# Install with: pip install -r requirements.txt\n\n")
            for package in sorted(packages_versions):
                version = packages_versions[package]
                if version and version != "unknown":
                    fh.write(f"{package}=={version}\n")
                else:
                    fh.write(f"{package}\n")
        return True
    except OSError as exc:
        logger.error("Error writing requirements file: %s", exc)
        return False


def ask_for_version(package: str) -> str:
    """
    Prompt the user for a version preference.

    Returns a pip-compatible specifier such as ``"package"`` or
    ``"package==1.2.3"``.
    """
    while True:
        response = input(f"\nInstall latest version of '{package}'? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            return package
        if response in ("n", "no"):
            version = input(f"Enter version for '{package}' (e.g. 1.2.3): ").strip()
            return f"{package}=={version}" if version else package
        print("Please answer 'y' or 'n'.")


def install_packages(
    pip_cmd: List[str],
    pkgs: Set[str],
    ask_version: bool = False,
    dry_run: bool = False,
) -> Tuple[bool, str]:
    """
    Install *pkgs* using *pip_cmd*.

    Parameters
    ----------
    pip_cmd:
        Full pip invocation prefix, e.g. ``["/path/to/python", "-m", "pip"]``.
    pkgs:
        Distribution names to install.
    ask_version:
        When True, interactively prompt for version preferences.
    dry_run:
        When True, log what would be installed without running pip.

    Returns
    -------
    ``(success, combined_stdout_stderr)``
    """
    if not pkgs:
        return True, "Nothing to install."

    if ask_version:
        logger.info("\n" + "=" * 50)
        logger.info("Version Selection")
        logger.info("=" * 50)
        packages_to_install = [ask_for_version(pkg) for pkg in sorted(pkgs)]
    else:
        packages_to_install = sorted(pkgs)

    if dry_run:
        logger.info("[dry-run] Would install: %s", " ".join(packages_to_install))
        return True, ""

    cmd = list(pip_cmd) + ["install", "--upgrade"] + packages_to_install
    logger.info("Installing: %s", " ".join(packages_to_install))
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return proc.returncode == 0, proc.stdout + "\n" + proc.stderr


def summarize_install(
    before: Set[str], after: Set[str], requested: Set[str]
) -> Tuple[Set[str], Set[str]]:
    """Return ``(newly_installed, already_present)`` for the requested packages."""
    newly = {p for p in requested if p.lower() in after and p.lower() not in before}
    already = {p for p in requested if p.lower() in before}
    return newly, already

# ---------------------------------------------------------------------------
# Caller / Jupyter detection
# ---------------------------------------------------------------------------

def get_caller_file() -> Optional[Path]:
    """
    Walk the call stack to find the file that invoked ``auto_install()``.

    Returns ``None`` when called from an interactive session (``<stdin>``,
    ``<ipython>``, etc.).
    """
    frame = inspect.currentframe()
    try:
        for _ in range(10):  # limit stack depth for safety
            if frame is None:
                break
            frame = frame.f_back
            if frame is None:
                break
            filename = frame.f_code.co_filename
            if filename == __file__ or filename.startswith("<"):
                continue
            path = Path(filename)
            if path.exists():
                return path.resolve()
    finally:
        del frame  # prevent reference cycle
    return None


def is_jupyter_environment() -> bool:
    """Return True when running inside Jupyter / IPython / Colab."""
    try:
        get_ipython()  # type: ignore[name-defined]
        return True
    except NameError:
        return False


def find_jupyter_notebook() -> Optional[Path]:
    """
    Attempt to locate the currently open notebook file.

    Detection strategy (in order of reliability):

    1. **Google Colab** – scan ``/content/`` and ``/content/drive/MyDrive/``.
    2. **Kernel-ID matching** – parse the running kernel's connection-file name
       and look for a matching ``kernel_id`` inside notebook metadata.
    3. **Single-notebook fallback** – if only one ``.ipynb`` exists in the
       current working directory, assume it is the active one.
    4. **Most-recent fallback** – if multiple notebooks exist, return the most
       recently modified one (heuristic, may be incorrect).

    Returns the resolved :class:`~pathlib.Path`, or ``None``.
    """
    try:
        ipython = get_ipython()  # type: ignore[name-defined]
    except NameError:
        return None

    # --- Strategy 1: Google Colab ---
    if "google.colab" in str(type(ipython)):
        import glob as _glob
        candidates = (
            _glob.glob("/content/*.ipynb")
            + _glob.glob("/content/drive/MyDrive/**/*.ipynb", recursive=True)
        )
        if candidates:
            try:
                return Path(max(candidates, key=lambda x: Path(x).stat().st_mtime)).resolve()
            except OSError:
                pass
        return None

    # --- Strategy 2: kernel-ID matching ---
    kernel_id: Optional[str] = None
    try:
        import ipykernel  # type: ignore[import]
        conn_file = ipykernel.get_connection_file()
        # Connection file is typically "kernel-<UUID>.json"
        kernel_id = Path(conn_file).stem.split("-", 1)[-1]
    except Exception:
        pass

    if kernel_id:
        for nb_path in Path.cwd().rglob("*.ipynb"):
            try:
                with open(nb_path, "r", encoding="utf-8") as fh:
                    nb_data = json.load(fh)
                # Some kernels embed an ID in kernelspec metadata
                if kernel_id in json.dumps(nb_data.get("metadata", {})):
                    return nb_path.resolve()
            except (OSError, json.JSONDecodeError):
                continue

    # --- Strategy 3 & 4: cwd notebooks ---
    notebooks = list(Path.cwd().glob("*.ipynb"))
    if len(notebooks) == 1:
        return notebooks[0].resolve()
    if notebooks:
        try:
            return max(notebooks, key=lambda x: x.stat().st_mtime).resolve()
        except OSError:
            pass

    return None


def parse_imports_from_ipython() -> Set[str]:
    """
    Return all imported module names visible in the current IPython session.

    Prefers reading every cell from the notebook file on disk (so unexecuted
    cells are included).  Falls back to the executed-cell history stored in
    ``IPython.In`` when the file cannot be located.
    """
    nb_path = find_jupyter_notebook()
    if nb_path and nb_path.exists():
        logger.info("Found notebook: %s", nb_path.name)
        return parse_imports_from_notebook(nb_path)

    logger.info("Scanning executed cells only (notebook file not found).")
    modules: Set[str] = set()
    try:
        ipython = get_ipython()  # type: ignore[name-defined]
        for cell_code in ipython.user_ns.get("In", []):
            if not isinstance(cell_code, str) or not cell_code.strip():
                continue
            clean = "\n".join(
                ln for ln in cell_code.splitlines()
                if not ln.strip().startswith(("!", "%"))
            )
            modules |= parse_imports_from_code(clean, "<ipython>")
    except Exception as exc:
        logger.warning("Could not read IPython history: %s", exc)
    return modules

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_install(
    file_path: Optional[str] = None,
    use_venv: bool = False,
    venv_path: str = ".venv",
    quiet: bool = False,
    verbose: bool = False,
    generate_requirements: bool = False,
    requirements_path: str = "requirements.txt",
    dry_run: bool = False,
) -> None:
    """
    Automatically install dependencies for the calling script or notebook.

    Parameters
    ----------
    file_path:
        Path to the file to scan.  Auto-detects the caller when omitted.
    use_venv:
        Create and use an isolated virtual environment.
    venv_path:
        Where to create the venv (default: ``".venv"``).
    quiet:
        Suppress all output except errors.
    verbose:
        Emit debug-level messages (overrides *quiet*).
    generate_requirements:
        Write a pinned ``requirements.txt`` after installation.
    requirements_path:
        Destination path for the requirements file.
    dry_run:
        Show what would be installed without actually modifying the environment.

    Usage in a Python script::

        from requirements_installer import auto_install
        auto_install()

    Usage in Jupyter / Colab::

        !pip install requirements_installer
        from requirements_installer import auto_install
        auto_install()
    """
    _setup_logger(quiet=quiet, verbose=verbose)

    in_jupyter = is_jupyter_environment()

    # --- Determine what to scan ---
    if file_path:
        entry_file = Path(file_path).resolve()
        if not entry_file.exists():
            logger.error("File not found: %s", entry_file)
            return
        project_root = entry_file.parent
        logger.info("Scanning: %s", entry_file.name)
        required = collect_requirements(entry_file, project_root)

    elif in_jupyter:
        logger.info("Scanning Jupyter/Colab notebook...")
        all_modules = parse_imports_from_ipython()
        stdlib = stdlib_names()
        third_party = {m for m in all_modules if m and not is_stdlib_module(m, stdlib)}
        dists = {map_to_distribution(m) for m in third_party}
        required = {d.replace("_", "-") for d in dists}
        project_root = Path.cwd()

    else:
        entry_file = get_caller_file()
        if entry_file is None or not entry_file.exists():
            logger.error(
                "Could not detect file to scan. Provide the file_path argument.\n"
                "  Usage: auto_install('your_script.py')"
            )
            return
        project_root = entry_file.parent
        logger.info("Scanning: %s", entry_file.name)
        required = collect_requirements(entry_file, project_root)

    if not required:
        logger.info("No external packages needed.")
        return

    if dry_run:
        logger.info("[dry-run] Would install: %s", ", ".join(sorted(required)))
        return

    # --- Setup environment ---
    if use_venv:
        venv_path_obj = Path(venv_path).resolve()
        py_exe, pip_cmd = ensure_venv(venv_path_obj)
    else:
        py_exe, pip_cmd = current_pip_cmd()

    try:
        before = installed_distributions_lower(py_exe)
    except subprocess.CalledProcessError as exc:
        logger.warning("Could not query installed packages: %s", exc)
        before = set()

    needed = {p for p in required if p.lower() not in before}

    if not needed:
        logger.info("All packages already installed: %s", ", ".join(sorted(required)))
        if generate_requirements and required:
            _write_requirements(py_exe, required, requirements_path)
        return

    logger.info("Installing %d package(s)...", len(needed))
    _ok, output = install_packages(pip_cmd, needed)

    invalidate_dist_cache(py_exe)
    try:
        after = installed_distributions_lower(py_exe)
    except subprocess.CalledProcessError:
        after = set()

    newly, already = summarize_install(before, after, required)
    if newly:
        logger.info("Installed: %s", ", ".join(sorted(newly)))
    if already:
        logger.info("Already present: %s", ", ".join(sorted(already)))

    missing = sorted(p for p in required if p.lower() not in after)
    if missing:
        logger.error("Failed to install: %s", ", ".join(missing))
        logger.debug("pip output:\n%s", output)

    if generate_requirements and required:
        _write_requirements(py_exe, required, requirements_path)


def _write_requirements(py_exe: Path, required: Set[str], requirements_path: str) -> None:
    """Internal helper: generate requirements.txt and log the result."""
    logger.info("Generating %s...", requirements_path)
    versions = get_installed_versions(py_exe, required)
    if generate_requirements_file(versions, Path(requirements_path)):
        logger.info("Generated %s with %d package(s).", requirements_path, len(versions))
    else:
        logger.error("Failed to generate %s.", requirements_path)

# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line interface for requirements_installer."""
    ap = argparse.ArgumentParser(
        description="Scan a Python file for third-party imports and install them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              requirements_installer --file mycode.py
              requirements_installer --file mycode.py --use-venv
              requirements_installer --file mycode.py --ask-version
              requirements_installer --file mycode.py --dry-run
              requirements_installer --file notebook.ipynb
              requirements_installer --file mycode.py --generate-requirements
              requirements_installer --file mycode.py --generate-requirements --requirements-path deps.txt
              requirements_installer --file mycode.py --scan-config
        """),
    )
    ap.add_argument("--file", required=True, help="Python file or Jupyter notebook to scan.")
    ap.add_argument("--use-venv", action="store_true",
                    help="Create and use a virtual environment for installation.")
    ap.add_argument("--venv-path", default=".venv",
                    help="Where to create the venv (default: .venv).")
    ap.add_argument("--print-requirements", action="store_true",
                    help="Print detected packages and exit without installing.")
    ap.add_argument("--ask-version", action="store_true",
                    help="Interactively choose a version for each package.")
    ap.add_argument("--generate-requirements", action="store_true",
                    help="Write requirements.txt with pinned versions after installation.")
    ap.add_argument("--requirements-path", default="requirements.txt",
                    help="Path for requirements.txt (default: requirements.txt).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be installed without actually installing.")
    ap.add_argument("--scan-config", action="store_true",
                    help="Also report packages declared in pyproject.toml / setup.cfg.")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="Suppress all output except errors.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Emit debug-level messages.")
    args = ap.parse_args()

    _setup_logger(quiet=args.quiet, verbose=args.verbose)

    entry_file = Path(args.file).resolve()
    if not entry_file.exists():
        ap.error(f"File not found: {entry_file}")

    project_root = entry_file.parent
    required = collect_requirements(entry_file, project_root)

    # Optionally surface packages declared in project config files
    if args.scan_config:
        declared = scan_project_config(project_root)
        if declared:
            logger.info("Declared in project config: %s", ", ".join(sorted(declared)))
        else:
            logger.info("No dependencies declared in pyproject.toml / setup.cfg.")

    if args.print_requirements:
        if required:
            print("\n".join(sorted(required)))
        else:
            print("(No external packages detected.)")
        return

    if args.dry_run:
        if required:
            logger.info("[dry-run] Would install: %s", ", ".join(sorted(required)))
        else:
            logger.info("[dry-run] No external packages detected.")
        return

    # Decide which Python / pip to use
    if args.use_venv:
        venv_path = Path(args.venv_path).resolve()
        py_exe, pip_cmd = ensure_venv(venv_path)
        env_desc = f"virtual environment at {venv_path}"
    else:
        py_exe, pip_cmd = current_pip_cmd()
        env_desc = f"current Python at {py_exe}"

    if is_conda_environment():
        conda_env = os.environ.get("CONDA_DEFAULT_ENV", "unknown")
        logger.info("Conda environment detected: %s", conda_env)

    logger.info("Environment : %s", env_desc)
    logger.info("Entry file  : %s", entry_file)

    if not required:
        logger.info("No external packages detected. Nothing to install.")
        return

    try:
        before = installed_distributions_lower(py_exe)
    except subprocess.CalledProcessError as exc:
        logger.warning("Could not query installed packages: %s", exc)
        before = set()

    needed = {p for p in required if p.lower() not in before}

    if not needed:
        logger.info("All required packages are already installed: %s", ", ".join(sorted(required)))
        if args.generate_requirements and required:
            versions = get_installed_versions(py_exe, required)
            req_path = Path(args.requirements_path)
            if generate_requirements_file(versions, req_path):
                logger.info("Generated %s", args.requirements_path)
            else:
                logger.error("Failed to generate %s", args.requirements_path)
                sys.exit(1)
        sys.exit(0)

    ok, output = install_packages(pip_cmd, needed, ask_version=args.ask_version)

    invalidate_dist_cache(py_exe)
    try:
        after = installed_distributions_lower(py_exe)
    except subprocess.CalledProcessError:
        after = set()

    newly, already = summarize_install(before, after, required)
    logger.info("")
    logger.info("=" * 50)
    logger.info("Installation Summary")
    logger.info("=" * 50)
    logger.info("Installed:        %s", ", ".join(sorted(newly)) or "(none)")
    if already:
        logger.info("Already present: %s", ", ".join(sorted(already)))

    missing = sorted(p for p in required if p.lower() not in after)
    if missing:
        logger.error("Failed / Missing: %s", ", ".join(missing))
        logger.debug("pip output:\n%s", output)
        sys.exit(1)

    logger.info("All requested packages are now present.")

    if args.generate_requirements and required:
        versions = get_installed_versions(py_exe, required)
        req_path = Path(args.requirements_path)
        if generate_requirements_file(versions, req_path):
            logger.info("Generated %s", args.requirements_path)
            logger.info("Install with: pip install -r %s", args.requirements_path)
        else:
            logger.error("Failed to generate %s", args.requirements_path)
            sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
