# plugins/bandpower_features_plugin.py
# -*- coding: utf-8 -*-
"""
BandpowerFeatures — extrait des features de puissance par bande (Welch).

Entrées:
  - segment : ndarray 2D (n_ch, n_t) ou (n_t, n_ch)
  - sfreq   : float (Hz) optionnel mais recommandé
  - ch_names: list[str] optionnel

Sorties:
  - features         : 1D ndarray concaténée (par canal puis par bande)
  - features_matrix  : 2D ndarray (n_ch, n_bands)
  - features_dim     : int
  - band_labels      : list[str] (ex: ["delta","theta","alpha","beta","gamma"])

UI:
  - Section "Paramètres" pliable (fermée par défaut) sans zone grise résiduelle.
  - Bandes (texte), nperseg, overlap.
"""
from typing import List, Tuple, Optional
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QLabel, QLineEdit,
    QSpinBox, QDoubleSpinBox, QPushButton, QHBoxLayout,
    QSizePolicy, QLayout, QFrame
)

from core.node_base import BasePlugin

# ---------- Welch SciPy (si dispo) ----------
try:
    from scipy.signal import welch
    _HAVE_SCIPY = True
except Exception:
    _HAVE_SCIPY = False


# ---------- Utilitaires ----------
def _ensure_seg_2d(seg: Optional[np.ndarray]) -> Optional[np.ndarray]:
    if seg is None:
        return None
    arr = np.asarray(seg)
    if arr.ndim != 2:
        return None
    # On suppose que l'axe le plus long est le temps: (n_ch, n_t)
    return arr if arr.shape[0] < arr.shape[1] else arr.T


def _parse_bands(spec: str) -> List[Tuple[str, Tuple[float, float]]]:
    """
    spec: "delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45"
    -> [("delta",(1,4)), ...]
    """
    bands = []
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok or ":" not in tok or "-" not in tok:
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


def _welch_psd(x: np.ndarray, fs: float, nperseg: int, noverlap: int):
    """x: (n_t,), retourne (f, Pxx)"""
    if _HAVE_SCIPY:
        f, pxx = welch(x, fs=fs, nperseg=nperseg, noverlap=noverlap, detrend="constant")
        return f, pxx
    # Fallback sans SciPy: moyenne de periodogrammes fenêtrés
    n = int(x.size)
    nperseg = max(8, min(int(nperseg), n)) if n > 0 else nperseg
    step = nperseg - int(noverlap)
    if step <= 0:
        step = max(1, nperseg // 2)
    wins = []
    win = np.hanning(nperseg)
    norm = np.sum(win ** 2) * (fs if np.isfinite(fs) and fs > 0 else 1.0)
    for start in range(0, n - nperseg + 1, step):
        seg = x[start:start + nperseg]
        seg = seg - np.mean(seg)
        xf = np.fft.rfft(seg * win)
        pxx = (np.abs(xf) ** 2) / (norm if norm > 0 else 1.0)
        wins.append(pxx)
    if not wins:
        seg = x - np.mean(x)
        win = np.hanning(len(seg))
        xf = np.fft.rfft(seg * win)
        pxx = (np.abs(xf) ** 2) / (np.sum(win ** 2) * (fs if np.isfinite(fs) and fs > 0 else 1.0))
        wins = [pxx]
        nperseg = len(seg)
    pxx_mean = np.mean(np.stack(wins, axis=0), axis=0)
    f = np.fft.rfftfreq(nperseg, d=1.0 / (fs if np.isfinite(fs) and fs > 0 else 1.0))
    return f, pxx_mean


# ---------- Section pliable robuste (anti “cadre gris”) ----------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Forçage d'update des layouts parents pour éviter
    toute zone grise résiduelle.
    """
    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

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
        self.set_collapsed(True)  # fermé sans espace au démarrage

    def content_layout(self) -> QVBoxLayout:
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
        # One-shot pour laisser Qt recalculer tout l'arbre
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


# ---------- Plugin ----------
class BandpowerFeaturesPlugin(BasePlugin):
    help = {
        'summary': 'Extract per-band power features from EEG segments using Welch PSD estimation.',
        'inputs': {
            'segment': '2D float [channels x samples] — EEG data window or epoched array',
            'sfreq': 'float — sampling frequency in Hz (required)',
            'ch_names': 'list[str] — optional channel names (not used in computation, but accepted)',
        },
        'outputs': {
            'features': '1D float ndarray — concatenated band powers (flattened from features_matrix)',
            'features_matrix': '2D float ndarray [channels x bands] — per-channel band power values',
            'features_dim': 'int — total number of features (n_ch * n_bands)',
            'band_labels': 'list[str] — band names in order (e.g. ["delta","theta","alpha","beta","gamma"])',
            'status': 'str — status message',
        },
        'parameters': [
            {'name': 'bands', 'type': 'str', 'default': 'delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45',
             'desc': 'Band specification as comma-separated name:lo-hi pairs in Hz.'},
            {'name': 'nperseg', 'type': 'int', 'default': 256,
             'desc': 'Welch segment length (samples). Must be ≤ data length. Larger values give better frequency resolution.'},
            {'name': 'overlap', 'type': 'float', 'default': 0.5,
             'desc': 'Overlap ratio (0.0–0.9) between Welch segments. Higher overlap reduces variance.'},
        ],
        'gotchas': [
            'sfreq is required — the node outputs nothing if it is missing or ≤ 0.',
            'nperseg is clamped to the data length if the segment is shorter.',
            'Falls back to a plain FFT windowed periodogram if SciPy is not installed.',
            'Orientation is auto-detected: if rows > cols, the segment is transposed to (n_ch, n_t).',
            'The flat features vector is ordered as [ch0_band0, ch0_band1, ..., ch1_band0, ...].',
            'Low-frequency bands (e.g. delta < 1 Hz) require a sufficiently long segment.',
        ],
        'usage': 'Connect a windowed EEG segment and a sampling frequency. Outputs per-channel band power features for ML classification or regression.',
    }

    name = "BandpowerFeatures"
    language = "Python"
    category = "Processing Nodes"

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
        self.outputs["status"] = BehaviorSubject("")

        # UI state
        self._bands_spec = "delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45"
        self._nperseg = 256
        self._overlap = 0.5  # ratio 0..0.9

        # Widgets
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
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("Bandpower Features (Welch)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        # --- Section Paramètres (pliable, fermée par défaut) ---
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

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

        # bouton "Appliquer" (optionnel, recalcul auto de toute façon)
        row_btn = QHBoxLayout()
        btn_apply = QPushButton("Appliquer")
        btn_apply.clicked.connect(self._on_ui_changed)
        row_btn.addWidget(btn_apply)
        row_btn.addStretch(1)

        box = QWidget(); box_lay = QVBoxLayout(box)
        box_lay.setContentsMargins(0, 0, 0, 0)
        box_lay.setSpacing(6)
        box_lay.addLayout(form)
        box_lay.addLayout(row_btn)

        sec.content_layout().addWidget(box)
        root.addWidget(sec)

        # Statut (toujours visible)
        self._lbl_info = QLabel("Prêt.")
        self._lbl_info.setStyleSheet("color:#666;")
        root.addWidget(self._lbl_info)

        # Contraintes anti “cadre gris”
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        # Appliquer modifications en temps réel
        self._txt_bands.editingFinished.connect(self._on_ui_changed)
        self._spin_nperseg.valueChanged.connect(self._on_ui_changed)
        self._spin_overlap.valueChanged.connect(self._on_ui_changed)

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if self._lbl_info is not None:
            self._lbl_info.setText(msg)

    def _on_ui_changed(self, *args):
        if self._txt_bands is not None:
            self._bands_spec = self._txt_bands.text().strip() or self._bands_spec
        if self._spin_nperseg is not None:
            self._nperseg = int(self._spin_nperseg.value())
        if self._spin_overlap is not None:
            self._overlap = float(self._spin_overlap.value())
        # Le prochain execute utilisera ces valeurs

    # ------------- Coeur calcul -------------
    def _compute_bandpowers(self, seg: np.ndarray, fs: float, bands):
        """
        seg: (n_ch, n_t)
        bands: list[(name,(lo,hi))]
        retourne: matrix (n_ch, n_bands)
        """
        n_ch, n_t = seg.shape
        nperseg = min(max(8, self._nperseg), n_t) if n_t > 0 else self._nperseg
        noverlap = int(max(0.0, min(0.9, self._overlap)) * nperseg)

        out = np.zeros((n_ch, len(bands)), dtype=float)
        for ci in range(n_ch):
            x = seg[ci, :]
            f, pxx = _welch_psd(x, fs=fs, nperseg=nperseg, noverlap=noverlap)
            for bi, (name, (lo, hi)) in enumerate(bands):
                mask = (f >= lo) & (f < hi)
                out[ci, bi] = np.trapz(pxx[mask], f[mask]) if np.any(mask) else 0.0
        return out

    # ------------- Exécution -------------
    def execute(self, *args, **kwargs):
        # Compat: on accepte soit dict brut, soit BehaviorSubjects
        inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)

        def _v(x):
            try:
                return x.value
            except Exception:
                return x

        seg = _v(inps.get("segment"))
        fs = _v(inps.get("sfreq"))

        seg = _ensure_seg_2d(seg)
        if seg is None or seg.size == 0:
            self.outputs["features_matrix"].on_next(None)
            self.outputs["features"].on_next(None)
            self.outputs["features_dim"].on_next(0)
            self._set_status("Aucune donnée.")
            return {}

        try:
            fs = float(fs) if fs is not None else None
        except Exception:
            fs = None

        if fs is None or not np.isfinite(fs) or fs <= 0:
            self._set_status("sfreq manquant/invalide → calcul ignoré.")
            self.outputs["features_matrix"].on_next(None)
            self.outputs["features"].on_next(None)
            self.outputs["features_dim"].on_next(0)
            return {}

        bands = _parse_bands(self._bands_spec)
        if not bands:
            bands = [("delta",(1.0,4.0)),("theta",(4.0,8.0)),("alpha",(8.0,13.0)),("beta",(13.0,30.0)),("gamma",(30.0,45.0))]

        M = self._compute_bandpowers(seg, fs, bands)  # (n_ch, n_bands)
        feats = M.reshape(-1)  # concat ch×bands

        self.outputs["features_matrix"].on_next(M)
        self.outputs["features"].on_next(feats)
        self.outputs["features_dim"].on_next(int(feats.size))
        self.outputs["band_labels"].on_next([b[0] for b in bands])

        n_ch, n_b = M.shape
        self._set_status(f"OK — {n_ch} canaux × {n_b} bandes (fs={fs:.1f} Hz, nperseg={self._nperseg}, overlap={self._overlap:.2f}).")
        return {}
