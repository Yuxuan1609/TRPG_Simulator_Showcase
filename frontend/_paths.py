"""Centralized path resolution for dev, PyInstaller, and Nuitka modes.

PyInstaller: sys.frozen=True + sys._MEIPASS -> _internal/
Nuitka:      no sys.frozen, no _MEIPASS; detect via .dist suffix on exe path
Dev:         normal __file__ resolution
"""
import sys
from pathlib import Path

_exe_dir = Path(sys.executable).parent
IS_FROZEN = getattr(sys, 'frozen', False) or _exe_dir.name.endswith('.dist')

if IS_FROZEN:
    _bundle = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else _exe_dir
    PROJECT_ROOT = _bundle
    FRONTEND_DIR = _bundle / "frontend"
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    FRONTEND_DIR = PROJECT_ROOT / "frontend"
