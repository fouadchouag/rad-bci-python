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
"""

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QSpinBox,
    QLayout, QSizePolicy
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin
try:
    from core.ui_kit import UiKit
except Exception:
    UiKit = None

class BandpowerExt(BasePlugin):
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
  'summary': 'BandpowerExt — extrait des puissances de bandes par canal depuis des '
             'segments.',
  'usage': 'Connect windowed or epoched data; feed features to ML nodes.'}

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
        if UiKit: UiKit.apply_node_style(w)
        root = QVBoxLayout(w)
        root.setContentsMargins(6,6,6,6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Preset:"))
        cmb = QComboBox(); cmb.addItems(["MI (alpha,beta)", "Full (delta,theta,alpha,beta)"])
        cmb.currentTextChanged.connect(lambda t: setattr(self, "_preset", t))
        row1.addWidget(cmb, 1)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        chk = QCheckBox("Relative power (1–40 Hz)")
        chk.setChecked(True)
        chk.stateChanged.connect(lambda s: setattr(self, "_relative", bool(s)))
        row2.addWidget(chk)
        row2.addSpacing(10)
        row2.addWidget(QLabel("nperseg:"))
        sp = QSpinBox(); sp.setRange(32, 4096); sp.setValue(self._nperseg)
        sp.valueChanged.connect(lambda v: setattr(self, "_nperseg", int(v)))
        row2.addWidget(sp)
        row2.addStretch(1)
        root.addLayout(row2)
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
            # ambiguous; assume (n_ch, n_s) ok
            pass
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
            band_names = ["delta","theta","alpha","beta"]
            bands = [(1.0,4.0),(4.0,8.0),(8.0,12.0),(13.0,30.0)]
        else:
            band_names = ["alpha","beta"]
            bands = [(8.0,12.0),(13.0,30.0)]
        return bands, band_names

    def _compute_bandpower(self, X, sf, bands, relative=True, nperseg=256):
        """
        X: (n_ch, n_s)
        Retourne (n_ch, n_bands)
        """
        n_ch, n_s = X.shape
        # Welch simple (sans SciPy)
        win_len = min(nperseg, n_s)
        if win_len < 16:
            win_len = n_s
        hop = max(1, win_len // 2)
        win = np.hanning(win_len)

        # fréquence
        nfft = int(2 ** int(np.ceil(np.log2(win_len))))
        freqs = np.fft.rfftfreq(nfft, d=1.0/sf)
        idx_1_40 = np.where((freqs >= 1.0) & (freqs <= 40.0))[0]

        psd = np.zeros((n_ch, len(freqs)), dtype=np.float64)
        n_win = 0
        start = 0
        while start + win_len <= n_s:
            xw = X[:, start:start+win_len] * win[None, :]
            # FFT
            F = np.fft.rfft(xw, n=nfft, axis=1)
            P = (np.abs(F) ** 2) / (np.sum(win**2))
            psd += P
            n_win += 1
            start += hop
        if n_win == 0:
            F = np.fft.rfft(X * np.hanning(n_s)[None,:], n=nfft, axis=1)
            psd = (np.abs(F) ** 2) / np.sum(np.hanning(n_s)**2)
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