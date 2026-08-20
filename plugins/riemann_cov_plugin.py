# plugins/riemann_cov_plugin.py
# -*- coding: utf-8 -*-
"""
RiemannCov — calcule la covariance SPD d'un segment EEG
→ Section Paramètres pliable (fermée par défaut, sans zone grise résiduelle)

Entrée
  - segment : ndarray 2D (n_ch, n_t) ou (n_t, n_ch)

Sortie
  - cov     : ndarray 2D (n_ch, n_ch) SPD

Paramètre
  - epsilon : régularisation diagonale (εI), ex: 1e-8..1e-2
"""
from typing import Optional
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QDoubleSpinBox,
    QSizePolicy, QLayout, QFrame, QPushButton
)
from PyQt5.QtCore import QTimer

from core.node_base import BasePlugin


# ---------------------- Section pliable (anti “cadre gris”) ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Reflow forcé jusqu'au parent (pas de zone grise).
    """
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # fermé au démarrage
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
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(10, 8, 10, 8)
        self._lay.setSpacing(6)
        self._lay.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.set_collapsed(True)

    def content_layout(self):
        return self._lay

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)
        self._apply(collapsed)
        self._update_title()
        self._reflow()

    def _on_toggled(self, checked: bool):
        self._apply(collapsed=not checked)
        self._update_title()
        self._reflow()

    def _apply(self, collapsed: bool):
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

    def _update_title(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._title[2:] if self._title[:2] in ("▼ ", "▶ ") else self._title
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry(); self.updateGeometry()
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._bubble_adjust)

    def _bubble_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout(): w.layout().activate()
                w.adjustSize(); w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


# ------------------------------ Plugin ------------------------------
def _ensure_seg_2d(seg):
    if seg is None:
        return None
    arr = np.asarray(seg)
    if arr.ndim != 2:
        return None
    # On suppose que l'axe le plus long est le temps
    return arr if arr.shape[0] < arr.shape[1] else arr.T  # (n_ch, n_t)


class RiemannCovPlugin(BasePlugin):
    help = {
        'summary': "Compute the SPD covariance matrix from a single EEG segment.",
        'inputs': {
            'segment': '2D float [channels x samples] or [samples x channels]',
        },
        'outputs': {
            'cov': '2D float SPD matrix [channels x channels] — regularized sample covariance',
        },
        'parameters': [
            {'name': 'epsilon', 'type': 'float', 'default': 1e-6,
             'desc': 'Diagonal regularization (εI). Prevents singularity when n_samples ≈ n_channels. Range: 1e-12 to 1e-2.'}
        ],
        'gotchas': [
            "Segment must be 2D; a 1D or 3D input will be rejected (outputs None).",
            "Orientation is auto-detected: if rows > cols, the array is transposed to (n_ch, n_t).",
            "ε is added to the diagonal of the covariance; too large a value biases the result toward identity.",
            "NaN/Inf values in the segment are replaced with zero before computing covariance.",
            "The covariance is computed as (X @ X.T) / (n_t - 1) with mean-centering per channel.",
        ],
        'usage': 'Connect a 2D EEG segment (channels × samples). Outputs the regularized SPD covariance matrix for downstream Riemannian geometry processing.',
    }

    name = "RiemannCov"
    language = "Python"
    category = "ML"

    def setup(self):
        self.inputs["segment"] = BehaviorSubject(None)
        self.outputs["cov"] = BehaviorSubject(None)

        self._eps = 1e-6
        self._widget = None
        self._spin_eps = None
        self._lbl_info = None

    # ---------------- UI ----------------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("RiemannCov — covariance SPD")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        # Section Paramètres pliable
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        form = QFormLayout()
        self._spin_eps = QDoubleSpinBox()
        self._spin_eps.setDecimals(8)
        self._spin_eps.setRange(1e-12, 1e-2)
        self._spin_eps.setSingleStep(1e-6)
        self._spin_eps.setValue(self._eps)
        self._spin_eps.valueChanged.connect(lambda v: setattr(self, "_eps", float(v)))
        form.addRow("ε (regularization)", self._spin_eps)

        # Mettre le form dans le contenu pliable
        sec.content_layout().addLayout(form)

        # Info (toujours visible)
        self._lbl_info = QLabel("Aucun segment — en attente…")
        self._lbl_info.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl_info)

        # Contraintes anti “cadre gris”
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        self._widget = w
        return w

    # ---------------- Core ----------------
    def _set_info(self, msg: str):
        if self._lbl_info is not None:
            self._lbl_info.setText(msg)

    def execute(self, inputs):
        seg = _ensure_seg_2d(inputs.get("segment"))
        if seg is None:
            self._set_info("Aucun segment valide (attendu 2D).")
            self.outputs["cov"].on_next(None)
            return

        n_ch, n_t = seg.shape
        if n_t < 2:
            self._set_info(f"Segment trop court (n_t={n_t}).")
            self.outputs["cov"].on_next(None)
            return

        X = seg.astype(float, copy=False)
        X = X - X.mean(axis=1, keepdims=True)

        # (X Xᵀ)/(T-1) + εI  — robuste aux NaN/Inf
        if not np.isfinite(X).all():
            X = np.nan_to_num(X, copy=False)

        denom = max(1, (n_t - 1))
        cov = (X @ X.T) / float(denom)
        cov.flat[::n_ch + 1] += float(self._eps)

        self.outputs["cov"].on_next(cov)
        self._set_info(f"{n_ch} ch × {n_t} échant. → cov {n_ch}×{n_ch} (ε={self._eps:g})")
