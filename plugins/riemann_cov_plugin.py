# plugins/riemann_cov_plugin.py
# -*- coding: utf-8 -*-
"""
RiemannCov — calcule la covariance SPD d'un segment EEG.
Inputs:
  - segment : ndarray 2D (n_ch, n_t) ou (n_t, n_ch)
Outputs:
  - cov     : ndarray 2D (n_ch, n_ch) SPD
UI:
  - epsilon : régularisation diagonale (ex: 1e-6..1e-2)
"""
import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QLabel
from core.node_base import BasePlugin

def _ensure_seg_2d(seg):
    if seg is None: return None
    arr = np.asarray(seg)
    if arr.ndim != 2: return None
    return arr if arr.shape[0] < arr.shape[1] else arr.T  # (n_ch, n_t)

class RiemannCovPlugin(BasePlugin):
    name = "RiemannCov"
    language = "Python"
    category = "ML / Riemann"

    def setup(self):
        self.inputs["segment"] = BehaviorSubject(None)
        self.outputs["cov"] = BehaviorSubject(None)
        self._eps = 1e-6
        self._widget = None
        self._spin_eps = None

    def build_widget(self):
        if self._widget is not None: return self._widget
        w = QWidget(); root = QVBoxLayout(w)
        info = QLabel("Covariance SPD = (X Xᵀ)/(T-1) + εI"); info.setStyleSheet("font-weight:600;")
        root.addWidget(info)
        form = QFormLayout()
        self._spin_eps = QDoubleSpinBox(); self._spin_eps.setDecimals(8)
        self._spin_eps.setRange(1e-12, 1e-1); self._spin_eps.setSingleStep(1e-6); self._spin_eps.setValue(self._eps)
        form.addRow("ε (regularization)", self._spin_eps)
        root.addLayout(form)
        self._spin_eps.valueChanged.connect(lambda v: setattr(self, "_eps", float(v)))
        self._widget = w
        return w

    def execute(self, inputs):
        seg = _ensure_seg_2d(inputs.get("segment"))
        if seg is None: return
        n_ch, n_t = seg.shape
        if n_t < 2: return
        X = seg - seg.mean(axis=1, keepdims=True)
        cov = (X @ X.T) / max(1, (n_t - 1))
        cov.flat[::n_ch+1] += self._eps  # εI
        self.outputs["cov"].on_next(cov)
