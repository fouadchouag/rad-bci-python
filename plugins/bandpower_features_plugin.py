# plugins/bandpower_features_plugin.py
# -*- coding: utf-8 -*-
"""
BandpowerFeatures — extrait des features de puissance par bande (Welch).
Inputs:
  - segment : ndarray 2D (n_ch, n_t) ou (n_t, n_ch)
  - sfreq   : float (Hz) optionnel mais recommandé
  - ch_names: list[str] optionnel
Outputs:
  - features         : 1D ndarray concaténée (par canal puis par bande)
  - features_matrix  : 2D ndarray (n_ch, n_bands)
  - features_dim     : int
  - band_labels      : list[str] (ex: ["delta","theta","alpha","beta","gamma"])
Notes:
  - Paramétrable via UI: bandes, nperseg, overlap.
"""

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox
)

from core.node_base import BasePlugin

# Welch préféré si scipy dispo
try:
    from scipy.signal import welch
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False


def _ensure_seg_2d(seg):
    if seg is None:
        return None
    arr = np.asarray(seg)
    if arr.ndim != 2:
        return None
    # (n_ch, n_t) : on suppose que l'axe le plus long est le temps
    return arr if arr.shape[0] < arr.shape[1] else arr.T


def _parse_bands(spec: str):
    """
    spec: "delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45"
    -> [("delta",(1,4)), ...]
    """
    bands = []
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" not in tok or "-" not in tok:
            continue
        name, fr = tok.split(":", 1)
        lo, hi = fr.split("-", 1)
        try:
            lo = float(lo); hi = float(hi)
            if hi > lo:
                bands.append((name.strip(), (lo, hi)))
        except Exception:
            pass
    return bands


def _welch_psd(x, fs, nperseg, noverlap):
    """x: (n_t,), retourne (f, Pxx)"""
    if _HAVE_SCIPY:
        f, pxx = welch(x, fs=fs, nperseg=nperseg, noverlap=noverlap, detrend='constant')
        return f, pxx
    # Fallback sans SciPy: fenêtre glissante et moyenne de periodogrammes
    n = len(x)
    step = nperseg - noverlap
    if step <= 0:
        step = nperseg // 2 or 1
    wins = []
    for start in range(0, n - nperseg + 1, step):
        seg = x[start:start + nperseg]
        seg = seg - np.mean(seg)
        win = np.hanning(len(seg))
        xf = np.fft.rfft(seg * win)
        pxx = (np.abs(xf) ** 2) / (np.sum(win**2) * fs)
        wins.append(pxx)
    if not wins:
        # dernier recours: un seul periodogramme
        seg = x - np.mean(x)
        win = np.hanning(len(seg))
        xf = np.fft.rfft(seg * win)
        pxx = (np.abs(xf) ** 2) / (np.sum(win**2) * fs)
        wins = [pxx]
    pxx_mean = np.mean(np.stack(wins, axis=0), axis=0)
    f = np.fft.rfftfreq(nperseg, d=1.0/fs)
    return f, pxx_mean


class BandpowerFeaturesPlugin(BasePlugin):
    help = help = { 'gotchas': ['Use adequate window length for low frequencies.'],
  'inputs': {'segment': '2D float [ch x samples] or epochs', 'sfreq': 'float (Hz)'},
  'outputs': { 'features': 'array/dict',
               'freqs': 'optional freqs',
               'psd': 'optional PSD'},
  'parameters': [ { 'default': 1.0,
                    'desc': 'Lower frequency',
                    'name': 'fmin',
                    'type': 'float',
                    'unit': 'Hz'},
                  { 'default': 40.0,
                    'desc': 'Upper frequency',
                    'name': 'fmax',
                    'type': 'float',
                    'unit': 'Hz'}],
  'summary': 'BandpowerFeatures — extrait des features de puissance par bande (Welch).',
  'usage': 'Connect windowed or epoched data; feed features to ML nodes.'}

    name = "BandpowerFeatures"
    language = "Python"
    category = "ML / Features"

    def setup(self):
        # Inputs
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["sfreq"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        # Outputs
        self.outputs["features"] = BehaviorSubject(None)
        self.outputs["features_matrix"] = BehaviorSubject(None)
        self.outputs["features_dim"] = BehaviorSubject(None)
        self.outputs["band_labels"] = BehaviorSubject(["delta","theta","alpha","beta","gamma"])

        # UI state (défauts)
        self._bands_spec = "delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45"
        self._nperseg = 256
        self._overlap = 0.5  # ratio 0..0.9

        self._widget = None
        self._lbl_info = None
        self._txt_bands = None
        self._spin_nperseg = None
        self._spin_overlap = None

    # ------------- UI -------------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)

        self._lbl_info = QLabel("Welch PSD → bandpowers (concat ch×bands).")
        self._lbl_info.setStyleSheet("font-weight: 600;")
        root.addWidget(self._lbl_info)

        form = QFormLayout()
        self._txt_bands = QLineEdit(self._bands_spec)
        form.addRow("Bandes (name:lo-hi)", self._txt_bands)

        self._spin_nperseg = QSpinBox()
        self._spin_nperseg.setRange(32, 4096)
        self._spin_nperseg.setValue(self._nperseg)
        form.addRow("nperseg (Welch)", self._spin_nperseg)

        self._spin_overlap = QDoubleSpinBox()
        self._spin_overlap.setRange(0.0, 0.9)
        self._spin_overlap.setSingleStep(0.1)
        self._spin_overlap.setDecimals(2)
        self._spin_overlap.setValue(self._overlap)
        form.addRow("overlap (0–0.9)", self._spin_overlap)

        root.addLayout(form)

        # Appliquer modifications en temps réel
        self._txt_bands.editingFinished.connect(self._on_ui_changed)
        self._spin_nperseg.valueChanged.connect(self._on_ui_changed)
        self._spin_overlap.valueChanged.connect(self._on_ui_changed)

        self._widget = w
        return w

    def _on_ui_changed(self, *args):
        self._bands_spec = self._txt_bands.text().strip() if self._txt_bands else self._bands_spec
        self._nperseg = int(self._spin_nperseg.value()) if self._spin_nperseg else self._nperseg
        self._overlap = float(self._spin_overlap.value()) if self._spin_overlap else self._overlap
        # Forcer un recalcul sur prochain segment (execute gère déjà)

    # ------------- Core -------------
    def _compute_bandpowers(self, seg, fs, bands):
        """
        seg: (n_ch, n_t)
        bands: list[(name,(lo,hi))]
        return matrix: (n_ch, n_bands), labels: [name,...]
        """
        n_ch, n_t = seg.shape
        nperseg = min(self._nperseg, n_t) if n_t > 0 else self._nperseg
        noverlap = int(self._overlap * nperseg)

        out = np.zeros((n_ch, len(bands)), dtype=float)
        for ci in range(n_ch):
            x = seg[ci, :]
            f, pxx = _welch_psd(x, fs=fs, nperseg=nperseg, noverlap=noverlap)
            for bi, (name, (lo, hi)) in enumerate(bands):
                # Intégration simple de la densité dans la bande
                mask = (f >= lo) & (f < hi)
                out[ci, bi] = np.trapz(pxx[mask], f[mask]) if np.any(mask) else 0.0
        return out

    def execute(self, inputs):
        seg = _ensure_seg_2d(inputs.get("segment"))
        if seg is None:
            return  # rien à faire
        fs = inputs.get("sfreq")
        if fs is None:
            # Heuristique: sans fs, on normalise mais la fréquence est inconnue
            # On retourne quand même une énergie par bande utilisant indices (approx).
            # Mieux: passer sfreq depuis Segmenter/Reader.
            return

        bands = _parse_bands(self._bands_spec)
        if not bands:
            bands = [("delta",(1,4)),("theta",(4,8)),("alpha",(8,13)),("beta",(13,30)),("gamma",(30,45))]

        M = self._compute_bandpowers(seg, fs, bands)  # (n_ch, n_bands)
        feats = M.reshape(-1)  # concat ch×bands

        self.outputs["features_matrix"].on_next(M)
        self.outputs["features"].on_next(feats)
        self.outputs["features_dim"].on_next(int(feats.size))
        self.outputs["band_labels"].on_next([b[0] for b in bands])