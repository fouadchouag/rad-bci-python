# rbciad_app/__main__.py
from __future__ import annotations
import sys, re
from pathlib import Path
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

def _import_main_window():
    """Import your MainWindow class without toucher à ton arborescence."""
    try:
        from gui.main_window import MainWindow
        return MainWindow
    except Exception:
        pass
    try:
        from gui.app import MainWindow
        return MainWindow
    except Exception:
        pass
    raise ImportError(
        "Could not import MainWindow. Adjust rbciad_app/__main__.py to your module path."
    )

def _get_version_from_core_module() -> str | None:
    """Try importing version from core.version (most reliable)."""
    try:
        from core.version import __version__ as v  # e.g. "__version__ = '1.8.0'"
        return str(v)
    except Exception:
        pass
    try:
        from core.version import VERSION as V  # e.g. "VERSION = (1, 8, 0)" or "1.8.0"
        if isinstance(V, (tuple, list)):
            return ".".join(str(x) for x in V)
        return str(V)
    except Exception:
        pass
    return None

def _get_version_by_parsing_file() -> str | None:
    """Fallback: read core/version.py and extract version with regex."""
    # try a few common locations relative to cwd and to this file
    candidates = [
        Path.cwd() / "core" / "version.py",
        Path(__file__).resolve().parents[1] / "core" / "version.py",
    ]
    for p in candidates:
        if p.exists():
            txt = p.read_text(encoding="utf-8", errors="ignore")
            # __version__ = "1.8.0"
            m = re.search(r"""__version__\s*=\s*['"]([^'"]+)['"]""", txt)
            if m:
                return m.group(1).strip()
            # VERSION = "1.8.0"
            m = re.search(r"""VERSION\s*=\s*['"]([^'"]+)['"]""", txt)
            if m:
                return m.group(1).strip()
            # VERSION = (1, 8, 0)
            m = re.search(r"""VERSION\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)""", txt)
            if m:
                return ".".join(m.groups())
    return None

def _get_version() -> str:
    """Public: returns version string like '1.8.0' or ''."""
    v = _get_version_from_core_module()
    if v:
        return v
    v = _get_version_by_parsing_file()
    return v or ""

def _strip_existing_version(title: str) -> str:
    """
    Remove an existing '— vX.Y.Z' suffix to avoid stacking versions when relaunching.
    """
    if not title:
        return "RBciAD"
    # patterns like "RBciAD — v1.8.0" or "RBciAD v1.8.0"
    title = re.sub(r"\s+—\s+v\d+\.\d+(\.\d+)?$", "", title).strip()
    title = re.sub(r"\s+v\d+\.\d+(\.\d+)?$", "", title).strip()
    return title or "RBciAD"

def main():
    MainWindow = _import_main_window()
    app = QApplication(sys.argv)
    w = MainWindow()

    # --- OUVERTURE PLEIN ÉCRAN ---
    try:
        w.showMaximized()
    except Exception:
        w.show()
        w.setWindowState(w.windowState() | Qt.WindowMaximized)

    # --- VERSION DANS LE TITRE (depuis core/version.py) ---
    try:
        ver = _get_version()  # ex: "1.8.0"
        if ver:
            base = _strip_existing_version(w.windowTitle() or "RBciAD")
            w.setWindowTitle(f"{base} — v{ver}")
    except Exception:
        pass

    # --- INTÉGRATION HELP (F1 / Shift+F1 / Ctrl+F1) ---
    try:
        from rbciad_app.integrate_help import setup_help
        scene = getattr(w, "scene", None) if hasattr(w, "scene") else None
        setup_help(main_window=w, scene=scene)
    except Exception as e:
        print("[rbciad_app] Help integration skipped:", e)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
