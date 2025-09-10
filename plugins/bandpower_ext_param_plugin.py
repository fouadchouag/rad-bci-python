# plugins/bandpower_ext_plugin.py
# -*- coding: utf-8 -*-
"""
BandpowerExt — extrait des puissances de bandes par canal depuis des segments.
Entrées:
  - segment : np.ndarray (n_ch, n_s) ou (n_s, n_ch)
  - ch_names: list[str] (optionnel)
  - sfreq   : float     (optionnel, sinon 250 Hz par défaut)
Sorties:
  - features    : dict {channel: {band: value}}
  - band_labels : list[str] (ordre des bandes)
Notes:
  - Implémentation légère type Welch (sans SciPy).
  - Mode 'relative'=True par défaut (rapport à 1–40 Hz).

→ Section Paramètres pliable (fermée par défaut, sans espace gris).
"""

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QSpinBox,
    QLayout, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from core.node_base import BasePlugin
try:
    from core.ui_kit import UiKit
except Exception:
    UiKit = None


# ---------------------- CollapsibleSection robuste (anti "rectangle gris") ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parents.
    """
    collapsedChanged = pyqtSignal(bool)  # True si fermé

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._base_title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QLabel()  # on utilise un QLabel + style pour rester minimal
        # Remplace par un QPushButton checkable si tu veux un vrai bouton; ici, on garde le style unifié
        # mais on va utiliser un "fake toggle" en cliquant sur la ligne !
        # Pour rester simple et fiable, on met un QPushButton:
        from PyQt5.QtWidgets import QPushButton
        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # démarrage fermé
        self._btn.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding:6px 8px; font-weight:600;"
            " border:1px solid #ccc; border-radius:6px; background:#f7f7f7;"
            "}"
        )
        self._btn.toggled.connect(self._on_toggled)
        root.addWidget(self._btn)

        self._content = QWidget()
        self._content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 8, 10, 8)
        self._content_layout.setSpacing(6)
        self._content_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._apply_collapsed_state(True)
        self._update_btn_text()

    # API
    def content_layout(self):
        return self._content_layout

    def add_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)  # checked => ouvert
        # (Qt ne supporte pas l'opérateur ! en Python, on corrige ci-dessous)
        # Correction:
        self._btn.setChecked(not collapsed)
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Slots
    def _on_toggled(self, checked: bool):
        collapsed = (not checked)
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Implémentation
    def _apply_collapsed_state(self, collapsed: bool):
        if collapsed:
            self._content.setMaximumHeight(0)
            self._content.setMinimumHeight(0)
            self._content.setVisible(False)
            self._line.setVisible(False)
        else:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            self._content.setMinimumHeight(0)
            self._line.setVisible(True)

    def _update_btn_text(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._base_title
        if base.startswith(("▼ ", "▶ ")):
            base = base[2:]
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry()
        self.updateGeometry()
        p = self.parentWidget()
        if p is not None:
            if p.layout():
                p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._delayed_adjust)

    def _delayed_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout():
                    w.layout().activate()
                w.adjustSize()
                w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


class BandpowerExt(BasePlugin):
    help = {
        'gotchas': ['Use adequate window length for low frequencies.'],
        'inputs': {'segment': '2D float [ch x samples] or epochs', 'sfreq': 'float (Hz)'},
        'outputs': {'features': 'array/dict', 'freqs': 'optional freqs', 'psd': 'optional PSD'},
        'parameters': [
            {'name': 'fmin', 'type': 'float', 'default': 1.0, 'unit': 'Hz', 'desc': 'Lower frequency'},
            {'name': 'fmax', 'type': 'float', 'default': 40.0, 'unit': 'Hz', 'desc': 'Upper frequency'},
        ],
        'summary': 'BandpowerExt — extrait des puissances de bandes par canal depuis des segments.',
        'usage': 'Connect windowed or epoched data; feed features to ML nodes.'
    }

    name = "BandpowerExt_param"
    language = "Python"
    category = "Processing Nodes"

    def setup(self):
        self.inputs["segment"]   = BehaviorSubject(None)
        self.inputs["ch_names"]  = BehaviorSubject(None)
        self.inputs["sfreq"]     = BehaviorSubject(None)

        self.outputs["features"]     = BehaviorSubject(None)
        self.outputs["band_labels"]  = BehaviorSubject(None)

        # params
        self._preset = "MI (alpha,beta)"
        self._relative = True
        self._nperseg = 256
        self._sf_fallback = 250.0

        # cached last
        self._last_bands = None

    def build_widget(self):
        w = QWidget()
        if UiKit:
            try:
                UiKit.apply_node_style(w)
            except Exception:
                pass

        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # -------- Paramètres (pliable, fermé par défaut)
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Row 1: Preset
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Preset:"))
        cmb = QComboBox()
        cmb.addItems(["MI (alpha,beta)", "Full (delta,theta,alpha,beta)"])
        cmb.setCurrentText(self._preset)
        cmb.currentTextChanged.connect(lambda t: setattr(self, "_preset", t))
        row1.addWidget(cmb, 1)

        # Row 2: Relative + nperseg
        row2 = QHBoxLayout()
        chk = QCheckBox("Relative power (1–40 Hz)")
        chk.setChecked(True)
        chk.stateChanged.connect(lambda s: setattr(self, "_relative", bool(s)))
        row2.addWidget(chk)
        row2.addSpacing(10)
        row2.addWidget(QLabel("nperseg:"))
        sp = QSpinBox()
        sp.setRange(32, 4096)
        sp.setValue(self._nperseg)
        sp.valueChanged.connect(lambda v: setattr(self, "_nperseg", int(v)))
        row2.addWidget(sp)
        row2.addStretch(1)

        # Injecter dans la section
        sec.content_layout().addLayout(row1)
        sec.content_layout().addLayout(row2)

        # Ajouter la section au root
        root.addWidget(sec)

        # Contraintes pour supprimer tout résidu d’espace
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        return w

    def execute(self, **kw):
        seg = kw.get("segment", None)
        if seg is None:
            self.outputs["features"].on_next(None)
            self.outputs["band_labels"].on_next(None)
            return {}

        arr = np.asarray(seg)
        if arr.ndim == 1:
            arr = arr[None, :]
        # (n_ch, n_s)
        if arr.shape[0] < arr.shape[1]:
            pass  # assume (n_ch, n_s)
        else:
            # likely (n_s, n_ch)
            if arr.shape[0] > arr.shape[1]:
                arr = arr.T

        ch_names = kw.get("ch_names", None)
        if not isinstance(ch_names, (list, tuple)) or len(ch_names) != arr.shape[0]:
            ch_names = [f"Ch{i+1}" for i in range(arr.shape[0])]

        sf = kw.get("sfreq", None)
        try:
            sf = float(sf) if sf is not None else float(self._sf_fallback)
        except Exception:
            sf = float(self._sf_fallback)

        bands, band_names = self._bands_for_preset()
        feats = self._compute_bandpower(arr, sf, bands, relative=self._relative, nperseg=self._nperseg)

        # to dict
        out = {}
        for ci, ch in enumerate(ch_names):
            row = {}
            for bi, bname in enumerate(band_names):
                row[bname] = float(feats[ci, bi])
            out[str(ch)] = row

        self._last_bands = list(band_names)
        self.outputs["features"].on_next(out)
        self.outputs["band_labels"].on_next(list(band_names))
        return {}

    def _bands_for_preset(self):
        if "Full" in (self._preset or ""):
            band_names = ["delta", "theta", "alpha", "beta"]
            bands = [(1.0, 4.0), (4.0, 8.0), (8.0, 12.0), (13.0, 30.0)]
        else:
            band_names = ["alpha", "beta"]
            bands = [(8.0, 12.0), (13.0, 30.0)]
        return bands, band_names

    def _compute_bandpower(self, X, sf, bands, relative=True, nperseg=256):
        """
        X: (n_ch, n_s) → retourne (n_ch, n_bands)
        """
        X = np.asarray(X, dtype=float)
        n_ch, n_s = X.shape
        # Welch simple (sans SciPy)
        win_len = min(nperseg, n_s)
        if win_len < 16:
            win_len = n_s
        hop = max(1, win_len // 2)
        win = np.hanning(win_len)

        # fréquences
        nfft = int(2 ** int(np.ceil(np.log2(win_len))))
        freqs = np.fft.rfftfreq(nfft, d=1.0 / sf)
        idx_1_40 = np.where((freqs >= 1.0) & (freqs <= 40.0))[0]

        psd = np.zeros((n_ch, len(freqs)), dtype=np.float64)
        n_win = 0
        start = 0
        while start + win_len <= n_s:
            xw = X[:, start:start + win_len] * win[None, :]
            F = np.fft.rfft(xw, n=nfft, axis=1)
            P = (np.abs(F) ** 2) / (np.sum(win ** 2))
            psd += P
            n_win += 1
            start += hop
        if n_win == 0:
            F = np.fft.rfft(X * np.hanning(n_s)[None, :], n=nfft, axis=1)
            psd = (np.abs(F) ** 2) / np.sum(np.hanning(n_s) ** 2)
            n_win = 1
        psd /= float(n_win)

        out = np.zeros((n_ch, len(bands)), dtype=np.float64)
        denom = np.maximum(1e-20, np.sum(psd[:, idx_1_40], axis=1)) if relative else 1.0
        for bi, (f0, f1) in enumerate(bands):
            idx = np.where((freqs >= f0) & (freqs <= f1))[0]
            bp = np.sum(psd[:, idx], axis=1)
            if relative:
                bp = bp / denom
            out[:, bi] = bp
        return out
