# -*- coding: utf-8 -*-
"""
MNEICAViewer (simple & robuste)
- Entrées: raw (mne.io.BaseRaw|Epochs), ica (mne.preprocessing.ICA), comp (int|None)
- Affiche: série temporelle du composant et son PSD (Welch)
- UI: sélection du composant, dB toggle, bouton "Agrandir…"
"""

from typing import Optional, Dict, Any
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QCheckBox, QDialog, QLabel, QDoubleSpinBox
)
from PyQt5.QtCore import Qt

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

try:
    import mne
    from mne.time_frequency import psd_array_welch
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class _BigDlg(QDialog):
    help = help = { 'gotchas': ['High refresh can drop FPS; consider decimation.'],
  'inputs': {'segment': '2D float [ch x samples] (or raw/derived)'},
  'outputs': {},
  'parameters': [ { 'default': 50.0,
                    'desc': 'Vertical scale',
                    'name': 'scale_uv',
                    'type': 'float',
                    'unit': 'µV'},
                  { 'default': 1.0,
                    'desc': 'Scroll speed',
                    'name': 'speed',
                    'type': 'float'},
                  { 'default': False,
                    'desc': 'Show full screen',
                    'name': 'fullscreen',
                    'type': 'bool'}],
  'summary': 'MNEICAViewer (simple & robuste)',
  'usage': 'Connect upstream data; adjust view parameters.'}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ICA – Agrandi")
        self.resize(1100, 700)
        self.fig = Figure(figsize=(11, 7), tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        lay = QVBoxLayout(self)
        lay.addWidget(self.canvas)


class MNEICAViewer(BasePlugin):
    name = "MNEICAViewer"
    language = "Python"
    category = "Visualization"
    supports_collapse = True

    # ---------------- lifecycle ----------------
    def setup(self):
        # pins
        self.inputs = {
            "raw": BehaviorSubject(None),
            "ica": BehaviorSubject(None),
            "comp": BehaviorSubject(None),    # index composant (optionnel)
        }
        self.outputs = {}

        # ui / state
        self._widget: Optional[QWidget] = None
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvas] = None
        self._big: Optional[_BigDlg] = None

        self._cb_comp: Optional[QComboBox] = None
        self._chk_db: Optional[QCheckBox] = None
        self._sp_win: Optional[QDoubleSpinBox] = None
        self._lbl: Optional[QLabel] = None

        self._use_db = False
        self._win_s = 10.0   # fenêtre temporelle affichée (s)
        self._last_raw = None
        self._last_ica = None

    # ---------------- UI ----------------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        panel = QWidget()
        pv = QVBoxLayout(panel)

        # Matplotlib canvas
        self._fig = Figure(figsize=(6, 4), tight_layout=True)
        self._canvas = FigureCanvas(self._fig)
        pv.addWidget(self._canvas)

        # Controls
        row = QHBoxLayout()

        row.addWidget(QLabel("Component:"))
        self._cb_comp = QComboBox()
        self._cb_comp.currentIndexChanged.connect(lambda _i: self._render_small())
        row.addWidget(self._cb_comp, 1)

        row.addWidget(QLabel("Window (s):"))
        self._sp_win = QDoubleSpinBox()
        self._sp_win.setRange(1.0, 120.0)
        self._sp_win.setSingleStep(1.0)
        self._sp_win.setValue(self._win_s)
        self._sp_win.valueChanged.connect(lambda v: self._set_win(float(v)))
        row.addWidget(self._sp_win)

        self._chk_db = QCheckBox("PSD in dB")
        self._chk_db.stateChanged.connect(lambda s: self._set_db(bool(s == Qt.Checked)))
        row.addWidget(self._chk_db)

        btn = QPushButton("Agrandir…")
        btn.clicked.connect(self._open_big)
        row.addWidget(btn)

        row.addStretch(1)
        pv.addLayout(row)

        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#bbb;font-style:italic;")
        pv.addWidget(self._lbl)

        wrap = QWidget()
        vw = QVBoxLayout(wrap); vw.setContentsMargins(0, 0, 0, 0)
        vw.addWidget(CollapsibleSection("ICA Viewer", panel, collapsed=False))
        self._widget = wrap
        return wrap

    def _ensure_canvas(self):
        if self._fig is None:
            self._fig = Figure(figsize=(6, 4), tight_layout=True)
        if self._widget is not None and self._canvas is None:
            self._canvas = FigureCanvas(self._fig)

    def _set_db(self, b: bool):
        self._use_db = bool(b)
        self._render_small()

    def _set_win(self, v: float):
        self._win_s = max(1.0, float(v))
        self._render_small()

    def _open_big(self):
        self._ensure_canvas()
        if self._big is None:
            self._big = _BigDlg()
        self._plot_into(self._big.fig, big=True)
        self._big.canvas.draw_idle()
        self._big.show(); self._big.raise_(); self._big.activateWindow()

    def _update_comp_list(self, ica):
        n = 0
        try:
            # n_components_ (après fit) ; sinon forme de get_components()
            if hasattr(ica, "n_components_") and ica.n_components_ is not None:
                n = int(ica.n_components_)
            else:
                W = ica.get_components()  # (n_channels, n_components)
                n = int(W.shape[1]) if W is not None else 0
        except Exception:
            n = 0

        if self._cb_comp is not None:
            self._cb_comp.blockSignals(True)
            self._cb_comp.clear()
            if n > 0:
                self._cb_comp.addItems([f"IC {i}" for i in range(n)])
                self._cb_comp.setCurrentIndex(0)
            self._cb_comp.blockSignals(False)

    def _current_comp_index(self) -> Optional[int]:
        if self._cb_comp is None or self._cb_comp.count() == 0:
            return None
        idx = self._cb_comp.currentIndex()
        return idx if idx >= 0 else None

    # ---------------- plotting ----------------
    def _plot_into(self, fig: Figure, big=False):
        fig.clear()
        ax_ts = fig.add_subplot(211)
        ax_psd = fig.add_subplot(212)

        raw = self._last_raw
        ica = self._last_ica

        if raw is None or ica is None:
            ax_ts.set_title("No raw/ICA")
            ax_psd.axis("off")
            try: fig.canvas.draw_idle()
            except Exception: pass
            return

        # Sources du composant
        try:
            src = ica.get_sources(raw)  # mne.io.RawArray (n_comp, n_times)
            X = src.get_data()          # ndarray
            sf = float(raw.info["sfreq"])
        except Exception as e:
            ax_ts.set_title(f"Cannot get sources: {e}")
            ax_psd.axis("off")
            try: fig.canvas.draw_idle()
            except Exception: pass
            return

        if not isinstance(X, np.ndarray) or X.ndim != 2 or X.shape[1] == 0:
            ax_ts.set_title("Empty sources")
            ax_psd.axis("off")
            try: fig.canvas.draw_idle()
            except Exception: pass
            return

        comp_idx = self._current_comp_index()
        if comp_idx is None or comp_idx >= X.shape[0]:
            comp_idx = 0

        # Fenêtre temporelle (fin du signal)
        n_win = max(1, int(round(self._win_s * sf)))
        x = X[comp_idx, :]
        if x.size <= n_win:
            seg = x
        else:
            seg = x[-n_win:]

        t = np.arange(seg.size, dtype=float) / sf
        ax_ts.plot(t, seg)
        ax_ts.set_xlabel("Time (s)"); ax_ts.set_ylabel("IC amp")
        ax_ts.set_title(f"IC {comp_idx} — time series ({seg.size/sf:.2f}s)")

        # PSD (Welch via MNE)
        try:
            psd, freqs = psd_array_welch(seg[None, :], sf, fmin=0.5, fmax=80.0, n_fft=min(2048, max(256, 2**int(np.ceil(np.log2(seg.size))))))
            y = psd[0]
            if self._use_db:
                y = 10.0 * np.log10(np.maximum(y, np.finfo(float).tiny))
            ax_psd.plot(freqs, y)
            ax_psd.set_xlabel("Frequency (Hz)")
            ax_psd.set_ylabel("PSD" + (" (dB)" if self._use_db else ""))
            ax_psd.set_title("Welch PSD")
        except Exception as e:
            ax_psd.text(0.5, 0.5, f"PSD error: {e}", ha="center", va="center")
            ax_psd.axis("off")

        try: fig.canvas.draw_idle()
        except Exception: pass

        if not big and self._lbl is not None:
            self._lbl.setText(f"{X.shape[0]} ICs · sf={sf:.2f} Hz")

    def _render_small(self):
        if self._last_ica is None or self._last_raw is None:
            # effacer le petit canvas s’il existe
            self._ensure_canvas()
            self._fig.clear()
            ax = self._fig.add_subplot(111)
            ax.set_title("No raw/ICA")
            try:
                if self._canvas is not None:
                    self._canvas.draw_idle()
            except Exception:
                pass
            return {}
        self._ensure_canvas()
        self._plot_into(self._fig, big=False)
        try:
            if self._canvas is not None:
                self._canvas.draw_idle()
        except Exception:
            pass
        return {}

    # ---------------- execute ----------------
    def execute(self, **kwargs) -> Dict[str, Any]:
        # s’assurer que l’UI/figure existent
        if self._widget is None:
            try:
                self.build_widget()
            except Exception:
                pass
        self._ensure_canvas()

        d = kwargs.get("in_data", {}) if "in_data" in kwargs else {}
        d.update(kwargs)

        raw = d.get("raw", self._last_raw)
        ica = d.get("ica", self._last_ica)
        comp = d.get("comp", None)

        self._last_raw = raw
        self._last_ica = ica

        # maj liste des compos
        if ica is not None:
            self._update_comp_list(ica)
            if isinstance(comp, int) and self._cb_comp is not None and self._cb_comp.count() > 0:
                idx = max(0, min(comp, self._cb_comp.count() - 1))
                self._cb_comp.blockSignals(True)
                self._cb_comp.setCurrentIndex(idx)
                self._cb_comp.blockSignals(False)

        self._render_small()
        return {}