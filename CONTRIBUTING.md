# Aircontrol Contribution Guide

Welcome to the **Aircontrol** development community!  
Aircontrol is an open-source project providing high-speed, ultra-low latency (<30ms) 60 FPS screen mirroring and interactive remote control for iPhone on Windows 10/11.

We warmly welcome all contributions: from bug fixes, performance optimizations, and new features to documentation improvements.

---

## 🛠️ 1. Development Setup

### Prerequisites:
- **Operating System:** Windows 10 or Windows 11 (64-bit).
- **Python:** Python 3.11 or newer (Python 3.11 or 3.12 recommended).
- **Package Manager:** [`uv`](https://github.com/astral-sh/uv) recommended for fast virtual environment management, or standard `python -m venv`.
- **Apple Drivers:** iTunes or **Apple Devices** app installed from Microsoft Store (provides Apple Mobile Device Support drivers).

### Installation Steps:

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/zuan412/Aircontrol.git
   cd Aircontrol
   ```

2. **Create and activate virtual environment:**
   *Using `uv`:*
   ```powershell
   uv venv
   .venv\Scripts\activate
   uv pip install -e .
   uv pip install pytest pytest-asyncio pyinstaller
   ```

   *Using standard `venv`:*
   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install -e .
   pip install pytest pytest-asyncio pyinstaller
   ```

3. **Verify installation:**
   ```powershell
   pytest tests -q
   ```
   All tests must report `passed`.

---

## 🚀 2. Running in Development Mode

- **Option 1: Quick start via batch script:**
  ```powershell
  .\run.bat
  ```

- **Option 2: Launch via launcher script:**
  ```powershell
  python run_aircontrol.py
  ```

- **Option 3: Run as Python module with flags:**
  ```powershell
  python -m aircontrol --wifi
  python -m aircontrol --usb
  python -m aircontrol --target-ip 192.168.1.150
  ```

---

## 🧪 3. Testing Guidelines

Aircontrol enforces rigorous testing principles:
1. **Every new feature or bugfix must be accompanied by unit tests.**
2. **Never commit code that breaks existing test suites.**
3. Run the full test suite before committing:
   ```powershell
   pytest tests -v
   ```

---

## 📦 4. Standalone Binary Build

The project supports building standalone `.exe` binaries via PyInstaller:
```powershell
.\build_release.bat
```
Build outputs are located at:
- `dist\Aircontrol\Aircontrol.exe` (Portable distribution directory)
- `dist\Aircontrol-v0.1.0-win64.zip` (Release archive)

---

## 📋 5. Pull Request Workflow

1. **Create a feature branch from `master`:**
   ```powershell
   git checkout -b feature/your-feature-name
   # or: git checkout -b fix/your-bug-fix
   ```

2. **Conventional Commits Specification:**
   - `feat(...)`: New feature (e.g., `feat(audio): add WASAPI exclusive mode`)
   - `fix(...)`: Bug fix (e.g., `fix(stream): resolve packet drop in reorder buffer`)
   - `docs(...)`: Documentation updates
   - `test(...)`: Adding or modifying tests
   - `refactor(...)`: Code refactoring without behavioral changes

3. **Push branch and open a Pull Request:**
   - Provide a clear description of the problem solved.
   - Attach screenshots or benchmark numbers if related to UI or performance.

Thank you for contributing to Aircontrol!
