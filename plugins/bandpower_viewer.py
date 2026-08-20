# -*- coding: utf-8 -*-
"""
BandpowerViewer
- Visualise les puissances par bande (agrégées) sous forme de bar chart.
- Pins MINIMALES, UI pliable, bouton "Agrandir".
- Modes:
   • "Moyenne (tous canaux)"  → barres par bande (moyenne des canaux)
   • "Canal unique"           → dropdown pour choisir le canal

Entrées:
    bandpowers : np.ndarray (n_ch, n_bands) [requis]
    band_labels: list[str]                  [requis]
    ch_names   : list[str]                  [optionnel]

Aucune sortie (viewer).
"""

import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
    QLayout, QSizePolicy, QDialog
)
from PyQt5.QtCore import Qt
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

try:
    from core.collapsible import CollapsibleSection
except Exception:
    class CollapsibleSection(QWidget):
        

        def __init__(self, title, content, collapsed=True, parent=None):
            super().__init__(parent)
            lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.addWidget(content)

class BandpowerViewer(BasePlugin):
    help = {
        'summary': 'Bar chart of EEG band powers (e.g. theta, alpha, beta), either averaged across channels or per-channel.',
        'usage': 'Connect bandpowers and band_labels from a band-power computation node. Switch between average and single-channel mode in the UI.',
        'inputs': {
            'bandpowers': '2D float array [channels x bands] — power values per channel per frequency band',
            'band_labels': 'list[str] — labels for each frequency band (e.g. ["delta", "theta", "alpha", "beta"])',
            'ch_names': 'list[str] — channel names for the channel dropdown selector',
        },
        'outputs': {},
        'parameters': [
            {'name': 'mode', 'type': 'str', 'default': 'avg', 'desc': 'Display mode: "avg" (mean across all channels) or "single" (one channel via dropdown)'},
            {'name': 'sel_ch', 'type': 'int', 'default': 0, 'desc': 'Selected channel index when in "single" mode'},
        ],
        'gotchas': [
            'bandpowers must be 2D [n_channels x n_bands]; 1D or mismatched shapes show "No data".',
            'band_labels length must match bandpowers.shape[1] for correct bar alignment.',
            'ch_names is optional — if absent, the channel dropdown is empty and single mode uses index 0.',
            'No outputs — this is a viewer-only node; use it at the end of a pipeline branch.',
            'Popup ("Agrandir") syncs with the main view in real time.',
        ],
    }
    

    name = "MNEBandpowerViewer"
    language = "Python"
    category = "Output Nodes"
    supports_collapse = True

    def setup(self):
        # Inputs
        self.inputs["bandpowers"] = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        # Pas de sorties (viewer)
        self.outputs = {}

        # UI
        self._widget = None
        self._figure = None
        self._canvas = None
        self._ax = None

        self._mode = "avg"   # 'avg' | 'single'
        self._sel_ch = 0

        # popup
        self._popup = None
        self._pop_fig = None
        self._pop_ax = None
        self._pop_canvas = None

        # cache
        self._last = {"bandpowers": None, "band_labels": None, "ch_names": None}

    # -------- UI --------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        w = QWidget()
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # Figure
        self._figure = Figure(figsize=(5, 2))
        self._ax = self._figure.add_subplot(111)
        self._canvas = FigureCanvas(self._figure)
        root.addWidget(self._canvas, 1)

        # panneau
        panel = QWidget()
        pv = QHBoxLayout(panel)
        pv.setContentsMargins(8,8,8,8)
        pv.setSpacing(6)

        pv.addWidget(QLabel("Mode:"))
        cb_mode = QComboBox()
        cb_mode.addItems(["Moyenne (tous canaux)", "Canal unique"])
        cb_mode.currentIndexChanged.connect(lambda i: self._on_mode_changed("avg" if i == 0 else "single"))
        pv.addWidget(cb_mode)

        pv.addWidget(QLabel("Canal:"))
        self._cb_ch = QComboBox()
        self._cb_ch.currentIndexChanged.connect(self._on_channel_changed)
        pv.addWidget(self._cb_ch)

        pv.addStretch(1)
        btn_big = QPushButton("Agrandir")
        btn_big.clicked.connect(self._show_large_plot)
        pv.addWidget(btn_big)

        root.addWidget(CollapsibleSection("Contrôles", panel, collapsed=True))

        self._widget = w
        self._refresh_channels()
        self._update_plot()
        return w

    # -------- config i/o --------
    def export_config(self) -> dict:
        return {"mode": self._mode, "sel_ch": int(self._sel_ch)}

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        mode = cfg.get("mode", self._mode)
        self._mode = mode if mode in ("avg","single") else "avg"
        self._sel_ch = int(cfg.get("sel_ch", self._sel_ch))
        self._update_plot()

    def config_hints(self) -> dict:
        return {"fields": {"mode": {"enum": ["avg","single"]}, "sel_ch": {"type": "int"}}}

    # -------- helpers --------
    def _refresh_channels(self):
        if not hasattr(self, "_cb_ch") or self._cb_ch is None:
            return
        ch = self._last.get("ch_names", None)
        self._cb_ch.blockSignals(True)
        self._cb_ch.clear()
        if isinstance(ch, list) and ch:
            self._cb_ch.addItems([str(x) for x in ch])
            idx = max(0, min(self._sel_ch, len(ch) - 1))
            self._cb_ch.setCurrentIndex(idx)
        self._cb_ch.blockSignals(False)

    def _on_mode_changed(self, mode):
        self._mode = mode
        self._update_plot()

    def _on_channel_changed(self, idx):
        self._sel_ch = int(max(0, idx))
        if self._mode == "single":
            self._update_plot()

    # -------- plotting --------
    def _plot_bars(self, ax, X, labels, title):
        ax.clear()
        if X is None or labels is None or len(labels) == 0:
            ax.set_title("No data")
            self._canvas.draw_idle() if ax is self._ax else self._pop_canvas.draw_idle()
            return
        ax.bar(np.arange(len(labels)), X, align="center")
        ax.set_xticks(np.arange(len(labels)))
        ax.set_xticklabels(labels)
        ax.set_ylabel("Power (rel.)" if (isinstance(self._last.get("info"), dict) and self._last["info"].get("relative")) else "Power")
        ax.set_title(title)
        if ax is self._ax:
            self._canvas.draw_idle()
        else:
            self._pop_canvas.draw_idle()

    def _update_plot(self):
        bp = self._last.get("bandpowers", None)
        labels = self._last.get("band_labels", None)
        ch = self._last.get("ch_names", None)

        if bp is None or labels is None:
            if self._ax:
                self._ax.clear(); self._ax.set_title("No data"); self._canvas.draw_idle()
            return

        if self._mode == "avg":
            vals = np.nanmean(bp, axis=0) if bp.size else None
            self._plot_bars(self._ax, vals, labels, "Band power — Moyenne tous canaux")
        else:
            i = max(0, min(self._sel_ch, bp.shape[0]-1))
            vals = bp[i, :]
            title = f"Band power — Canal: {ch[i] if isinstance(ch, list) and i < len(ch) else i}"
            self._plot_bars(self._ax, vals, labels, title)

        # popup synchro
        if self._popup and self._pop_ax:
            if self._mode == "avg":
                vals = np.nanmean(bp, axis=0)
                self._plot_bars(self._pop_ax, vals, labels, "Band power — Moyenne (agrandie)")
            else:
                i = max(0, min(self._sel_ch, bp.shape[0]-1))
                vals = bp[i, :]
                self._plot_bars(self._pop_ax, vals, labels, f"Band power — Canal {i} (agrandie)")

    # -------- runtime --------
    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        bp = in_data.get("bandpowers", None)
        labels = in_data.get("band_labels", None)
        ch = in_data.get("ch_names", None)
        info = in_data.get("info", None)
        self._last = {"bandpowers": bp, "band_labels": labels, "ch_names": ch, "info": info}

        self._refresh_channels()
        self._update_plot()
        return {}

    # -------- popup --------
    def _show_large_plot(self):
        if self._popup is not None:
            try: self._popup.close()
            except Exception: pass
            self._popup = None; self._pop_fig = None; self._pop_ax = None; self._pop_canvas = None

        dialog = QDialog()
        dialog.setWindowTitle("Band power — Vue agrandie")
        lay = QVBoxLayout(dialog)

        fig = Figure(figsize=(10,6))
        ax = fig.add_subplot(111)
        canvas = FigureCanvas(fig)
        lay.addWidget(canvas)

        self._popup = dialog
        self._pop_fig = fig
        self._pop_ax = ax
        self._pop_canvas = canvas

        self._update_plot()
        dialog.showMaximized()