# plugins/bci_euclidean_alignment_node.py
# -*- coding: utf-8 -*-
"""
BCI_EuclideanAlignment — Per-subject Euclidean Alignment (EA) for cross-subject BCI.

Implements the EA preprocessing described in Chapter 4, Section 4.4.7 of the thesis.
For subject s, EA computes the mean trace-normalized covariance across all available
training trials, then derives a whitening matrix W_s that maps the subject's EEG
distribution toward identity covariance.

In fit mode, the node accumulates trials and computes the whitening matrix.
In transform mode, it applies the previously computed whitening matrix.

Inputs:
  - segment   : ndarray (n_samples x n_channels) or (n_channels x n_samples)
  - sfreq     : float
  - ch_names  : list[str] (optional)
  - y_idx     : int (optional, for tracking class info)

Outputs:
  - segment   : aligned EEG segment
  - sfreq     : sampling frequency (unchanged)
  - ch_names  : channel names (unchanged)
  - ea_matrix : the whitening matrix W_s (n_channels x n_channels)
  - config_out: dict
"""
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSizePolicy
)

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


def _ensure_nchn(seg):
    """Ensure shape (n_channels, n_samples)."""
    arr = np.asarray(seg, float)
    if arr.ndim == 1:
        return arr[:, None]
    if arr.shape[0] > arr.shape[1]:
        return arr.T
    return arr


class BCIEuclideanAlignment(BasePlugin):
    help = {
        'gotchas': [
            "In fit mode, accumulate all training trials before enabling transform.",
            "EA requires no label information from the target subject."
        ],
        'inputs': {
            'segment': '2D float [ch x samples]',
            'sfreq': 'float (sampling frequency)',
            'ch_names': 'list[str] (optional)',
        },
        'outputs': {
            'segment': 'aligned 2D float [ch x samples]',
            'sfreq': 'float',
            'ch_names': 'list[str]',
            'ea_matrix': '2D float [ch x ch] whitening matrix',
            'config_out': 'dict',
        },
        'parameters': [
            {'name': 'enabled', 'type': 'bool', 'default': True,
             'desc': 'Enable/disable EA transformation'},
            {'name': 'epsilon', 'type': 'float', 'default': 1e-8,
             'desc': 'Regularization for covariance eigendecomposition'},
        ],
        'summary': 'Per-subject Euclidean Alignment for cross-subject BCI.',
        'usage': 'Connect EEG segments. In fit mode, accumulate training trials; '
                 'in transform mode, EA is applied automatically.'
    }

    name = "BCI_EuclideanAlignment"
    language = "Python"
    category = "Preprocessing"

    def setup(self):
        self.inputs["segment"]  = BehaviorSubject(None)
        self.inputs["sfreq"]    = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["config_in"] = BehaviorSubject(None)

        self.outputs["segment"]   = BehaviorSubject(None)
        self.outputs["sfreq"]     = BehaviorSubject(None)
        self.outputs["ch_names"]  = BehaviorSubject(None)
        self.outputs["ea_matrix"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        self._enabled = True
        self._epsilon = 1e-8

        # State
        self._fit_seg = []          # accumulated training segments (n_ch, T_i)
        self._whitening = None      # W_s (n_ch, n_ch)
        self._is_fitted = False
        self._n_ch = None

        # UI
        self._lbl = None
        self._ck_enabled = None
        self._sp_eps = None

    def build_widget(self):
        w = QWidget()
        UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        r0 = QHBoxLayout()
        self._ck_enabled = QCheckBox("Enable EA")
        self._ck_enabled.setChecked(self._enabled)
        self._ck_enabled.toggled.connect(
            lambda s: setattr(self, "_enabled", bool(s)) or self._emit_config()
        )
        r0.addWidget(self._ck_enabled)
        r0.addSpacing(12)

        r0.addWidget(QLabel("Epsilon:"))
        self._sp_eps = QDoubleSpinBox()
        self._sp_eps.setDecimals(8)
        self._sp_eps.setRange(1e-12, 1e-2)
        self._sp_eps.setSingleStep(1e-6)
        self._sp_eps.setValue(self._epsilon)
        self._sp_eps.valueChanged.connect(
            lambda v: setattr(self, "_epsilon", float(v))
        )
        r0.addWidget(self._sp_eps)
        r0.addStretch(1)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        btn_fit = UiKit.make_btn("Reset & Fit", role="primary")
        btn_fit.clicked.connect(self._on_reset_fit)
        r1.addWidget(btn_fit)

        btn_clear = UiKit.make_btn("Clear EA", role="danger")
        btn_clear.clicked.connect(self._on_clear)
        r1.addWidget(btn_clear)
        r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel("No EA computed. Add training segments, then Fit.")
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("Euclidean Alignment", panel, collapsed=False))
        return w

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        return {
            "enabled": bool(self._enabled),
            "epsilon": float(self._epsilon),
            "is_fitted": bool(self._is_fitted),
            "n_segments": len(self._fit_seg),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        if "enabled" in cfg:
            self._enabled = bool(cfg["enabled"])
        if "epsilon" in cfg:
            self._epsilon = float(cfg["epsilon"])
        if self._ck_enabled:
            self._ck_enabled.setChecked(self._enabled)
        if self._sp_eps:
            self._sp_eps.setValue(self._epsilon)
        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- actions ----------
    def _on_reset_fit(self):
        self._fit_seg.clear()
        self._whitening = None
        self._is_fitted = False
        self._n_ch = None
        self._set_status("Cleared. Accumulating training segments for EA fit.")

    def _on_clear(self):
        self._fit_seg.clear()
        self._whitening = None
        self._is_fitted = False
        self._n_ch = None
        self._set_status("EA cleared.")
        self.outputs["ea_matrix"].on_next(None)
        self.outputs["segment"].on_next(None)

    def _set_status(self, msg):
        if self._lbl:
            self._lbl.setText(msg)

    # ---------- EA computation ----------
    def _compute_ea(self):
        if len(self._fit_seg) < 2:
            self._set_status(f"Need >=2 segments for EA (have {len(self._fit_seg)}).")
            return False

        segs = self._fit_seg
        n_ch = segs[0].shape[0]
        self._n_ch = n_ch

        # Accumulate covariance matrices
        covs = []
        for seg in segs:
            X = seg - seg.mean(axis=1, keepdims=True)
            T = X.shape[1]
            if T < 2:
                continue
            C = (X @ X.T) / float(T - 1)
            tr = np.trace(C)
            if tr > 1e-12:
                C = C / tr
            covs.append(C)

        if len(covs) < 2:
            self._set_status("Not enough valid segments for EA.")
            return False

        # Mean covariance across all training trials
        A_mean = np.mean(covs, axis=0)

        # Eigendecomposition
        try:
            eigvals, eigvecs = np.linalg.eigh(A_mean)
        except np.linalg.LinAlgError:
            self._set_status("Eigendecomposition failed.")
            return False

        # Clamp eigenvalues for numerical stability
        eigvals = np.maximum(eigvals, self._epsilon)

        # Whitening matrix: W = E @ diag(1/sqrt(lambda)) @ E^T
        D_inv_sqrt = np.diag(1.0 / np.sqrt(eigvals))
        self._whitening = eigvecs @ D_inv_sqrt @ eigvecs.T

        self._is_fitted = True
        self.outputs["ea_matrix"].on_next(self._whitening.copy())
        self._set_status(
            f"EA fitted: {len(covs)} segments, {n_ch} channels. "
            f"Trace(A_mean)={np.trace(A_mean):.4f}"
        )
        return True

    def _apply_ea(self, seg):
        if self._whitening is None:
            return seg
        n_ch = seg.shape[0]
        if n_ch != self._whitening.shape[0]:
            self._set_status(
                f"Channel mismatch: EA matrix is {self._whitening.shape[0]}ch, "
                f"segment is {n_ch}ch."
            )
            return seg
        # X_aligned = W @ X
        return self._whitening @ seg

    # ---------- runtime ----------
    def execute(self, **kw):
        cfg = kw.get("config_in", None)
        if isinstance(cfg, dict) and cfg:
            self.import_config(cfg)

        seg = kw.get("segment", None)
        fs = kw.get("sfreq", None)
        ch = kw.get("ch_names", None)

        if seg is None:
            return {}

        seg_2d = _ensure_nchn(seg)
        if seg_2d is None or seg_2d.ndim != 2:
            return {}

        # If not fitted yet, accumulate this segment for fitting
        if not self._is_fitted:
            self._fit_seg.append(seg_2d.copy())
            n_accum = len(self._fit_seg)
            self._set_status(f"Accumulating: {n_accum} segments for EA fit.")
            # Pass through without alignment
            self.outputs["segment"].on_next(seg)
            self.outputs["sfreq"].on_next(fs)
            self.outputs["ch_names"].on_next(ch)
            # Auto-fit when we have enough segments (e.g. 20)
            if n_accum >= 20:
                self._compute_ea()
            return {}

        # Apply EA if enabled
        if self._enabled:
            aligned = self._apply_ea(seg_2d)
            self.outputs["segment"].on_next(aligned)
        else:
            self.outputs["segment"].on_next(seg)

        self.outputs["sfreq"].on_next(fs)
        self.outputs["ch_names"].on_next(ch)
        return {}
