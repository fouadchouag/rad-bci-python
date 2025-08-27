# core/metrics_hotkeys.py
# -*- coding: utf-8 -*-
from PyQt5.QtCore import QObject, QEvent, Qt, QCoreApplication
from PyQt5.QtWidgets import QApplication
import threading, time
from .metrics_logger import init_metrics_logger, metrics, deinit_metrics_logger, is_active as _is_active

_LOCK = threading.Lock()
_INSTALLED = False

class _GlobalHotkeyFilter(QObject):
    def eventFilter(self, obj, event):
        try:
            if event.type() == QEvent.KeyPress:
                key = event.key()
                if key == Qt.Key_F9:
                    _toggle_metrics()
                    return True
                elif key == Qt.Key_F10:
                    _stop_metrics(force=True)
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

def _start_metrics(app_name="RBciAD", out_dir="runs"):
    with _LOCK:
        if _is_active():
            return
        run_csv = init_metrics_logger(app_name=app_name, out_dir=out_dir)
        # borne de session pour l’analyse + TTFP
        try:
            metrics().event("RUN_BEGIN", path=run_csv)
            metrics().ttfp()
        except Exception:
            pass

def _stop_metrics(force=False):
    with _LOCK:
        if not _is_active():
            return
        try:
            metrics().event("RUN_END", force=int(bool(force)))
        except Exception:
            pass
        deinit_metrics_logger()

def _toggle_metrics():
    if _is_active():
        _stop_metrics()
    else:
        _start_metrics()

def install_global_metrics_hotkeys(app_name="RBciAD", out_dir="runs"):
    """
    Installe UNE FOIS des hotkeys globaux sur l'application:
      F9  -> start/stop (toggle)
      F10 -> stop (force)
    Appelle cette fonction depuis n'importe quel widget (p. ex. LiveDisplay.build_widget()).
    """
    global _INSTALLED
    if _INSTALLED:
        return
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication non initialisé")
    filt = _GlobalHotkeyFilter(app)
    app.installEventFilter(filt)
    _INSTALLED = True
