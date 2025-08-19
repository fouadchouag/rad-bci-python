# gui/log_console.py
# -*- coding: utf-8 -*-
import io, sys, logging, weakref, datetime
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
    QComboBox, QCheckBox, QFileDialog, QLabel, QSizePolicy, QDockWidget
)

# ---------- Qt log handler (thread-safe via signal) ----------
class _QtLogBridge(QObject):
    sig_text = pyqtSignal(str)

class _QtLogHandler(logging.Handler):
    """Logging handler that emits to a Qt signal."""
    def __init__(self, bridge: _QtLogBridge, level=logging.INFO):
        super().__init__(level)
        self.bridge = bridge
        fmt = "[%(asctime)s] %(levelname)s %(name)s — %(message)s"
        datefmt = "%H:%M:%S"
        self.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] <format error>"
        # Always append newline (QPlainTextEdit expects lines)
        self.bridge.sig_text.emit(msg + "\n")

# ---------- stdout/stderr proxy (optional) ----------
class _StdProxy(io.TextIOBase):
    """Redirects writes to a callback (and optionally to original)."""
    def __init__(self, write_cb, original=None, also_forward=False):
        super().__init__()
        self._write_cb = write_cb
        self._orig = original
        self._forward = bool(also_forward)

    def writable(self): return True

    def write(self, s):
        try:
            if s:
                self._write_cb(str(s))
        except Exception:
            pass
        if self._forward and self._orig is not None:
            try:
                return self._orig.write(s)
            except Exception:
                return len(s)
        return len(s)

    def flush(self):
        if self._forward and self._orig:
            try: self._orig.flush()
            except Exception: pass

# ---------- Log console widget ----------
class LogConsole(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        self._bridge = _QtLogBridge()
        self._bridge.sig_text.connect(self._append)

        self._handler = None
        self._attached_loggers = set()

        # stdout/stderr capture
        self._orig_stdout = None
        self._orig_stderr = None
        self._stdout_proxy = None
        self._stderr_proxy = None

        # UI
        root = QVBoxLayout(self); root.setContentsMargins(6,6,6,6); root.setSpacing(6)

        bar = QHBoxLayout(); bar.setSpacing(8)

        bar.addWidget(QLabel("Niveau:"))
        self.cmb_level = QComboBox()
        self.cmb_level.addItems(["DEBUG","INFO","WARNING","ERROR","CRITICAL"])
        self.cmb_level.setCurrentText("INFO")
        self.cmb_level.currentTextChanged.connect(self._on_level_changed)
        bar.addWidget(self.cmb_level)

        self.chk_autoscroll = QCheckBox("Auto-scroll"); self.chk_autoscroll.setChecked(True)
        bar.addWidget(self.chk_autoscroll)

        self.chk_capture = QCheckBox("Capturer print()")
        self.chk_capture.stateChanged.connect(self._toggle_capture)
        bar.addWidget(self.chk_capture)

        self.chk_pause = QCheckBox("Pause"); bar.addWidget(self.chk_pause)

        btn_clear = QPushButton("Vider")
        btn_clear.clicked.connect(self.clear)
        bar.addWidget(btn_clear)

        btn_save = QPushButton("Enregistrer…")
        btn_save.clicked.connect(self._save_to_file)
        bar.addWidget(btn_save)

        bar.addStretch(1)
        root.addLayout(bar)

        self.txt = QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setMaximumHeight(200)
        root.addWidget(self.txt)

        # default attach on root logger as convenience
        self.attach_to_logger(logging.getLogger(), level=logging.INFO)

    # ----- public API -----
    def attach_to_logger(self, logger_or_name=None, level=logging.INFO):
        """
        Attach the console to a logger (name or Logger). Returns the handler.
        """
        if isinstance(logger_or_name, logging.Logger):
            lg = logger_or_name
        elif isinstance(logger_or_name, str):
            lg = logging.getLogger(logger_or_name)
        elif logger_or_name is None:
            lg = logging.getLogger()  # root
        else:
            lg = logging.getLogger()

        if lg in self._attached_loggers:
            return self._handler

        if self._handler is None:
            self._handler = _QtLogHandler(self._bridge, level=level)
        self._handler.setLevel(level)
        lg.addHandler(self._handler)
        lg.setLevel(min(lg.level or logging.NOTSET, level) if lg.level else level)
        self._attached_loggers.add(lg)
        return self._handler

    def detach_all(self):
        if self._handler is None:
            return
        for lg in list(self._attached_loggers):
            try:
                lg.removeHandler(self._handler)
            except Exception:
                pass
        self._attached_loggers.clear()

    def clear(self):
        self.txt.clear()

    def log_text(self, text: str):
        """Append plain text line (bypassing logging)."""
        self._bridge.sig_text.emit(text if text.endswith("\n") else text + "\n")

    # ----- internals -----
    def _append(self, text: str):
        if self.chk_pause.isChecked():
            return
        self.txt.moveCursor(self.txt.textCursor().End)
        self.txt.insertPlainText(text)
        if self.chk_autoscroll.isChecked():
            self.txt.moveCursor(self.txt.textCursor().End)

    def _on_level_changed(self, level_name: str):
        lvl = getattr(logging, level_name.upper(), logging.INFO)
        if self._handler:
            self._handler.setLevel(lvl)
        for lg in self._attached_loggers:
            try:
                lg.setLevel(min(lg.level or logging.NOTSET, lvl) if lg.level else lvl)
            except Exception:
                pass
        self.log_text(f"[Console] Niveau défini: {level_name}")

    def _toggle_capture(self, state):
        want = state == Qt.Checked
        if want and self._stdout_proxy is None:
            # start capture (do not forward to terminal)
            self._orig_stdout = sys.stdout
            self._orig_stderr = sys.stderr
            self._stdout_proxy = _StdProxy(self.log_text, original=self._orig_stdout, also_forward=False)
            self._stderr_proxy = _StdProxy(self.log_text, original=self._orig_stderr, also_forward=False)
            sys.stdout = self._stdout_proxy
            sys.stderr = self._stderr_proxy
            self.log_text("[Console] Capture stdout/stderr: ON")
        elif not want and self._stdout_proxy is not None:
            # stop capture
            sys.stdout = self._orig_stdout or sys.__stdout__
            sys.stderr = self._orig_stderr or sys.__stderr__
            self._stdout_proxy = None
            self._stderr_proxy = None
            self._orig_stdout = None
            self._orig_stderr = None
            self.log_text("[Console] Capture stdout/stderr: OFF")

    def _save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le log", "", "Texte (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt.toPlainText())
            self.log_text(f"[Console] Sauvé: {path}")
        except Exception as e:
            self.log_text(f"[Console] Erreur sauvegarde: {e}")

# ---------- Dock wrapper ----------
class LogConsoleDock(QDockWidget):
    """
    Dock prêt à l'emploi: place un LogConsole en bas, avec toggleViewAction().
    """
    def __init__(self, parent=None, title="Console (logs)"):
        super().__init__(title, parent)
        self.setObjectName("RBciAD_LogDock")
        self.setAllowedAreas(Qt.BottomDockWidgetArea)
        self.console = LogConsole(self)
        self.setWidget(self.console)
        self.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

    def attach_logger(self, name="RBciAD", level=logging.INFO):
        return self.console.attach_to_logger(name, level)
