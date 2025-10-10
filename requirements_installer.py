#!/usr/bin/env python3
"""
requirements_installer.py

Usage:
  Command line:
    python requirements_installer.py --file mycode.py
    python requirements_installer.py --file mycode.py --use-venv
    python requirements_installer.py --file mycode.py --ask-version
  
  Inside Python code:
    from requirements_installer import auto_install
    auto_install()
  
  In Jupyter/Colab:
    !pip install requirements_installer
    from requirements_installer import auto_install
    auto_install()

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
import inspect
import json
from pathlib import Path
from typing import Set, Tuple, Dict, Iterable, List, Optional

# ------- Load module mappings from JSON file -------
def load_module_mappings() -> Dict[str, str]:
    """
    Load module-to-package mappings from module_mappings.json.
    Falls back to minimal mappings if file not found (graceful degradation).
    """
    try:
        # Get the directory where this module is installed
        module_dir = Path(__file__).parent
        mappings_file = module_dir / "module_mappings.json"
        
        if mappings_file.exists():
            with open(mappings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Remove comment fields (keys starting with '_')
                return {k: v for k, v in data.items() if not k.startswith('_')}
        else:
            # Fallback: basic mappings if JSON file missing
            return {
                "cv2": "opencv-python",
                "PIL": "Pillow",
                "sklearn": "scikit-learn",
                "yaml": "PyYAML",
                "bs4": "beautifulsoup4",
            }
    except Exception as e:
        print(f"Warning: Could not load module mappings: {e}")
        # Minimal fallback
        return {
            "cv2": "opencv-python",
            "PIL": "Pillow",
            "sklearn": "scikit-learn",
        }

# Load mappings at module level
MODULE_TO_DIST: Dict[str, str] = load_module_mappings()

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
    """Get set of standard library module names."""
    names = set()
    try:
        names.update(getattr(sys, "stdlib_module_names"))  # Py3.10+
    except Exception:
        pass
    if not names:
        names.update(STDLIB_FALLBACK)
    return names

def top_level_module(name: str) -> str:
    """Extract top-level module from dotted name."""
    return name.split(".", 1)[0]

def is_relative_import(mod: str) -> bool:
    """Check if module name represents a relative import."""
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

def parse_imports_from_code(code: str, filename: str = "<string>") -> Set[str]:
    """Parse imports from a code string."""
    modules: Set[str] = set()
    try:
        tree = ast.parse(code, filename=filename)
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
                    continue
                mod = top_level_module(node.module)
                if not is_relative_import(mod):
                    modules.add(mod)
        modules |= find_dynamic_imports(tree)
    except SyntaxError:
        pass  # Skip cells with syntax errors
    return modules

def parse_imports_from_file(path: Path) -> Tuple[Set[str], Set[str]]:
    """
    Returns (modules, local_modules)
    modules: top-level imported module names (absolute)
    local_modules: modules likely referring to local files/packages (within project)
    """
    code = path.read_text(encoding="utf-8", errors="ignore")
    modules = parse_imports_from_code(code, str(path))
    local: Set[str] = set()
    return modules, local

def parse_imports_from_notebook(notebook_path: Path) -> Set[str]:
    """Parse imports from a Jupyter notebook (.ipynb file)."""
    modules: Set[str] = set()
    try:
        with open(notebook_path, 'r', encoding='utf-8') as f:
            notebook = json.load(f)
        
        # Extract code from cells
        cells = notebook.get('cells', [])
        for cell in cells:
            if cell.get('cell_type') == 'code':
                source = cell.get('source', [])
                # Source can be a list of strings or a single string
                if isinstance(source, list):
                    code = ''.join(source)
                else:
                    code = source
                
                # Skip magic commands and shell commands
                lines = code.split('\n')
                filtered_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped.startswith('!') and not stripped.startswith('%'):
                        filtered_lines.append(line)
                code = '\n'.join(filtered_lines)
                
                modules |= parse_imports_from_code(code, str(notebook_path))
    except Exception as e:
        print(f"Warning: Could not parse notebook {notebook_path}: {e}")
    
    return modules

def is_stdlib_module(mod: str, stdlib: Set[str]) -> bool:
    """Check if module is part of Python standard library."""
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
    Excludes virtual environments (venv, .venv, env, etc.)
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
        
        # Check if origin is under project_root
        try:
            if project_root.resolve() not in origin.parents:
                return False
            
            # It's under project_root, but check if it's in a venv
            # Common venv directory names
            venv_names = {'venv', '.venv', 'env', '.env', 'virtualenv', '.virtualenv'}
            
            # Check if any parent directory is a venv
            for parent in origin.parents:
                if parent == project_root:
                    break
                if parent.name.lower() in venv_names:
                    # It's in a venv, so NOT a local module
                    return False
                # Also check for common venv indicators
                if (parent / 'pyvenv.cfg').exists():
                    return False
            
            # It's under project_root and NOT in a venv, so it IS local
            return True
            
        except Exception:
            return False
    except Exception:
        # If importable resolution fails, do a filesystem guess:
        pkg_dir = project_root / mod
        py_file = project_root / f"{mod}.py"
        return pkg_dir.exists() or py_file.exists()

def map_to_distribution(mod: str) -> str:
    """Map module name to PyPI distribution name."""
    # Prefer an explicit mapping, else use the module name itself
    return MODULE_TO_DIST.get(mod, mod)

def collect_requirements(entry_file: Path, project_root: Path) -> Set[str]:
    """
    Parse entry file and any immediately local-imported files (one hop) to collect modules.
    We don't recurse deep to keep it fast and simple.
    """
    stdlib = stdlib_names()
    all_modules: Set[str] = set()

    # Check if it's a Jupyter notebook
    if entry_file.suffix == '.ipynb':
        all_modules.update(parse_imports_from_notebook(entry_file))
    else:
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
    """Get pip command for current Python interpreter."""
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
    return set(json.loads(out))

def get_installed_versions(pip_python: Path, packages: Set[str]) -> Dict[str, str]:
    """
    Get installed versions for a set of packages.
    Returns dict: {package_name: version}
    """
    # Create a properly formatted single-line Python command
    packages_list = list(packages)
    code = f"""
import importlib.metadata as m
import json
result = {{}}
for pkg in {packages_list}:
    try:
        result[pkg] = m.version(pkg)
    except:
        result[pkg] = 'unknown'
print(json.dumps(result))
""".strip()
    
    try:
        out = subprocess.check_output([str(pip_python), "-c", code], text=True)
        return json.loads(out)
    except Exception:
        return {pkg: "unknown" for pkg in packages}

def generate_requirements_file(packages_versions: Dict[str, str], output_path: Path) -> bool:
    """
    Generate a requirements.txt file with package versions.
    
    Args:
        packages_versions: Dict mapping package names to versions
        output_path: Path to write requirements.txt
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Generated by requirements_installer\n")
            f.write("# Install with: pip install -r requirements.txt\n\n")
            
            for package in sorted(packages_versions.keys()):
                version = packages_versions[package]
                if version and version != "unknown":
                    f.write(f"{package}=={version}\n")
                else:
                    f.write(f"{package}\n")
        
        return True
    except Exception as e:
        print(f"Error generating requirements.txt: {e}")
        return False

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

def get_caller_file() -> Optional[Path]:
    """
    Get the file path of the caller (the file that called auto_install()).
    Returns None if called from interactive environment.
    """
    # Walk up the stack to find the caller
    frame = inspect.currentframe()
    try:
        # Go up the stack: auto_install -> caller
        for _ in range(10):  # Safety limit
            if frame is None:
                break
            frame = frame.f_back
            if frame is None:
                break
            
            filename = frame.f_code.co_filename
            # Skip this module and built-in modules
            if filename == __file__ or filename.startswith('<'):
                continue
            
            # Found the caller file
            path = Path(filename)
            if path.exists():
                return path.resolve()
    finally:
        del frame  # Avoid reference cycles
    
    return None

def is_jupyter_environment() -> bool:
    """Check if running in a Jupyter/IPython environment."""
    try:
        get_ipython()  # type: ignore
        return True
    except NameError:
        return False

def find_jupyter_notebook() -> Optional[Path]:
    """
    Try to find the current Jupyter notebook file.
    Returns the path if found, None otherwise.
    """
    try:
        # Try to get IPython instance
        ipython = get_ipython()  # type: ignore
        
        # Method 1: Check if notebook name is in user namespace (Colab)
        if 'google.colab' in str(ipython):
            # In Colab, try common locations
            import glob
            # Check if Drive is mounted
            drive_notebooks = glob.glob('/content/drive/MyDrive/**/*.ipynb', recursive=True)
            content_notebooks = glob.glob('/content/*.ipynb')
            
            all_notebooks = drive_notebooks + content_notebooks
            if all_notebooks:
                # Return the most recently modified notebook
                return Path(max(all_notebooks, key=lambda x: Path(x).stat().st_mtime))
        
        # Method 2: For local Jupyter, try to get notebook path from connection file
        try:
            import ipykernel
            connection_file = ipykernel.get_connection_file()
            kernel_id = connection_file.split('-', 1)[1].split('.')[0]
            
            # Look for notebook in current directory and subdirectories
            import glob
            for nb_path in glob.glob('**/*.ipynb', recursive=True):
                nb_path = Path(nb_path)
                if nb_path.exists():
                    # Try to read and check if it's using this kernel
                    try:
                        with open(nb_path, 'r', encoding='utf-8') as f:
                            nb_data = json.load(f)
                            # If we can read it, it's likely the current one
                            # (This is a heuristic, not perfect)
                            return nb_path.resolve()
                    except:
                        continue
        except:
            pass
        
        # Method 3: Look for .ipynb files in current directory
        cwd = Path.cwd()
        notebooks = list(cwd.glob('*.ipynb'))
        if len(notebooks) == 1:
            # If there's only one notebook, it's likely the current one
            return notebooks[0].resolve()
        elif len(notebooks) > 1:
            # Multiple notebooks - return most recently modified
            return max(notebooks, key=lambda x: x.stat().st_mtime)
        
    except Exception as e:
        pass
    
    return None

def parse_imports_from_ipython() -> Set[str]:
    """
    Parse imports from current IPython/Jupyter session.
    First tries to read all cells from the notebook file.
    Falls back to reading executed cells from history if file not found.
    """
    modules: Set[str] = set()
    
    # Try to find and read the actual notebook file (includes ALL cells)
    notebook_path = find_jupyter_notebook()
    if notebook_path and notebook_path.exists():
        try:
            print(f"📓 Found notebook: {notebook_path.name}")
            return parse_imports_from_notebook(notebook_path)
        except Exception as e:
            print(f"Warning: Could not parse notebook file: {e}")
    
    # Fallback: Read from IPython history (only executed cells)
    print("ℹ️  Scanning executed cells only (notebook file not found)")
    try:
        ipython = get_ipython()  # type: ignore
        
        # Get all input cells from the session
        # In IPython, 'In' is a list where In[1], In[2], etc. are cell contents
        input_cells = ipython.user_ns.get('In', [])
        
        for cell_code in input_cells:
            if isinstance(cell_code, str) and cell_code.strip():
                # Skip magic commands and shell commands
                lines = cell_code.split('\n')
                filtered_lines = []
                for line in lines:
                    stripped = line.strip()
                    if not stripped.startswith('!') and not stripped.startswith('%'):
                        filtered_lines.append(line)
                code = '\n'.join(filtered_lines)
                
                # Parse imports from this cell
                modules |= parse_imports_from_code(code, '<ipython>')
    except Exception as e:
        print(f"Warning: Could not read IPython history: {e}")
    
    return modules

def auto_install(file_path: Optional[str] = None, use_venv: bool = False, 
                 venv_path: str = ".venv", quiet: bool = False,
                 generate_requirements: bool = False, requirements_path: str = "requirements.txt"):
    """
    Automatically install dependencies for the calling script or notebook.
    
    Args:
        file_path: Path to the file to scan. If None, auto-detects the caller.
        use_venv: Whether to create and use a virtual environment.
        venv_path: Path for the virtual environment (default: .venv).
        quiet: If True, suppress output except for errors.
        generate_requirements: If True, generate requirements.txt with pinned versions.
        requirements_path: Path for requirements.txt file (default: requirements.txt).
    
    Usage in Python script:
        from requirements_installer import auto_install
        auto_install()
    
    Usage in Jupyter/Colab:
        !pip install requirements_installer
        from requirements_installer import auto_install
        auto_install()
    """
    # Detect if we're in Jupyter/Colab
    in_jupyter = is_jupyter_environment()
    
    # Determine what to scan
    if file_path:
        # User provided explicit path
        entry_file = Path(file_path).resolve()
        if not entry_file.exists():
            print(f"❌ File not found: {entry_file}")
            return
        project_root = entry_file.parent
        
        # Collect requirements from file
        if not quiet:
            print(f"🔍 Scanning: {entry_file.name}")
        required = collect_requirements(entry_file, project_root)
        
    elif in_jupyter:
        # In Jupyter/Colab - try to scan all cells from notebook file
        if not quiet:
            print(f"🔍 Scanning Jupyter/Colab notebook...")
        
        # Parse imports (tries notebook file first, then executed cells)
        all_modules = parse_imports_from_ipython()
        
        # Filter to third-party only
        stdlib = stdlib_names()
        third_party = set()
        for mod in all_modules:
            if not mod or is_stdlib_module(mod, stdlib):
                continue
            third_party.add(mod)
        
        # Map to distributions
        dists = {map_to_distribution(m) for m in third_party}
        required = set()
        for d in dists:
            required.add(d.replace("_", "-"))
        
        project_root = Path.cwd()
        
    else:
        # Regular Python script - try to find the caller
        entry_file = get_caller_file()
        
        if entry_file is None or not entry_file.exists():
            print("❌ Could not detect file to scan. Please provide file_path argument.")
            print("   Usage: auto_install('your_script.py')")
            return
        
        project_root = entry_file.parent
        
        if not quiet:
            print(f"🔍 Scanning: {entry_file.name}")
        
        required = collect_requirements(entry_file, project_root)
    
    if not required:
        if not quiet:
            print("✅ No external packages needed!")
        return
    
    # Setup environment
    if use_venv:
        venv_path_obj = Path(venv_path).resolve()
        py_exe, pip_cmd = ensure_venv(venv_path_obj)
    else:
        py_exe, pip_cmd = current_pip_cmd()
    
    # Check what's already installed
    try:
        before = installed_distributions_lower(py_exe)
    except Exception:
        before = set()
    
    # Determine what needs installation
    needed = {p for p in required if p.lower() not in before}
    
    if not needed:
        if not quiet:
            print(f"✅ All packages already installed: {', '.join(sorted(required))}")
        
        # Even if nothing to install, generate requirements.txt if requested
        if generate_requirements and required:
            if not quiet:
                print(f"\n📝 Generating {requirements_path}...")
            
            packages_versions = get_installed_versions(py_exe, required)
            req_path = Path(requirements_path)
            
            if generate_requirements_file(packages_versions, req_path):
                if not quiet:
                    print(f"✅ Generated {requirements_path} with {len(packages_versions)} packages")
            else:
                print(f"❌ Failed to generate {requirements_path}")
        
        return
    
    # Install missing packages
    if not quiet:
        print(f"📦 Installing {len(needed)} package(s)...")
    
    ok, output = install_packages(pip_cmd, needed, ask_version=False)
    
    # Check results
    try:
        after = installed_distributions_lower(py_exe)
    except Exception:
        after = set()
    
    newly, already = summarize_install(before, after, required)
    
    if not quiet:
        if newly:
            print(f"✅ Installed: {', '.join(sorted(newly))}")
        if already:
            print(f"ℹ️  Already present: {', '.join(sorted(already))}")
    
    missing = sorted({p for p in required if p.lower() not in after})
    if missing:
        print(f"❌ Failed to install: {', '.join(missing)}")
        if not quiet:
            print("\n--- Debug output ---")
            print(output)
    
    # Generate requirements.txt if requested
    if generate_requirements and required:  # Generate if ANY packages are required
        if not quiet:
            print(f"\n📝 Generating {requirements_path}...")
        
        # Get versions for ALL required packages (both new and already installed)
        packages_versions = get_installed_versions(py_exe, required)
        
        # Debug: Show what we're including
        if not quiet:
            found_count = sum(1 for v in packages_versions.values() if v != 'unknown')
            print(f"   Including {found_count} packages with versions")
        
        req_path = Path(requirements_path)
        if generate_requirements_file(packages_versions, req_path):
            if not quiet:
                print(f"✅ Generated {requirements_path} with {len(packages_versions)} packages")
        else:
            print(f"❌ Failed to generate {requirements_path}")

def main():
    """Command-line interface for requirements_installer."""
    ap = argparse.ArgumentParser(
        description="Scan a Python file for third-party imports and install them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              requirements_installer --file mycode.py
              requirements_installer --file mycode.py --use-venv
              requirements_installer --file mycode.py --ask-version
              requirements_installer --file notebook.ipynb
              requirements_installer --file mycode.py --generate-requirements
              requirements_installer --file mycode.py --generate-requirements --requirements-path deps.txt
        """),
    )
    ap.add_argument("--file", required=True, help="Entry Python file or Jupyter notebook to scan.")
    ap.add_argument("--use-venv", action="store_true",
                    help="Create and use a virtual environment for installation.")
    ap.add_argument("--venv-path", default=".venv", help="Where to create the venv (default: .venv).")
    ap.add_argument("--print-requirements", action="store_true", help="Only print inferred packages and exit.")
    ap.add_argument("--ask-version", action="store_true", 
                    help="Interactively ask for version preference for each package.")
    ap.add_argument("--generate-requirements", action="store_true",
                    help="Generate requirements.txt with pinned versions after installation.")
    ap.add_argument("--requirements-path", default="requirements.txt",
                    help="Path for requirements.txt file (default: requirements.txt).")
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
        
        # Generate requirements.txt even if nothing to install
        if args.generate_requirements and required:
            print(f"\n📝 Generating {args.requirements_path}...")
            
            packages_versions = get_installed_versions(py_exe, required)
            found_count = sum(1 for v in packages_versions.values() if v != 'unknown')
            print(f"   Including {found_count} packages with versions")
            
            req_path = Path(args.requirements_path)
            
            if generate_requirements_file(packages_versions, req_path):
                print(f"✅ Generated {args.requirements_path} with {len(packages_versions)} packages")
                print(f"\nYou can now install these dependencies with:")
                print(f"  pip install -r {args.requirements_path}")
                sys.exit(0)
            else:
                print(f"❌ Failed to generate {args.requirements_path}")
                sys.exit(1)
        
        sys.exit(0)

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
        
        # Generate requirements.txt if requested
        if args.generate_requirements and required:
            print(f"\n📝 Generating {args.requirements_path}...")
            
            # Get versions for ALL required packages (both newly installed and already present)
            packages_versions = get_installed_versions(py_exe, required)
            
            # Show what we're including
            found_count = sum(1 for v in packages_versions.values() if v != 'unknown')
            print(f"   Including {found_count} packages with versions")
            
            req_path = Path(args.requirements_path)
            
            if generate_requirements_file(packages_versions, req_path):
                print(f"✅ Generated {args.requirements_path} with {len(packages_versions)} packages")
                print(f"\nYou can now install these dependencies with:")
                print(f"  pip install -r {args.requirements_path}")
            else:
                print(f"❌ Failed to generate {args.requirements_path}")
                sys.exit(1)
        
        sys.exit(0)

if __name__ == "__main__":
    main()