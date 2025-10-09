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
requirements_installer --file mycode.py
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
- **📄 Module-to-Package Mapping** - Handles 150+ tricky cases like `cv2` → `opencv-python`, `pptx` → `python-pptx`
- **🔧 Easy to Extend** - Add new mappings by editing a simple JSON file
- **🌍 One-Hop Local Import Scanning** - Follows local imports to catch all dependencies
- **💪 Pure Python** - No external dependencies required

---

## 🔥 Installation

```bash
pip install requirements_installer
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
# Cell 1: Your imports and code
import pandas as pd
import torch
from transformers import AutoModel
# ... your code ...

# Cell 2: Install everything (run this if imports fail)
!pip install -q requirements_installer
from requirements_installer import auto_install
auto_install()  # Scans all cells above and installs missing packages!

# Now re-run Cell 1 and it will work!
```

**Or install dependencies first:**

```python
# Cell 1: Setup (run first)
!pip install -q requirements_installer
from requirements_installer import auto_install
auto_install()  # If you have imports in other cells, it will find them

# Cell 2+: Your code with any imports
import torch
import transformers
```

### Basic Command-Line Usage

**After `pip install requirements_installer`, use it as a command:**

```bash
# Scan and install dependencies for a Python file
requirements_installer --file mycode.py

# Works with Jupyter notebooks too!
requirements_installer --file notebook.ipynb
```

### With Virtual Environment

```bash
# Create a venv and install dependencies there
requirements_installer --file mycode.py --use-venv --venv-path .venv
```

### Interactive Version Selection

```bash
# Choose specific versions for each package
requirements_installer --file mycode.py --ask-version
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
requirements_installer --file mycode.py --print-requirements
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

**Option A - Install before running (recommended):**
```python
# Cell 1: One-time setup
!pip install -q requirements_installer
from requirements_installer import auto_install
auto_install()  # Scans ALL cells in notebook (even unexecuted ones!)

# Cell 2+: Now run your code
import pandas as pd
import torch
from transformers import AutoModel
model = AutoModel.from_pretrained('bert-base-uncased')
```

**Option B - Fix import errors after they happen:**
```python
# Cell 1: Try to run your code
import pandas as pd
import torch
# ImportError: No module named 'torch'

# Cell 2: Install missing dependencies
!pip install -q requirements_installer
from requirements_installer import auto_install
auto_install()  # Scans ALL cells and installs what's needed!

# Cell 3: Re-run Cell 1 - now it works!
```

**How it works in Colab/Jupyter:**
- Automatically finds and reads your notebook file
- Scans **ALL cells** (even unexecuted ones!)
- Installs missing packages automatically
- No need to execute cells first - just call `auto_install()`

### Example 3: Quick Script Setup
You clone a repo without a `requirements.txt`:

```bash
requirements_installer --file app.py
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
requirements_installer --file main.py --use-venv
```

Creates a `.venv` folder and installs all dependencies there, keeping your system Python clean.

### Example 5: Precise Version Control

```bash
requirements_installer --file analysis.py --ask-version
```

Prompts you for each package, letting you pin versions for reproducibility.

---

## 🔧 Command-Line Options

**After installation, use the `requirements_installer` command:**

```
usage: requirements_installer [-h] --file FILE [--use-venv] 
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
requirements_installer --file mycode.py

# With virtual environment
requirements_installer --file mycode.py --use-venv

# Interactive version selection
requirements_installer --file mycode.py --ask-version

# Scan Jupyter notebook
requirements_installer --file notebook.ipynb
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
4. **Map Module Names**: Converts import names to PyPI package names using `module_mappings.json` (e.g., `cv2` → `opencv-python`)
5. **Check Installation**: Queries what's already installed to avoid redundant work
6. **Install Packages**: Uses pip to install missing packages
7. **Verify**: Confirms all required packages are present

---

## 📊 Comparison with Other Tools

| Feature | requirements_installer | pipreqs | pigar | pythonrunscript |
|---------|----------------------|---------|-------|-----------------|
| Auto-detect imports | ✅ | ✅ | ✅ | ❌ |
| Auto-install packages | ✅ | ❌ | ❌ | ✅ |
| Call from inside code | ✅ | ❌ | ❌ | ⚠️ |
| Jupyter notebook support | ✅ | ⚠️ | ✅ | ❌ |
| Interactive version selection | ✅ | ❌ | ❌ | ❌ |
| Virtual environment support | ✅ | ❌ | ❌ | ✅ |
| No source file modification | ✅ | ✅ | ✅ | ❌ |
| One-command operation | ✅ | ❌ | ❌ | ✅ |
| Easy to extend mappings | ✅ | ❌ | ❌ | ❌ |

**Why requirements_installer?**
- **pipreqs/pigar**: Generate `requirements.txt` but don't install (requires 2 steps)
- **pythonrunscript**: Installs but requires metadata comments in your code
- **requirements_installer**: 
  - ✨ Call `auto_install()` directly in your code
  - 📓 Full Jupyter/Colab support
  - 🚀 Self-installing scripts
  - 💪 150+ module-to-package mappings
  - 🔧 Easy to extend via JSON file

---

## 🧪 Module-to-Package Mappings

The tool includes smart mappings for 150+ common cases where the import name differs from the PyPI package name. These mappings are stored in `module_mappings.json` for easy maintenance and contributions.

**Common examples:**
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
# ... and 140+ more!
```

### Adding Your Own Mappings

It's easy to contribute new mappings! Just edit `module_mappings.json`:

```json
{
  "your_import_name": "pypi-package-name",
  "another_module": "another-package"
}
```

Then submit a pull request or use your custom version locally.

---

## ⚠️ Limitations

- **One-hop scanning**: Only follows local imports one level deep (for speed)
- **Dynamic imports**: Limited detection of `importlib.import_module()` calls
- **Conditional imports**: Treats all imports equally (no context analysis)
- **Version conflicts**: Doesn't resolve complex dependency conflicts (delegates to pip)
- **Jupyter notebooks**: Best results when notebook is saved. If not found, falls back to scanning executed cells only

These are deliberate trade-offs for simplicity and speed. For complex projects with intricate dependency trees, consider using Poetry or Pipenv.

---

## 🆘 Troubleshooting

### Imports not detected in Jupyter/Colab

**Problem:** Some imports are not being detected.

**Solution:** 

The tool automatically tries to find your notebook file to scan ALL cells. If it can't find the file:

1. **Save your notebook** - This helps the tool locate and read it
2. **For Colab**: Mount Google Drive if your notebook is stored there:
```python
from google.colab import drive
drive.mount('/content/drive')
```
3. **Fallback behavior**: If the notebook file isn't found, it scans executed cells only. In this case, run cells with imports before calling `auto_install()`.

### Command not found

```bash
# If 'requirements_installer' command not found, try:
python -m requirements_installer --file mycode.py

# Or check if installed:
pip show requirements_installer
```

---

## 🆚 Command Line vs auto_install()

**Command Line** (traditional):
```bash
pip install requirements_installer
requirements_installer --file mycode.py
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
- ⭐ Add more module-to-package mappings to `module_mappings.json`

### Development Setup

```bash
git clone https://github.com/FH-Prevail/requirements_installer.git
cd requirements_installer
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e .
```

### Adding New Mappings

To add new module-to-package mappings:

1. Edit `module_mappings.json`
2. Add your mapping: `"import_name": "pypi-package-name"`
3. Test it works
4. Submit a pull request!

**Note:** Only add mappings where the import name differs from the package name. No need for entries like `"torch": "torch"`.

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
- **Author**: Sina Mirshahi

---

## 🎓 Perfect For:

- 📓 **Jupyter/Colab notebooks** - Make them truly self-contained
- 🚀 **Quick scripts** - No setup, just run
- 👥 **Sharing code** - Recipients don't need to know about dependencies
- 🎓 **Teaching** - Students can run examples immediately
- 🔬 **Research** - Reproducible notebooks that "just work"
- 🤖 **Automation** - Scripts that set themselves up

---

**Made with ❤️ by Sina Mirshahi**

**Star this repo if you find it useful!** ⭐ 

[Report Bug](https://github.com/FH-Prevail/requirements_installer/issues) · [Request Feature](https://github.com/FH-Prevail/requirements_installer/issues) · [Contribute](https://github.com/FH-Prevail/requirements_installer/pulls)