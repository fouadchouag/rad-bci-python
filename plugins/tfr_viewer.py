# -*- coding: utf-8 -*-
"""
TFRViewer — robuste au changement de fichier / nbre de canaux
- Affiche AverageTFR / EpochsTFR (moyenne si nécessaire)
- Pins:  tfr, channel (str|int, optionnel)
- UI:    Single channel / dB / Channel combo / Agrandir
- Fixes:
  * nettoie correctement la figure (plus d'image résiduelle)
  * re-remplit la combo canaux à chaque nouveau TFR
  * fenêtre Agrandir synchronisée (canal/dB/single)
  * fallback canaux via tfr.info['ch_names'] (GDF/obj atypiques)
"""
from typing import Optional, Sequence
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox,
    QCheckBox, QDialog, QLabel
)
from PyQt5.QtCore import Qt

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class _BigDlg(QDialog):
    

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TFR – Agrandi")
        self.resize(1000, 650)
        self.fig = Figure(figsize=(10, 6), tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.canvas)


class TFRViewer(BasePlugin):

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
  'summary': 'TFRViewer — robuste au changement de fichier / nbre de canaux',
  'usage': 'Connect upstream data; adjust view parameters.'}
    
    
    name = "TFRViewer"
    language = "Python"
    category = "Output Nodes"
    supports_collapse = True
    start_hidden = False

    def setup(self):
        self.inputs = {
            "tfr": BehaviorSubject(None),
            "channel": BehaviorSubject(None),
        }
        self.outputs = {}

        self._widget: Optional[QWidget] = None
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvas] = None
        self._big: Optional[_BigDlg] = None

        self._chk_single = None
        self._cb_channel = None
        self._chk_db = None
        self._lbl = None

        self._single = True
        self._db = False
        self._ch_names: Sequence[str] = []
        self._chan_hint = None

        self._last_tfr = None
        self._last_nch = None  # pour détecter les changements de #canaux

    # -------------- UI --------------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(6, 6, 6, 6)
        pv.setSpacing(6)

        self._fig = Figure(figsize=(5, 3), tight_layout=True)
        self._canvas = FigureCanvas(self._fig)
        pv.addWidget(self._canvas)

        row = QHBoxLayout()
        self._chk_single = QCheckBox("Single channel")
        self._chk_single.setChecked(True)
        self._chk_single.stateChanged.connect(lambda s: self._toggle_single(s == Qt.Checked))
        row.addWidget(self._chk_single)

        row.addWidget(QLabel("Channel:"))
        self._cb_channel = QComboBox()
        self._cb_channel.currentIndexChanged.connect(lambda _: self._render_all())
        row.addWidget(self._cb_channel, 1)

        self._chk_db = QCheckBox("dB scale")
        self._chk_db.stateChanged.connect(lambda s: self._set_db(s == Qt.Checked))
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
        vw = QVBoxLayout(wrap)
        vw.setContentsMargins(0, 0, 0, 0)
        vw.addWidget(CollapsibleSection("TFR Viewer", panel, collapsed=False))
        self._widget = wrap
        return wrap

    # -------------- internals --------------
    def _toggle_single(self, b: bool):
        self._single = bool(b)
        self._render_all()

    def _set_db(self, b: bool):
        self._db = bool(b)
        self._render_all()

    def _open_big(self):
        if self._big is None:
            self._big = _BigDlg()
        self._plot_into(self._big.fig, self._last_tfr, big=True)
        self._big.canvas.draw_idle()
        self._big.show(); self._big.raise_(); self._big.activateWindow()

    def _hard_reset(self):
        # appelé quand on reçoit tfr=None ou quand #canaux change
        self._ch_names = []
        self._last_nch = None
        if self._cb_channel is not None:
            self._cb_channel.blockSignals(True)
            self._cb_channel.clear()
            self._cb_channel.blockSignals(False)
        self._clear_axes(self._fig, "No TFR")
        if self._big is not None:
            self._clear_axes(self._big.fig, "No TFR")
            try: self._big.canvas.draw_idle()
            except Exception: pass
        try:
            if self._canvas is not None:
                self._canvas.draw_idle()
        except Exception:
            pass

    def _update_channels(self, tfr):
        ch = []
        # 1) tfr.ch_names
        try:
            ch = list(getattr(tfr, "ch_names", []) or [])
        except Exception:
            ch = []
        # 2) fallback: info['ch_names']
        if not ch:
            try:
                info = getattr(tfr, "info", None)
                if info and "ch_names" in info:
                    ch = list(info["ch_names"] or [])
            except Exception:
                ch = []

        # détecter changement #canaux -> reset index/hints
        nch = len(ch)
        changed = (self._last_nch is None) or (nch != self._last_nch)
        self._last_nch = nch
        self._ch_names = ch

        if self._cb_channel is not None:
            self._cb_channel.blockSignals(True)
            self._cb_channel.clear()
            if ch:
                self._cb_channel.addItems(ch)
            # positionner un index valide
            set_to = 0
            if self._chan_hint is not None and ch:
                try:
                    if isinstance(self._chan_hint, int):
                        set_to = max(0, min(int(self._chan_hint), nch - 1))
                    else:
                        s = str(self._chan_hint).lower()
                        for i, nm in enumerate(ch):
                            if nm.lower() == s:
                                set_to = i; break
                except Exception:
                    set_to = 0
            if ch:
                self._cb_channel.setCurrentIndex(set_to)
            self._cb_channel.blockSignals(False)

        # si #canaux a changé, on re-render tout (évite écran blanc résiduel)
        if changed:
            self._render_all()

    def _current_idx(self) -> Optional[int]:
        if not self._single or not self._ch_names:
            return None
        idx = self._cb_channel.currentIndex() if self._cb_channel else -1
        if idx < 0:
            idx = 0
        return idx if 0 <= idx < len(self._ch_names) else None

    def _extract_mat(self, tfr, ch_idx: Optional[int]):
        try:
            times = np.asarray(tfr.times, float)
            freqs = np.asarray(tfr.freqs, float)
            data = tfr.data
        except Exception:
            return None, None, None
        if data is None:
            return None, None, None

        if data.ndim == 3:  # AverageTFR: (n_ch, n_freq, n_times)
            mat = np.nanmean(data, axis=0) if ch_idx is None else data[ch_idx, :, :]
        elif data.ndim == 4:  # EpochsTFR: (n_ep, n_ch, n_freq, n_times)
            mat = np.nanmean(data, axis=(0, 1)) if ch_idx is None else np.nanmean(data[:, ch_idx, :, :], axis=0)
        else:
            return None, None, None
        return np.asarray(mat, float), freqs, times

    def _clear_axes(self, fig: Figure, title="No TFR"):
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_title(title)
        ax.axis("off")
        try: fig.canvas.draw_idle()
        except Exception: pass

    def _plot_into(self, fig: Figure, tfr, big: bool = False):
        if tfr is None:
            self._clear_axes(fig, "No TFR"); return

        mat, freqs, times = self._extract_mat(tfr, self._current_idx())
        if mat is None or mat.size == 0 or freqs is None or times is None:
            self._clear_axes(fig, "Invalid TFR"); return

        if self._db:
            mat = 10.0 * np.log10(np.maximum(mat, np.finfo(float).tiny))

        fig.clear()
        ax = fig.add_subplot(111)
        extent = [float(times[0]), float(times[-1]), float(freqs[0]), float(freqs[-1])]
        im = ax.imshow(mat, origin="lower", aspect="auto", extent=extent)
        ax.axvline(0.0, linestyle="--", linewidth=0.8, color="k")
        ax.set_xlabel("Time (s)"); ax.set_ylabel("Frequency (Hz)")
        title = "TFR"
        if self._single and self._ch_names:
            ci = self._current_idx() if self._current_idx() is not None else 0
            title += f" – {self._ch_names[ci]}"
        ax.set_title(title)
        if big:
            try: fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            except Exception: pass
        ax.grid(False)
        try: fig.canvas.draw_idle()
        except Exception: pass

        if not big and self._lbl is not None:
            try: self._lbl.setText(f"{len(self._ch_names)} ch | {mat.shape[0]}×{mat.shape[1]}")
            except Exception: self._lbl.setText("")

    def _render_small(self):
        if self._fig is None:
            self._fig = Figure(figsize=(5, 3), tight_layout=True)
        self._plot_into(self._fig, self._last_tfr, big=False)
        try:
            if self._canvas is not None:
                self._canvas.draw_idle()
        except Exception:
            pass

    def _render_big(self):
        if self._big is not None:
            self._plot_into(self._big.fig, self._last_tfr, big=True)
            try: self._big.canvas.draw_idle()
            except Exception: pass

    def _render_all(self):
        self._render_small()
        self._render_big()

    # -------------- execute --------------
    def execute(self, **kwargs):
        if self._widget is None:
            try: self.build_widget()
            except Exception: pass

        d = kwargs.get("in_data", {}) if "in_data" in kwargs else {}
        d.update(kwargs)

        if "channel" in d:
            self._chan_hint = d.get("channel")

        tfr = d.get("tfr", None)
        self._last_tfr = tfr

        if tfr is None:
            self._hard_reset()
            return {}

        self._update_channels(tfr)
        self._render_all()
        return {}