# plugins/bci_tsfbcsp_features_node.py
# -*- coding: utf-8 -*-
"""
BCI_TSFBCSPFeatures — TS-FBCSP Feature Extraction Node.

Implements the TS-FBCSP algorithm described in Chapter 4, Section 4.7 of the thesis:
  1. Filter-bank spectral decomposition (9 overlapping sub-bands, 8-30 Hz)
  2. Per-band OAS shrinkage covariance estimation
  3. Per-band Riemannian mean computation (fit mode)
  4. Tangent space projection at the Riemannian mean
  5. Feature concatenation across all sub-bands

Inputs:
  - segment   : ndarray (n_samples x n_channels) — preprocessed (EA-aligned) EEG
  - sfreq     : float
  - ch_names  : list[str] (optional)
  - y_idx     : int (optional, class label for fit mode)

Outputs:
  - features     : 1D ndarray — concatenated tangent space features
  - features_dim : int — total feature dimensionality
  - band_labels  : list[str] — labels for each sub-band
  - covariances  : list[ndarray] — per-band covariance matrices (for inspection)

Internal state (fit mode):
  - Per-band Riemannian means M^(b) stored for transform mode.
"""
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    from sklearn.preprocessing import StandardScaler
    SK_OK = True
except Exception:
    SK_OK = False


# ======================================================================
# Filter-bank sub-band definitions (Table 4.2 of the thesis)
# 9 overlapping bands covering 8-30 Hz
# ======================================================================
DEFAULT_FILTER_BANK = [
    (8.0, 12.0),
    (12.0, 16.0),
    (16.0, 20.0),
    (20.0, 24.0),
    (24.0, 28.0),
    (8.0, 16.0),
    (12.0, 20.0),
    (16.0, 24.0),
    (20.0, 30.0),
]


def _ensure_nchn(seg):
    """Ensure shape (n_channels, n_samples)."""
    arr = np.asarray(seg, float)
    if arr.ndim == 1:
        return arr[:, None]
    if arr.shape[0] > arr.shape[1]:
        return arr.T
    return arr


def _oas_shrinkage(X, epsilon=1e-8):
    """
    Ledoit-Wolf / OAS shrinkage covariance estimator.
    X: (n_channels, n_samples)
    Returns: regularized covariance matrix (n_channels, n_channels)
    """
    n_ch, n_samp = X.shape
    if n_samp < 2:
        cov = np.eye(n_ch) * epsilon
        return cov

    X_mean = X - X.mean(axis=1, keepdims=True)
    S_emp = (X_mean @ X_mean.T) / float(n_samp)

    # Trace-normalized target
    tr = np.trace(S_emp)
    F = (tr / n_ch) * np.eye(n_ch)

    # OAS shrinkage intensity
    num = np.sum(S_emp ** 2) + (np.trace(S_emp) ** 2) / n_samp
    denom = (n_samp + 1) * (np.sum(S_emp ** 2) - (np.trace(S_emp) ** 2) / n_ch)
    rho = max(0.0, min(1.0, num / max(denom, 1e-30)))

    cov = rho * F + (1.0 - rho) * S_emp
    cov.flat[::n_ch + 1] += epsilon
    return cov


def _apply_filter_bands(seg, sfreq, bands):
    """
    Apply bandpass filter for each sub-band.
    seg: (n_channels, n_samples)
    Returns: list of filtered segments, one per band.
    """
    try:
        from scipy.signal import butter, sosfiltfilt
        has_scipy = True
    except Exception:
        has_scipy = False

    filtered = []
    n_ch, n_samp = seg.shape
    nyq = 0.5 * sfreq

    for f_lo, f_hi in bands:
        if not has_scipy:
            filtered.append(seg.copy())
            continue
        lo = max(0.001, f_lo / nyq)
        hi = min(0.999, f_hi / nyq)
        if hi <= lo:
            filtered.append(seg.copy())
            continue
        try:
            sos = butter(4, [lo, hi], btype='band', output='sos')
            band_seg = sosfiltfilt(sos, seg, axis=1)
            filtered.append(band_seg)
        except Exception:
            filtered.append(seg.copy())

    return filtered


def _riemannian_mean(covs, max_iter=50, tol=1e-6):
    """
    Compute the Riemannian (Frechet) mean of SPD matrices via iterative
    gradient descent.

    covs: list of (n_ch, n_ch) SPD matrices
    Returns: M — the Riemannian mean matrix
    """
    if len(covs) == 0:
        return None
    if len(covs) == 1:
        return covs[0].copy()

    # Initialize with arithmetic mean
    M = np.mean(covs, axis=0).copy()
    n_ch = M.shape[0]

    for iteration in range(max_iter):
        # Compute matrix square root inverse of M
        try:
            eigvals, eigvecs = np.linalg.eigh(M)
            eigvals = np.maximum(eigvals, 1e-12)
            M_inv_sqrt = eigvecs @ np.diag(1.0 / np.sqrt(eigvals)) @ eigvecs.T
        except np.linalg.LinAlgError:
            break

        # Gradient: sum of log_M(C_i)
        grad = np.zeros_like(M)
        for C in covs:
            # Transport C to tangent space at M
            try:
                C_eigvals, C_eigvecs = np.linalg.eigh(C)
                C_eigvals = np.maximum(C_eigvals, 1e-12)
                C_sqrt = C_eigvecs @ np.diag(np.sqrt(C_eigvals)) @ C_eigvecs.T
                C_inv_sqrt = C_eigvecs @ np.diag(1.0 / np.sqrt(C_eigvals)) @ C_eigvecs.T
                log_MC = M_inv_sqrt @ C_sqrt @ M_inv_sqrt
                # Logarithm
                log_eigvals, log_eigvecs = np.linalg.eigh(log_MC)
                log_MC = log_eigvecs @ np.diag(np.log(np.maximum(log_eigvals, 1e-12))) @ log_eigvecs.T
                grad += log_MC
            except np.linalg.LinAlgError:
                continue

        grad /= len(covs)

        # Check convergence
        grad_norm = np.linalg.norm(grad)
        if grad_norm < tol:
            break

        # Update M
        try:
            grad_eigvals, grad_eigvecs = np.linalg.eigh(grad)
            grad_exp = grad_eigvecs @ np.diag(np.exp(grad_eigvals)) @ grad_eigvecs.T
            M = M_inv_sqrt @ grad_exp @ M_inv_sqrt
        except np.linalg.LinAlgError:
            break

        # Ensure symmetry
        M = 0.5 * (M + M.T)

    return M


def _log_map(M, C):
    """
    Compute the logarithm map log_M(C) — projects C onto tangent space at M.
    Returns: symmetric matrix of same shape.
    """
    try:
        M_eigvals, M_eigvecs = np.linalg.eigh(M)
        M_eigvals = np.maximum(M_eigvals, 1e-12)
        M_inv_sqrt = M_eigvecs @ np.diag(1.0 / np.sqrt(M_eigvals)) @ M_eigvecs.T

        C_eigvals, C_eigvecs = np.linalg.eigh(C)
        C_eigvals = np.maximum(C_eigvals, 1e-12)
        C_sqrt = C_eigvecs @ np.diag(np.sqrt(C_eigvals)) @ C_eigvecs.T

        log_MC = M_inv_sqrt @ C_sqrt @ M_inv_sqrt
        log_eigvals, log_eigvecs = np.linalg.eigh(log_MC)
        log_MC = log_eigvecs @ np.diag(np.log(np.maximum(log_eigvals, 1e-12))) @ log_eigvecs.T

        return log_MC
    except np.linalg.LinAlgError:
        n = M.shape[0]
        return np.zeros((n, n))


def _vectorize_upper(sym_mat):
    """
    Vectorize a symmetric matrix using upper-triangular entries.
    Off-diagonal elements are scaled by sqrt(2) to preserve Frobenius inner product.
    """
    n = sym_mat.shape[0]
    idx = np.triu_indices(n)
    vec = sym_mat[idx].copy()
    # Scale off-diagonal by sqrt(2)
    diag_mask = idx[0] == idx[1]
    vec[~diag_mask] *= np.sqrt(2.0)
    return vec


class BCITSFBCSPFeatures(BasePlugin):
    help = {
        'gotchas': [
            "In fit mode, connect y_idx for supervised Riemannian mean computation.",
            "Requires pyriemann for full Riemannian operations (fallback: pure numpy).",
            "Feature dimensionality = C*(C+1)/2 * n_bands (e.g., 253*9=2277 for 22ch)."
        ],
        'inputs': {
            'segment': '2D float [samples x channels] (EA-aligned EEG)',
            'sfreq': 'float',
            'ch_names': 'list[str]',
            'y_idx': 'int (class label, optional)',
        },
        'outputs': {
            'features': '1D float array (concatenated tangent vectors)',
            'features_dim': 'int',
            'band_labels': 'list[str]',
            'covariances': 'list[ndarray] (per-band covariance matrices)',
            'config_out': 'dict',
        },
        'parameters': [
            {'name': 'mode', 'type': 'str', 'default': 'transform',
             'desc': 'fit: compute Riemannian means; transform: project to tangent space'},
            {'name': 'cov_estimator', 'type': 'str', 'default': 'OAS',
             'desc': 'Covariance estimator: OAS, LW (Ledoit-Wolf), or empirical'},
        ],
        'summary': 'TS-FBCSP: Filter-bank tangent space features with OAS covariance.',
        'usage': 'Connect preprocessed EA-aligned EEG. Set mode=fit for training, '
                 'mode=transform for inference.'
    }

    name = "BCI_TSFBCSPFeatures"
    language = "Python"
    category = "ML"

    def setup(self):
        self.inputs["segment"]   = BehaviorSubject(None)
        self.inputs["sfreq"]     = BehaviorSubject(None)
        self.inputs["ch_names"]  = BehaviorSubject(None)
        self.inputs["y_idx"]     = BehaviorSubject(None)
        self.inputs["config_in"] = BehaviorSubject(None)

        self.outputs["features"]     = BehaviorSubject(None)
        self.outputs["features_dim"] = BehaviorSubject(None)
        self.outputs["band_labels"]  = BehaviorSubject(None)
        self.outputs["covariances"]  = BehaviorSubject(None)
        self.outputs["config_out"]   = BehaviorSubject(None)

        # Parameters
        self._mode = "transform"  # "fit" | "transform"
        self._cov_estimator = "OAS"  # "OAS" | "LW" | "empirical"
        self._filter_bank = list(DEFAULT_FILTER_BANK)
        self._n_bands = len(self._filter_bank)
        self._epsilon = 1e-8

        # Fit state
        self._riemannian_means = None  # list of (n_ch, n_ch) per band
        self._is_fitted = False
        self._n_ch = None
        self._fit_covs_per_band = [[] for _ in self._filter_bank]
        self._fit_labels = []

        # Scalers per band (for StandardScaler)
        self._scaler = None

        # UI refs
        self._lbl = None
        self._cmb_mode = None
        self._cmb_cov = None
        self._lbl_dim = None

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

        # Mode
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Mode:"))
        self._cmb_mode = QComboBox()
        self._cmb_mode.addItems(["fit", "transform"])
        self._cmb_mode.setCurrentText(self._mode)
        self._cmb_mode.currentTextChanged.connect(
            lambda s: setattr(self, "_mode", s) or self._emit_config()
        )
        r0.addWidget(self._cmb_mode)
        r0.addSpacing(12)

        r0.addWidget(QLabel("Cov estimator:"))
        self._cmb_cov = QComboBox()
        self._cmb_cov.addItems(["OAS", "LW", "empirical"])
        self._cmb_cov.setCurrentText(self._cov_estimator)
        self._cmb_cov.currentTextChanged.connect(
            lambda s: setattr(self, "_cov_estimator", s)
        )
        r0.addWidget(self._cmb_cov)
        r0.addStretch(1)
        v.addLayout(r0)

        # Actions
        r1 = QHBoxLayout()
        btn_fit = UiKit.make_btn("Fit Riemannian Means", role="primary")
        btn_fit.clicked.connect(self._on_fit)
        r1.addWidget(btn_fit)

        btn_clear = UiKit.make_btn("Clear Fit", role="danger")
        btn_clear.clicked.connect(self._on_clear_fit)
        r1.addWidget(btn_clear)
        r1.addStretch(1)
        v.addLayout(r1)

        # Info
        self._lbl_dim = QLabel(f"Bands: {self._n_bands} | Feature dim: (compute after fit)")
        v.addWidget(self._lbl_dim)

        self._lbl = QLabel(
            "TS-FBCSP ready. Mode=transform (no fit data). "
            "Set mode=fit and connect training segments."
        )
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("TS-FBCSP Features", panel, collapsed=False))
        return w

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        return {
            "mode": self._mode,
            "cov_estimator": self._cov_estimator,
            "n_bands": self._n_bands,
            "filter_bank": [(f0, f1) for f0, f1 in self._filter_bank],
            "is_fitted": self._is_fitted,
            "n_ch": self._n_ch,
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        if "mode" in cfg:
            self._mode = str(cfg["mode"])
        if "cov_estimator" in cfg:
            self._cov_estimator = str(cfg["cov_estimator"])
        if self._cmb_mode:
            self._cmb_mode.setCurrentText(self._mode)
        if self._cmb_cov:
            self._cmb_cov.setCurrentText(self._cov_estimator)
        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- actions ----------
    def _on_fit(self):
        if len(self._fit_labels) < 2:
            self._set_status("Need >=2 labeled segments for fit.")
            return

        n_ch = self._n_ch
        if n_ch is None:
            self._set_status("No segments received yet.")
            return

        # Compute Riemannian mean per band
        means = []
        for b_idx in range(self._n_bands):
            covs = self._fit_covs_per_band[b_idx]
            if len(covs) < 2:
                self._set_status(f"Band {b_idx}: only {len(covs)} covs (need >=2).")
                means.append(np.eye(n_ch))
                continue
            M = _riemannian_mean(covs)
            if M is None:
                M = np.eye(n_ch)
            means.append(M)

        self._riemannian_means = means
        self._is_fitted = True

        # Fit StandardScaler on training features
        if SK_OK and len(self._fit_labels) > 0:
            train_feats = []
            for trial_idx in range(len(self._fit_labels)):
                feat_vec = self._extract_features_per_trial(trial_idx)
                if feat_vec is not None:
                    train_feats.append(feat_vec)
            if len(train_feats) > 1:
                train_X = np.stack(train_feats, axis=0)
                self._scaler = StandardScaler()
                self._scaler.fit(train_X)

        feat_dim = n_ch * (n_ch + 1) // 2 * self._n_bands
        self._set_status(
            f"Fitted: {len(self._fit_labels)} trials, {self._n_bands} bands, "
            f"feat_dim={feat_dim}"
        )
        self._lbl_dim.setText(
            f"Bands: {self._n_bands} | Channels: {n_ch} | Feature dim: {feat_dim}"
        )
        self._emit_config()

    def _on_clear_fit(self):
        self._fit_covs_per_band = [[] for _ in self._filter_bank]
        self._fit_labels = []
        self._riemannian_means = None
        self._is_fitted = False
        self._scaler = None
        self._n_ch = None
        self._set_status("Fit state cleared.")
        self._lbl_dim.setText(
            f"Bands: {self._n_bands} | Feature dim: (compute after fit)"
        )

    def _set_status(self, msg):
        if self._lbl:
            self._lbl.setText(msg)

    # ---------- feature extraction helpers ----------
    def _extract_covs(self, seg_2d, sfreq):
        """Extract per-band covariance matrices from a single segment."""
        filtered_segs = _apply_filter_bands(seg_2d, sfreq, self._filter_bank)
        covs = []
        for band_seg in filtered_segs:
            if self._cov_estimator == "OAS":
                C = _oas_shrinkage(band_seg, self._epsilon)
            elif self._cov_estimator == "LW":
                C = self._lw_shrinkage(band_seg)
            else:
                C = self._empirical_cov(band_seg)
            covs.append(C)
        return covs

    def _lw_shrinkage(self, X):
        """Ledoit-Wolf shrinkage covariance (fallback using OAS)."""
        return _oas_shrinkage(X, self._epsilon)

    def _empirical_cov(self, X):
        """Empirical (sample) covariance with diagonal regularization."""
        n_ch, n_samp = X.shape
        X_centered = X - X.mean(axis=1, keepdims=True)
        C = (X_centered @ X_centered.T) / max(1, n_samp - 1)
        C.flat[::n_ch + 1] += self._epsilon
        return C

    def _extract_features_per_trial(self, trial_idx):
        """Extract concatenated features for a single trial (from fit cache)."""
        if self._riemannian_means is None:
            return None
        n_ch = self._n_ch
        feat_parts = []
        for b_idx in range(self._n_bands):
            covs = self._fit_covs_per_band[b_idx]
            if trial_idx >= len(covs):
                feat_parts.append(np.zeros(n_ch * (n_ch + 1) // 2))
                continue
            C = covs[trial_idx]
            M = self._riemannian_means[b_idx]
            log_MC = _log_map(M, C)
            vec = _vectorize_upper(log_MC)
            feat_parts.append(vec)
        return np.concatenate(feat_parts)

    # ---------- runtime ----------
    def execute(self, **kw):
        cfg = kw.get("config_in", None)
        if isinstance(cfg, dict) and cfg:
            self.import_config(cfg)

        seg = kw.get("segment", None)
        fs = kw.get("sfreq", None)
        ch = kw.get("ch_names", None)
        y_idx = kw.get("y_idx", None)

        if seg is None or fs is None:
            return {}

        fs = float(fs)
        seg_2d = _ensure_nchn(seg)
        if seg_2d is None or seg_2d.ndim != 2:
            return {}

        n_ch, n_samp = seg_2d.shape
        self._n_ch = n_ch

        # Extract per-band covariances
        covs = self._extract_covs(seg_2d, fs)

        if self._mode == "fit":
            # Accumulate for Riemannian mean computation
            for b_idx in range(self._n_bands):
                self._fit_covs_per_band[b_idx].append(covs[b_idx])
            if y_idx is not None:
                try:
                    self._fit_labels.append(int(y_idx))
                except Exception:
                    self._fit_labels.append(0)
            self._set_status(
                f"Fit mode: {len(self._fit_labels)} trials accumulated. "
                f"Press 'Fit Riemannian Means' when ready."
            )
            # Pass covariances for inspection
            self.outputs["covariances"].on_next(covs)
            self.outputs["features"].on_next(None)
            return {}

        # Transform mode
        if not self._is_fitted:
            self._set_status("Not fitted. Switch to fit mode and fit first.")
            self.outputs["features"].on_next(None)
            return {}

        feat_parts = []
        for b_idx in range(self._n_bands):
            M = self._riemannian_means[b_idx]
            C = covs[b_idx]
            log_MC = _log_map(M, C)
            vec = _vectorize_upper(log_MC)
            feat_parts.append(vec)

        feat = np.concatenate(feat_parts)

        # Apply StandardScaler if fitted
        if self._scaler is not None:
            try:
                feat = self._scaler.transform(feat.reshape(1, -1))[0]
            except Exception:
                pass

        feat_dim = feat.shape[0]

        band_labels = [f"band_{i+1}_{b[0]:.0f}-{b[1]:.0f}Hz"
                       for i, b in enumerate(self._filter_bank)]

        self.outputs["features"].on_next(feat)
        self.outputs["features_dim"].on_next(feat_dim)
        self.outputs["band_labels"].on_next(band_labels)
        self.outputs["covariances"].on_next(covs)

        self._set_status(
            f"TS-FBCSP: dim={feat_dim} | {self._n_bands} bands | {n_ch}ch"
        )
        return {}
