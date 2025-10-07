# Requirements Installer 🚀

**Tired of hunting down missing Python dependencies?** Requirements Installer automatically detects and installs all third-party packages your Python script needs—no `requirements.txt` needed!

Simply point it at your Python file, and it handles the rest. Perfect for running unfamiliar scripts, quick prototyping, or setting up development environments.

---

## ✨ Features

- **🔍 Smart Import Detection** - Automatically scans your Python files for all third-party imports
- **📦 One-Command Install** - Detects and installs dependencies in a single step
- **🎯 Interactive Version Selection** - Optionally choose specific versions for each package
- **🔒 Virtual Environment Support** - Create and install into isolated environments
- **🧠 Intelligent Filtering** - Excludes stdlib and local modules automatically
- **📝 Module-to-Package Mapping** - Handles tricky cases like `cv2` → `opencv-python`, `PIL` → `Pillow`
- **🌐 One-Hop Local Import Scanning** - Follows local imports to catch all dependencies
- **⚡ Fast & Lightweight** - Pure Python with no external dependencies

---

## 📥 Installation

```bash
pip install requirements-installer
```

Or install from source:

```bash
git clone https://github.com/FH-Prevail/requirements_installer.git
cd requirements-installer
pip install -e .
```

---

## 🚀 Quick Start

### Basic Usage

```bash
# Scan and install dependencies for a Python file
python requirements_installer.py --file mycode.py
```

### With Virtual Environment

```bash
# Create a venv and install dependencies there
python requirements_installer.py --file mycode.py --use-venv --venv-path .venv
```

### Interactive Version Selection

```bash
# Choose specific versions for each package
python requirements_installer.py --file mycode.py --ask-version
```

Example interaction:
```
==================================================
Version Selection
==================================================

Install latest version of 'numpy'? [Y/n]: n
Enter version for 'numpy' (e.g., 1.2.3): 1.24.0

Install latest version of 'pandas'? [Y/n]: y

Install latest version of 'requests'? [Y/n]: 
```

### Print Requirements Only

```bash
# Just show what would be installed, don't install
python requirements_installer.py --file mycode.py --print-requirements
```

---

## 📖 Usage Examples

### Example 1: Quick Script Setup
You clone a repo without a `requirements.txt`:

```bash
python requirements_installer.py --file app.py
```

Output:
```
Detected environment: current Python at /usr/bin/python3
Entry file: /home/user/project/app.py
Installing: numpy pandas requests

==================================================
Installation Summary
==================================================
Installed: numpy, pandas, requests
Already satisfied: (none)
All requested packages are now present.
```

### Example 2: Isolated Development Environment

```bash
python requirements_installer.py --file main.py --use-venv
```

Creates a `.venv` folder and installs all dependencies there, keeping your system Python clean.

### Example 3: Precise Version Control

```bash
python requirements_installer.py --file analysis.py --ask-version
```

Prompts you for each package, letting you pin versions for reproducibility.

---

## 🔧 Command-Line Options

```
usage: requirements_installer.py [-h] --file FILE [--use-venv] 
                                 [--venv-path VENV_PATH]
                                 [--print-requirements] [--ask-version]

options:
  -h, --help            Show this help message and exit
  --file FILE           Entry Python file to scan (e.g., mycode.py)
  --use-venv            Create and use a virtual environment
  --venv-path VENV_PATH 
                        Where to create the venv (default: .venv)
  --print-requirements  Only print inferred packages and exit
  --ask-version         Interactively ask for version preference for each package
```

---

## 🎯 How It Works

1. **Parse Imports**: Uses Python's AST to find all `import` and `from ... import` statements
2. **Filter Standard Library**: Removes built-in Python modules (e.g., `os`, `sys`, `json`)
3. **Filter Local Modules**: Excludes your project's own modules
4. **Map Module Names**: Converts import names to PyPI package names (e.g., `cv2` → `opencv-python`)
5. **Check Installation**: Queries what's already installed to avoid redundant work
6. **Install Packages**: Uses pip to install missing packages
7. **Verify**: Confirms all required packages are present

---

## 📊 Comparison with Other Tools

| Feature | requirements-installer | pipreqs | pigar | pythonrunscript |
|---------|----------------------|---------|-------|-----------------|
| Auto-detect imports | ✅ | ✅ | ✅ | ❌ |
| Auto-install packages | ✅ | ❌ | ❌ | ✅ |
| Interactive version selection | ✅ | ❌ | ❌ | ❌ |
| Virtual environment support | ✅ | ❌ | ❌ | ✅ |
| No source file modification | ✅ | ✅ | ✅ | ❌ |
| One-command operation | ✅ | ❌ | ❌ | ✅ |

**Why requirements-installer?**
- **pipreqs/pigar**: Generate `requirements.txt` but don't install (requires 2 steps)
- **pythonrunscript**: Installs but requires metadata comments in your code
- **requirements-installer**: Does both detection and installation, no modifications needed!

---

## 🧪 Module-to-Package Mappings

The tool includes smart mappings for common cases where the import name differs from the PyPI package name:

```python
cv2          → opencv-python
PIL          → Pillow
sklearn      → scikit-learn
yaml         → PyYAML
bs4          → beautifulsoup4
dotenv       → python-dotenv
# ... and many more!
```

---

## ⚠️ Limitations

- **One-hop scanning**: Only follows local imports one level deep (for speed)
- **Dynamic imports**: Limited detection of `importlib.import_module()` calls
- **Conditional imports**: Treats all imports equally (no context analysis)
- **Version conflicts**: Doesn't resolve complex dependency conflicts (delegates to pip)

These are deliberate trade-offs for simplicity and speed. For complex projects with intricate dependency trees, consider using Poetry or Pipenv.

---

## 🤝 Contributing

Contributions are welcome! Here are some ways you can help:

- 🐛 Report bugs and issues
- 💡 Suggest new features or improvements
- 📝 Improve documentation
- 🔧 Submit pull requests
- ⭐ Add more module-to-package mappings

---


## ⭐ Star History

If you find this tool useful, please consider giving it a star on GitHub! It helps others discover the project.

---

**Made with ❤️ by developers, for developers**