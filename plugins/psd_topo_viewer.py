# -*- coding: utf-8 -*-
"""
PSDTopoViewer (lite + fullscreen)
- Topomap/bars d’énergie spectrale moyenne sur une bande à partir de PSD (Welch).
- Pins MINIMALES :
    psd       : np.ndarray (n_ch, n_freq) ou (n_epochs, n_ch, n_freq)
    freqs     : np.ndarray (n_freq,)
    ch_names  : list[str]
- UI pliable : band_low, band_high, agg('mean'/'median'), dB, + bouton "Agrandir".
- Si noms de canaux matchent standard_1020 → topomap ; sinon fallback barplot propre.
"""

from typing import Optional, Any
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox, QCheckBox,
    QPushButton, QDialog
)
from PyQt5.QtCore import Qt

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection
import mne


class PSDTopoViewer(BasePlugin):
    help = {
        'summary': 'Topomap or bar-chart of average PSD power in a configurable frequency band.',
        'usage': 'Connect psd, freqs, and ch_names from a PSD computation node. Adjust band range and aggregation in the collapsible panel.',
        'inputs': {
            'psd': '2D float [channels x frequencies] or 3D [epochs x channels x frequencies] — power spectral density',
            'freqs': '1D float array — frequency axis (Hz)',
            'ch_names': 'list[str] — channel names; must match standard_1020 montage for topomap rendering',
            'band_low': 'float — lower frequency bound of the band (default 8.0 Hz)',
            'band_high': 'float — upper frequency bound of the band (default 12.0 Hz)',
            'agg': 'str — aggregation method: "mean" or "median" (default "mean")',
            'db': 'bool — convert power to dB before aggregation (default True)',
        },
        'outputs': {
            'noop': 'None — viewer-only node (output exists for pipeline compatibility)',
        },
        'parameters': [
            {'name': 'band_low', 'type': 'float', 'default': 8.0, 'desc': 'Lower frequency bound (Hz) for the power band'},
            {'name': 'band_high', 'type': 'float', 'default': 12.0, 'desc': 'Upper frequency bound (Hz) for the power band'},
            {'name': 'agg', 'type': 'str', 'default': 'mean', 'desc': 'Aggregation across frequency bins: "mean" or "median"'},
            {'name': 'db', 'type': 'bool', 'default': True, 'desc': 'Apply 10*log10 before aggregating'},
        ],
        'gotchas': [
            'Topomap requires at least 3 channels whose names match the MNE standard_1020 montage.',
            'Falls back to a bar chart when channel names are unrecognized or fewer than 3 match.',
            '3D PSD input (epochs x channels x frequencies) is averaged across epochs automatically.',
            'band_low must be <= band_high; if band_high < band_low, no frequency bins are selected.',
            'The noop output exists only so the node can be wired into pipelines that require an output pin.',
        ],
    }

    name = "PSDTopoViewer"
    language = "Python"
    category = "Visualization"
    supports_collapse = True

    # ---------- lifecycle ----------
    def setup(self):
        # Entrées minimales
        self.inputs["psd"] = BehaviorSubject(None)
        self.inputs["freqs"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        # Réglages
        self.inputs["band_low"] = BehaviorSubject(8.0)
        self.inputs["band_high"] = BehaviorSubject(12.0)
        self.inputs["agg"] = BehaviorSubject("mean")   # 'mean' | 'median'
        self.inputs["db"] = BehaviorSubject(True)

        # Sortie factice (viewer)
        self.outputs["noop"] = BehaviorSubject(None)

        # État runtime
        self._psd = None
        self._freqs = None
        self._ch_names = None

        # UI
        self._fig: Optional[Figure] = None
        self._canvas: Optional[FigureCanvas] = None
        self._sp_low = self._sp_high = None
        self._cb_agg = None
        self._chk_db = None
        self._widget: Optional[QWidget] = None

        # Fullscreen window
        self._big_win: Optional[QDialog] = None
        self._big_fig: Optional[Figure] = None
        self._big_canvas: Optional[FigureCanvas] = None

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)

        # Panneau réglages (pliable)
        panel = QWidget()
        h = QHBoxLayout(panel)
        h.setContentsMargins(8, 8, 8, 4)
        h.setSpacing(10)

        h.addWidget(QLabel("Band (Hz):"))
        self._sp_low = QDoubleSpinBox()
        self._sp_low.setRange(0.0, 1000.0)
        self._sp_low.setDecimals(2)
        self._sp_low.setSingleStep(0.5)
        self._sp_low.setValue(float(self.inputs["band_low"].value))
        self._sp_low.valueChanged.connect(lambda v: self.set_input("band_low", float(v)))
        h.addWidget(self._sp_low)

        self._sp_high = QDoubleSpinBox()
        self._sp_high.setRange(0.0, 1000.0)
        self._sp_high.setDecimals(2)
        self._sp_high.setSingleStep(0.5)
        self._sp_high.setValue(float(self.inputs["band_high"].value))
        self._sp_high.valueChanged.connect(lambda v: self.set_input("band_high", float(v)))
        h.addWidget(self._sp_high)

        h.addWidget(QLabel("Agg:"))
        self._cb_agg = QComboBox()
        self._cb_agg.addItems(["mean", "median"])
        self._cb_agg.setCurrentText(str(self.inputs["agg"].value))
        self._cb_agg.currentTextChanged.connect(lambda t: self.set_input("agg", str(t)))
        h.addWidget(self._cb_agg)

        self._chk_db = QCheckBox("dB")
        self._chk_db.setChecked(bool(self.inputs["db"].value))
        self._chk_db.stateChanged.connect(lambda s: self.set_input("db", bool(s == Qt.Checked)))
        h.addWidget(self._chk_db)

        # --- bouton Agrandir ---
        btn_big = QPushButton("Agrandir")
        btn_big.clicked.connect(self._open_big_view)
        h.addWidget(btn_big)

        h.addStretch(1)
        v.addWidget(CollapsibleSection("Réglages PSD Topo", panel, collapsed=True))

        # Figure (vue normale)
        self._fig = Figure(figsize=(4.2, 3.6), dpi=100)
        self._canvas = FigureCanvas(self._fig)
        v.addWidget(self._canvas, stretch=1)

        self._widget = root
        return root

    # ---------- helpers ----------
    @staticmethod
    def _coerce_psd(psd: Any) -> Optional[np.ndarray]:
        """(n_epochs, n_ch, n_freq) -> moyenne epochs ; (n_ch, n_freq) -> tel quel."""
        if psd is None:
            return None
        arr = np.asarray(psd)
        if arr.ndim == 3:
            return np.nanmean(arr, axis=0)
        if arr.ndim == 2:
            return arr
        return None

    @staticmethod
    def _band_vector(psd2: np.ndarray, freqs: np.ndarray, f_lo: float, f_hi: float,
                     agg: str, use_db: bool) -> Optional[np.ndarray]:
        if psd2 is None or freqs is None:
            return None
        freqs = np.asarray(freqs).ravel()
        if psd2.ndim != 2 or freqs.ndim != 1 or psd2.shape[1] != freqs.size:
            return None

        f_lo = max(0.0, float(f_lo))
        f_hi = max(f_lo, float(f_hi))
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if not np.any(mask):
            return None
        sub = psd2[:, mask]
        if use_db:
            sub = 10.0 * np.log10(np.maximum(sub, np.finfo(float).eps))
        if agg == "median":
            vec = np.nanmedian(sub, axis=1)
        else:
            vec = np.nanmean(sub, axis=1)
        return np.asarray(vec, dtype=float)

    def _render_into(self, fig: Figure):
        """Rend le contenu dans la figure donnée (vue normale ou agrandie)."""
        psd2 = self._coerce_psd(self._psd)
        freqs = np.asarray(self._freqs) if self._freqs is not None else None
        ch_names = list(self._ch_names or [])

        fig.clf()
        ax = fig.add_subplot(111)

        if psd2 is None or freqs is None or not ch_names:
            ax.text(0.5, 0.5, "En attente de psd / freqs / ch_names…", ha="center", va="center")
            ax.set_axis_off()
            return

        f_lo = float(self.inputs["band_low"].value)
        f_hi = float(self.inputs["band_high"].value)
        agg = str(self.inputs["agg"].value).lower()
        use_db = bool(self.inputs["db"].value)

        vec = self._band_vector(psd2, freqs, f_lo, f_hi, agg, use_db)
        if vec is None or vec.size != len(ch_names):
            ax.text(0.5, 0.5, "Bande invalide ou dimensions incohérentes.", ha="center", va="center")
            ax.set_axis_off()
            return

        # Essayer une topomap via montage standard_1020
        try:
            montage = mne.channels.make_standard_montage("standard_1020")
            pos_dict = montage._get_ch_pos()
            pos = []
            use_idx = []
            for i, nm in enumerate(ch_names):
                if nm in pos_dict:
                    pos.append(pos_dict[nm][:2])  # (x, y) only
                    use_idx.append(i)

            if len(pos) >= 3:
                mne.viz.plot_topomap(vec[use_idx], np.array(pos), axes=ax, show=False)
                ax.set_title(f"PSD Topomap {f_lo:.1f}–{f_hi:.1f} Hz ({agg}{' dB' if use_db else ''})")
            else:
                # Fallback: barplot propre
                ax.bar(range(len(vec)), vec)
                ax.set_xticks(range(len(vec)))
                ax.set_xticklabels(ch_names, rotation=90, fontsize=8)
                ax.set_title(f"PSD (bar) {f_lo:.1f}–{f_hi:.1f} Hz (pas de positions)")
        except Exception as e:
            ax.text(0.5, 0.5, f"Topomap indisponible:\n{e}", ha="center", va="center")
            ax.set_axis_off()

    # ---------- rendu normal ----------
    def _render(self):
        if self._fig is None or self._canvas is None:
            return
        self._render_into(self._fig)
        self._canvas.draw_idle()

        # mettre à jour la grande fenêtre si ouverte
        if self._big_win is not None and self._big_fig is not None and self._big_canvas is not None:
            self._render_into(self._big_fig)
            self._big_canvas.draw_idle()

    # ---------- fullscreen ----------
    def _open_big_view(self):
        if self._big_win is not None:
            try:
                self._big_win.raise_()
                self._big_win.activateWindow()
                return
            except Exception:
                self._big_win = None

        dlg = QDialog()
        dlg.setWindowTitle("PSD Topomap — Agrandi")
        dlg.resize(1100, 800)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(6, 6, 6, 6)

        self._big_fig = Figure(figsize=(10, 7.5), dpi=100)
        self._big_canvas = FigureCanvas(self._big_fig)
        lay.addWidget(self._big_canvas)

        # Premier rendu
        self._render_into(self._big_fig)
        self._big_canvas.draw_idle()

        def _cleanup():
            self._big_canvas = None
            self._big_fig = None
            self._big_win = None

        dlg.finished.connect(_cleanup)
        self._big_win = dlg
        dlg.show()

    # ---------- exécution ----------
    def execute(self, in_data=None, **kwargs):
        # Unifier l’entrée
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        # Mises à jour des buffers
        if "psd" in in_data:
            self._psd = in_data["psd"]
        if "freqs" in in_data:
            self._freqs = in_data["freqs"]
        if "ch_names" in in_data:
            self._ch_names = in_data["ch_names"]

        # Eventuels réglages reçus par programme
        if "band_low" in in_data and self._sp_low is not None:
            self._sp_low.blockSignals(True); self._sp_low.setValue(float(in_data["band_low"])); self._sp_low.blockSignals(False)
        if "band_high" in in_data and self._sp_high is not None:
            self._sp_high.blockSignals(True); self._sp_high.setValue(float(in_data["band_high"])); self._sp_high.blockSignals(False)
        if "agg" in in_data and self._cb_agg is not None:
            self._cb_agg.blockSignals(True); self._cb_agg.setCurrentText(str(in_data["agg"])); self._cb_agg.blockSignals(False)
        if "db" in in_data and self._chk_db is not None:
            self._chk_db.blockSignals(True); self._chk_db.setChecked(bool(in_data["db"])); self._chk_db.blockSignals(False)

        # Rendu (normal + sync fullscreen si ouvert)
        self._render()
        return {"noop": None}