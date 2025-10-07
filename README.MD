# Requirements Installer 🚀

**Tired of hunting down missing Python dependencies?** Requirements Installer automatically detects and installs all third-party packages your Python script needs—no `requirements.txt` needed!

Simply point it at your Python file, and it handles the rest. Perfect for running unfamiliar scripts, quick prototyping, or setting up development environments.

## 🎯 Two Ways to Use

### 1️⃣ Inside Your Code (Easiest!)
```python
from requirements_installer import auto_install
auto_install()
```

### 2️⃣ Command Line
```bash
requirements-installer --file mycode.py
```

---

## ✨ Features

- **⚡ Auto-Install Inside Code** - Just `from requirements_installer import auto_install; auto_install()` and you're done!
- **📓 Jupyter/Colab Support** - Scans and installs from `.ipynb` files automatically
- **🔍 Smart Import Detection** - Automatically scans your Python files for all third-party imports
- **📦 One-Command Install** - Detects and installs dependencies in a single step
- **🎯 Interactive Version Selection** - Optionally choose specific versions for each package
- **🔒 Virtual Environment Support** - Create and install into isolated environments
- **🧠 Intelligent Filtering** - Excludes stdlib and local modules automatically
- **📝 Module-to-Package Mapping** - Handles 100+ tricky cases like `cv2` → `opencv-python`, `pptx` → `python-pptx`
- **🌐 One-Hop Local Import Scanning** - Follows local imports to catch all dependencies
- **💪 Pure Python** - No external dependencies required

---

## 📥 Installation

```bash
pip install requirements-installer
```

Or install from source:

```bash
git clone https://github.com/FH-Prevail/requirements_installer.git
cd requirements_installer
pip install -e .
```

---

## 🚀 Quick Start

### ⭐ NEW: Auto-Install Inside Your Code (Recommended!)

**The easiest way - just add 2 lines to your script:**

```python
from requirements_installer import auto_install
auto_install()

# Now use any packages - they'll be auto-installed if missing!
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
```

**Perfect for Jupyter/Colab notebooks:**

```python
# Cell 1: Setup
!pip install -q requirements-installer
from requirements_installer import auto_install
auto_install()

# Cell 2+: Your code with any imports
import torch
import transformers
```

### Basic Command-Line Usage

**After `pip install requirements-installer`, use it as a command:**

```bash
# Scan and install dependencies for a Python file
requirements-installer --file mycode.py

# Works with Jupyter notebooks too!
requirements-installer --file notebook.ipynb
```

### With Virtual Environment

```bash
# Create a venv and install dependencies there
requirements-installer --file mycode.py --use-venv --venv-path .venv
```

### Interactive Version Selection

```bash
# Choose specific versions for each package
requirements-installer --file mycode.py --ask-version
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
requirements-installer --file mycode.py --print-requirements
```

---

## 📖 Usage Examples

### Example 1: Auto-Install in Script (NEW! 🎉)
Make your scripts self-installing:

```python
# my_analysis.py
from requirements_installer import auto_install
auto_install()

# Now use any packages!
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

df = pd.read_csv('data.csv')
plt.plot(df['x'], df['y'])
plt.show()
```

**Just run it:**
```bash
python my_analysis.py  # Auto-installs pandas, numpy, matplotlib!
```

### Example 2: Jupyter/Colab Notebook
```python
# Cell 1: Setup
!pip install -q requirements-installer
from requirements_installer import auto_install
auto_install()  # Scans entire notebook and installs everything!

# Cell 2+: Your code
import torch
from transformers import AutoModel
# ... rest of your notebook
```

### Example 3: Quick Script Setup
You clone a repo without a `requirements.txt`:

```bash
requirements-installer --file app.py
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

### Example 4: Isolated Development Environment

```bash
requirements-installer --file main.py --use-venv
```

Creates a `.venv` folder and installs all dependencies there, keeping your system Python clean.

### Example 5: Precise Version Control

```bash
requirements-installer --file analysis.py --ask-version
```

Prompts you for each package, letting you pin versions for reproducibility.

---

## 🔧 Command-Line Options

**After installation, use the `requirements-installer` command:**

```
usage: requirements-installer [-h] --file FILE [--use-venv] 
                              [--venv-path VENV_PATH]
                              [--print-requirements] [--ask-version]

options:
  -h, --help            Show this help message and exit
  --file FILE           Entry Python file or Jupyter notebook (.ipynb) to scan
  --use-venv            Create and use a virtual environment
  --venv-path VENV_PATH 
                        Where to create the venv (default: .venv)
  --print-requirements  Only print inferred packages and exit
  --ask-version         Interactively ask for version preference for each package
```

**Examples:**
```bash
# Basic usage
requirements-installer --file mycode.py

# With virtual environment
requirements-installer --file mycode.py --use-venv

# Interactive version selection
requirements-installer --file mycode.py --ask-version

# Scan Jupyter notebook
requirements-installer --file notebook.ipynb
```

**Note:** If you cloned the repository and want to run directly without installation:
```bash
python requirements_installer.py --file mycode.py
```

## 🐍 Python API

```python
from requirements_installer import auto_install

# Auto-detect and install (recommended)
auto_install()

# Specify file explicitly
auto_install(file_path='script.py')
auto_install(file_path='notebook.ipynb')

# Use virtual environment
auto_install(use_venv=True, venv_path='.venv')

# Quiet mode (only show errors)
auto_install(quiet=True)
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
| Call from inside code | ✅ | ❌ | ❌ | ⚠️ |
| Jupyter notebook support | ✅ | ⚠️ | ✅ | ❌ |
| Interactive version selection | ✅ | ❌ | ❌ | ❌ |
| Virtual environment support | ✅ | ❌ | ❌ | ✅ |
| No source file modification | ✅ | ✅ | ✅ | ❌ |
| One-command operation | ✅ | ❌ | ❌ | ✅ |

**Why requirements-installer?**
- **pipreqs/pigar**: Generate `requirements.txt` but don't install (requires 2 steps)
- **pythonrunscript**: Installs but requires metadata comments in your code
- **requirements-installer**: 
  - ✨ Call `auto_install()` directly in your code
  - 📓 Full Jupyter/Colab support
  - 🚀 Self-installing scripts
  - 💪 100+ module-to-package mappings

---

## 🧪 Module-to-Package Mappings

The tool includes smart mappings for 100+ common cases where the import name differs from the PyPI package name:

```python
cv2          → opencv-python
PIL          → Pillow
sklearn      → scikit-learn
yaml         → PyYAML
bs4          → beautifulsoup4
pptx         → python-pptx
docx         → python-docx
MySQLdb      → mysqlclient
psycopg2     → psycopg2-binary
telegram     → python-telegram-bot
discord      → discord.py
serial       → pyserial
git          → GitPython
# ... and 90+ more!
```

---

## ⚠️ Limitations

- **One-hop scanning**: Only follows local imports one level deep (for speed)
- **Dynamic imports**: Limited detection of `importlib.import_module()` calls
- **Conditional imports**: Treats all imports equally (no context analysis)
- **Version conflicts**: Doesn't resolve complex dependency conflicts (delegates to pip)

These are deliberate trade-offs for simplicity and speed. For complex projects with intricate dependency trees, consider using Poetry or Pipenv.

---

## 🆚 Command Line vs auto_install()

**Command Line** (traditional):
```bash
pip install requirements-installer
requirements-installer --file mycode.py
python mycode.py
```

**auto_install()** (modern - recommended):
```bash
python mycode.py  # That's it! Self-installing
```

---

## 🤝 Contributing

Contributions are welcome! Here are some ways you can help:

- 🐛 Report bugs and issues
- 💡 Suggest new features or improvements
- 📝 Improve documentation
- 🔧 Submit pull requests
- ⭐ Add more module-to-package mappings

### Development Setup

```bash
git clone https://github.com/FH-Prevail/requirements_installer.git
cd requirements_installer
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
```

### Running Tests

```bash
python -m pytest tests/
```

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

Inspired by:
- [pipreqs](https://github.com/bndr/pipreqs) - For the import scanning approach
- [pigar](https://github.com/damnever/pigar) - For AST parsing techniques
- [pythonrunscript](https://github.com/AnswerDotAI/pythonrunscript) - For auto-installation workflows

---

## 📬 Contact & Support

- **Issues**: [GitHub Issues](https://github.com/FH-Prevail/requirements_installer/issues)
- **Discussions**: [GitHub Discussions](https://github.com/FH-Prevail/requirements_installer/discussions)
- **Repository**: [github.com/FH-Prevail/requirements_installer](https://github.com/FH-Prevail/requirements_installer)
- **Author**: Sina

---

## 🎓 Perfect For:

- 📓 **Jupyter/Colab notebooks** - Make them truly self-contained
- 🚀 **Quick scripts** - No setup, just run
- 👥 **Sharing code** - Recipients don't need to know about dependencies
- 🎓 **Teaching** - Students can run examples immediately
- 🔬 **Research** - Reproducible notebooks that "just work"
- 🤖 **Automation** - Scripts that set themselves up

---

**Made with ❤️ by Sina**

**Star this repo if you find it useful!** ⭐ 

[Report Bug](https://github.com/FH-Prevail/requirements_installer/issues) · [Request Feature](https://github.com/FH-Prevail/requirements_installer/issues) · [Contribute](https://github.com/FH-Prevail/requirements_installer/pulls)