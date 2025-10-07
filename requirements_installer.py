#!/usr/bin/env python3
"""
requirements_installer.py

Usage:
  python requirements_installer.py --file mycode.py
  python requirements_installer.py --file mycode.py --use-venv
  python requirements_installer.py --file mycode.py --use-venv --venv-path .venv
  python requirements_installer.py --file mycode.py --ask-version

What it does:
- Parses your Python file (and any local modules it directly imports) for imports.
- Filters out stdlib and local modules; infers third-party packages.
- Maps common module names to PyPI package names.
- Installs everything (optionally inside a freshly created venv).
- Prints a concise summary of what was installed and what was already satisfied.
"""

import argparse
import ast
import importlib.util
import os
import sys
import subprocess
import textwrap
from pathlib import Path
from typing import Set, Tuple, Dict, Iterable, List

# ------- Mapping: module name -> PyPI distribution name -------
MODULE_TO_DIST: Dict[str, str] = {
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "Crypto": "pycryptodome",
    "crypto": "pycryptodome",
    "mpl_toolkits": "matplotlib",
    "BeautifulSoup": "beautifulsoup4",
    "OpenGL": "PyOpenGL",
    "ruamel": "ruamel.yaml",
    "dotenv": "python-dotenv",
    "weasyprint": "WeasyPrint",
    "orjson": "orjson",
    "ujson": "ujson",
    "yamlpath": "yamlpath",
    # Often identical, listed to be explicit:
    "numpy": "numpy",
    "pandas": "pandas",
    "matplotlib": "matplotlib",
    "seaborn": "seaborn",
    "requests": "requests",
    "httpx": "httpx",
    "fastapi": "fastapi",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
    "flask": "Flask",
    "Django": "Django",
    "jinja2": "Jinja2",
    "lxml": "lxml",
    "tqdm": "tqdm",
    "dateutil": "python-dateutil",
    "psutil": "psutil",
    "Pillow": "Pillow",
    "tabulate": "tabulate",
    "rich": "rich",
    "typer": "typer",
    "click": "click",
    "loguru": "loguru",
    "pyyaml": "PyYAML",
    "PILLOW": "Pillow",
    "opencv": "opencv-python",
    "opencv_python": "opencv-python",
    "transformers": "transformers",
    "torch": "torch",
    "torchvision": "torchvision",
    "torchaudio": "torchaudio",
    "tensorflow": "tensorflow",
    "jax": "jax",
    "xgboost": "xgboost",
    "lightgbm": "lightgbm",
    "catboost": "catboost",
    "skops": "skops",
    "safetensors": "safetensors",
    "scipy": "scipy",
    "statsmodels": "statsmodels",
}

# Some stdlib fallbacks for older Python (<3.10 without sys.stdlib_module_names)
STDLIB_FALLBACK = {
    "abc","argparse","array","asyncio","base64","binascii","bisect","builtins","calendar","cmath",
    "collections","concurrent","configparser","contextlib","copy","csv","ctypes","datetime","decimal",
    "difflib","email","enum","errno","faulthandler","fnmatch","fractions","functools","gc","getopt",
    "getpass","gettext","glob","gzip","hashlib","heapq","hmac","html","http","imaplib","importlib",
    "inspect","io","ipaddress","itertools","json","keyword","linecache","locale","logging","lzma",
    "math","mimetypes","multiprocessing","numbers","operator","os","pathlib","pickle","pkgutil","platform",
    "plistlib","pprint","profile","pstats","queue","random","re","resource","sched","secrets","select",
    "selectors","shlex","shutil","signal","site","smtplib","socket","sqlite3","ssl","stat","statistics",
    "string","stringprep","struct","subprocess","sys","sysconfig","tarfile","tempfile","textwrap","threading",
    "time","timeit","tkinter","token","traceback","types","typing","unicodedata","unittest","urllib","uuid",
    "venv","warnings","weakref","xml","xmlrpc","zipfile","zoneinfo",
}

def stdlib_names() -> Set[str]:
    names = set()
    try:
        names.update(getattr(sys, "stdlib_module_names"))  # Py3.10+
    except Exception:
        pass
    if not names:
        names.update(STDLIB_FALLBACK)
    return names

def top_level_module(name: str) -> str:
    return name.split(".", 1)[0]

def is_relative_import(mod: str) -> bool:
    return mod.startswith(".")

def find_dynamic_imports(node: ast.AST) -> Set[str]:
    """Very simple detection for importlib.import_module('pkg[.sub]')"""
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            # importlib.import_module("x") or import_module("x")
            target = ""
            if isinstance(n.func, ast.Attribute):
                if getattr(n.func.value, "id", None) == "importlib" and n.func.attr == "import_module":
                    target = "importlib.import_module"
            elif isinstance(n.func, ast.Name) and n.func.id == "import_module":
                target = "import_module"
            if target and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                found.add(top_level_module(n.args[0].value))
    return found

def parse_imports_from_file(path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Returns (modules, local_modules)
    modules: top-level imported module names (absolute)
    local_modules: modules likely referring to local files/packages (within project)
    """
    modules: Set[str] = set()
    local: Set[str] = set()
    code = path.read_text(encoding="utf-8", errors="ignore")
    tree = ast.parse(code, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = top_level_module(alias.name)
                if not is_relative_import(mod):
                    modules.add(mod)
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            if node.level and node.level > 0:
                # relative import -> likely local
                continue
            mod = top_level_module(node.module)
            if not is_relative_import(mod):
                modules.add(mod)
    modules |= find_dynamic_imports(tree)
    return modules, local

def is_stdlib_module(mod: str, stdlib: Set[str]) -> bool:
    if mod in stdlib:
        return True
    if mod in sys.builtin_module_names:
        return True
    # Heuristic: if spec exists and lives under base_prefix + "lib"
    try:
        spec = importlib.util.find_spec(mod)
        if spec and spec.origin:
            origin = str(spec.origin).lower()
            base = str(Path(sys.base_prefix)).lower()
            # stdlib often under .../lib/pythonX.Y/...
            if "python" in origin and base in origin and "site-packages" not in origin:
                return True
    except Exception:
        pass
    return False

def is_local_module(mod: str, project_root: Path) -> bool:
    """
    Decide if 'mod' resolves to a module/package under project_root.
    """
    try:
        spec = importlib.util.find_spec(mod)
        if not spec or not spec.origin:
            # Could be uninstalled third-party (desired) OR local not in sys.path.
            # If a file/folder with that name exists next to project, treat as local.
            pkg_dir = project_root / mod
            py_file = project_root / f"{mod}.py"
            return pkg_dir.exists() or py_file.exists()
        origin = Path(spec.origin).resolve()
        try:
            return project_root.resolve() in origin.parents
        except Exception:
            return False
    except Exception:
        # If importable resolution fails, do a filesystem guess:
        pkg_dir = project_root / mod
        py_file = project_root / f"{mod}.py"
        return pkg_dir.exists() or py_file.exists()

def map_to_distribution(mod: str) -> str:
    # Prefer an explicit mapping, else use the module name itself
    return MODULE_TO_DIST.get(mod, mod)

def collect_requirements(entry_file: Path, project_root: Path) -> Set[str]:
    """
    Parse entry file and any immediately local-imported files (one hop) to collect modules.
    We don't recurse deep to keep it fast and simple.
    """
    stdlib = stdlib_names()
    all_modules: Set[str] = set()

    def add_from(path: Path):
        mods, _ = parse_imports_from_file(path)
        all_modules.update(mods)

    add_from(entry_file)

    # One-hop: if an import is local, parse that file/package's __init__.py
    local_files_to_parse: Set[Path] = set()
    for mod in list(all_modules):
        if is_local_module(mod, project_root):
            # Prefer package __init__.py if package; else module.py
            pkg_dir = project_root / mod
            if (pkg_dir / "__init__.py").exists():
                local_files_to_parse.add(pkg_dir / "__init__.py")
            elif (project_root / f"{mod}.py").exists():
                local_files_to_parse.add(project_root / f"{mod}.py")

    for lf in local_files_to_parse:
        mods, _ = parse_imports_from_file(lf)
        all_modules.update(mods)

    # Filter stdlib & local
    third_party = set()
    for mod in all_modules:
        if not mod or is_stdlib_module(mod, stdlib) or is_local_module(mod, project_root):
            continue
        third_party.add(mod)

    # Map to distributions (deduplicate case-insensitively)
    dists = {map_to_distribution(m) for m in third_party}
    # Normalize "-" vs "_" inconsistencies to avoid duplicates
    normed = set()
    for d in dists:
        normed.add(d.replace("_", "-"))
    return normed

def ensure_venv(venv_path: Path) -> Tuple[Path, List[str]]:
    """
    Create a venv at venv_path if missing. Return (python_exe, pip_cmd_as_list)
    """
    from venv import EnvBuilder
    if not venv_path.exists():
        print(f"Creating virtual environment at: {venv_path}")
        builder = EnvBuilder(with_pip=True, clear=False, upgrade=False, symlinks=True)
        builder.create(str(venv_path))
    # Paths
    if os.name == "nt":
        py = venv_path / "Scripts" / "python.exe"
    else:
        py = venv_path / "bin" / "python"
    pip_cmd = [str(py), "-m", "pip"]
    return py, pip_cmd

def current_pip_cmd() -> Tuple[Path, List[str]]:
    py = Path(sys.executable)
    return py, [str(py), "-m", "pip"]

def installed_distributions_lower(pip_python: Path) -> Set[str]:
    """
    Use importlib.metadata from the given python to list installed dists (lowercased).
    """
    code = (
        "import importlib.metadata as m, json; "
        "print(json.dumps([d.metadata['Name'].lower() for d in m.distributions() if 'Name' in d.metadata]))"
    )
    out = subprocess.check_output([str(pip_python), "-c", code], text=True)
    import json
    return set(json.loads(out))

def ask_for_version(package: str) -> str:
    """
    Interactively ask user if they want the latest version or a specific version.
    Returns the package spec (e.g., 'package' or 'package==1.2.3')
    """
    while True:
        response = input(f"\nInstall latest version of '{package}'? [Y/n]: ").strip().lower()
        if response in ('', 'y', 'yes'):
            return package
        elif response in ('n', 'no'):
            version = input(f"Enter version for '{package}' (e.g., 1.2.3): ").strip()
            if version:
                return f"{package}=={version}"
            else:
                print("No version specified, using latest.")
                return package
        else:
            print("Please answer 'y' or 'n'.")

def install_packages(pip_cmd: List[str], pkgs: Set[str], ask_version: bool = False) -> Tuple[bool, str]:
    """
    Install packages. If ask_version is True, prompt for version preferences.
    """
    if not pkgs:
        return True, "Nothing to install."
    
    packages_to_install = []
    if ask_version:
        print("\n" + "="*50)
        print("Version Selection")
        print("="*50)
        for pkg in sorted(pkgs):
            pkg_spec = ask_for_version(pkg)
            packages_to_install.append(pkg_spec)
    else:
        packages_to_install = sorted(pkgs)
    
    cmd = list(pip_cmd) + ["install", "--upgrade"] + packages_to_install
    print(f"\nInstalling: {' '.join(packages_to_install)}")
    proc = subprocess.run(cmd, text=True, capture_output=True)
    success = proc.returncode == 0
    return success, proc.stdout + "\n" + proc.stderr

def summarize_install(before: Set[str], after: Set[str], requested: Set[str]) -> Tuple[Set[str], Set[str]]:
    """
    Summarize what was installed vs what was already present.
    Note: requested contains base package names without version specs.
    """
    newly_installed = {p for p in requested if p.lower() in after and p.lower() not in before}
    already_present = {p for p in requested if p.lower() in before}
    return newly_installed, already_present

def main():
    ap = argparse.ArgumentParser(
        description="Scan a Python file for third-party imports and install them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python requirements_installer.py --file mycode.py
              python requirements_installer.py --file mycode.py --use-venv
              python requirements_installer.py --file mycode.py --use-venv --venv-path .venv
              python requirements_installer.py --file mycode.py --ask-version
        """),
    )
    ap.add_argument("--file", required=True, help="Entry Python file to scan (e.g., mycode.py).")
    ap.add_argument("--use-venv", action="store_true",
                    help="Create and use a virtual environment for installation.")
    ap.add_argument("--venv-path", default=".venv", help="Where to create the venv (default: .venv).")
    ap.add_argument("--print-requirements", action="store_true", help="Only print inferred packages and exit.")
    ap.add_argument("--ask-version", action="store_true", 
                    help="Interactively ask for version preference for each package.")
    args = ap.parse_args()

    entry_file = Path(args.file).resolve()
    if not entry_file.exists():
        ap.error(f"File not found: {entry_file}")

    project_root = entry_file.parent

    # Collect required distributions
    required = collect_requirements(entry_file, project_root)

    # Early exit if requested
    if args.print_requirements:
        if required:
            print("\n".join(sorted(required)))
        else:
            print("(No external packages detected.)")
        return

    # Decide environment
    if args.use_venv:
        venv_path = Path(args.venv_path).resolve()
        py_exe, pip_cmd = ensure_venv(venv_path)
        env_desc = f"virtual environment at {venv_path}"
    else:
        py_exe, pip_cmd = current_pip_cmd()
        env_desc = f"current Python at {py_exe}"

    print(f"Detected environment: {env_desc}")
    print(f"Entry file: {entry_file}")

    if not required:
        print("No external packages detected. Nothing to install.")
        return

    # Read installed packages before
    try:
        before = installed_distributions_lower(py_exe)
    except Exception:
        before = set()

    # Determine what actually needs to be installed (case-insensitive)
    needed = {p for p in required if p.lower() not in before}

    if not needed:
        print("All required packages are already installed.")
        print("Packages:", ", ".join(sorted(required)))
        return

    ok, output = install_packages(pip_cmd, needed, ask_version=args.ask_version)
    
    # Read installed packages after
    try:
        after = installed_distributions_lower(py_exe)
    except Exception:
        after = set()

    newly, already = summarize_install(before, after, required)
    print("\n" + "="*50)
    print("Installation Summary")
    print("="*50)
    if newly:
        print("Installed:", ", ".join(sorted(newly)))
    else:
        print("Installed: (none)")
    if already:
        print("Already satisfied:", ", ".join(sorted(already)))
    missing = sorted({p for p in required if p.lower() not in after})
    if missing:
        print("Failed / Missing:", ", ".join(missing))
        print("\n--- pip output (for debugging) ---")
        print(output)
        sys.exit(1)
    else:
        print("All requested packages are now present.")
        sys.exit(0)

if __name__ == "__main__":
    main()