# plugins/psd_welch_plugin.py
# -*- coding: utf-8 -*-
"""
PSDWelchPlugin
- Calcule la densité spectrale de puissance (PSD) par méthode de Welch.
- Entrées *essentielles* uniquement :
    • raw            : mne.io.Raw | mne.Epochs (on prend les données concaténées si Epochs)
    • OU segment     : np.ndarray (n_ch, n_samples)  + sfreq: float (Hz)
    • (optionnel) ch_names : list[str] (si chemin "segment")
- Tous les autres réglages sont dans l’UI (pliable) + config (export/import).

Sorties :
    • freqs     : np.ndarray (n_freqs,)
    • psd       : np.ndarray (n_ch, n_freqs)   [float32]
    • ch_names  : list[str]
    • info      : dict (paramètres effectifs, n_ch, nyquist, etc.)
    • config_out: dict (pour ConfigNode)

Robustesses intégrées :
    • Clamp automatique de fmax à la Nyquist (sfreq/2 - epsilon)
    • Ajuste n_per_seg si trop long vs la longueur du signal disponible
    • Anti-“silence” : si la bande fmin–fmax vide, essaie une plage valide
    • Décimation graphique (max_points) pour éviter des tracés trop lourds
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSpinBox,
    QCheckBox, QComboBox, QLayout, QSizePolicy
)

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import mne
    from mne.time_frequency import psd_array_welch
    HAVE_MNE = True
except Exception as _e:
    HAVE_MNE = False
    _MNE_ERR = str(_e)


class PSDWelchPlugin(BasePlugin):
    name = "PSDWelch"
    language = "Python"
    category = "Analysis"
    supports_collapse = True

    # -------------------- lifecycle --------------------
    def setup(self):
        # Entrées essentielles
        self.inputs["raw"] = BehaviorSubject(None)        # MNE Raw/Epochs
        self.inputs["segment"] = BehaviorSubject(None)    # np.ndarray (n_ch, n_samples)
        self.inputs["sfreq"] = BehaviorSubject(None)      # float (Hz) — requis si "segment" utilisé
        self.inputs["ch_names"] = BehaviorSubject(None)   # list[str] optionnelle (segment)

        # Sorties
        self.outputs["freqs"] = BehaviorSubject(None)
        self.outputs["psd"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["info"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # UI params (configurables)
        self._fmin = 0.5
        self._fmax = 45.0
        self._seglen_s = 2.0
        self._overlap_s = 1.0
        self._average = "mean"           # 'mean' | 'median'
        self._eeg_only = True            # chemin "raw" uniquement
        self._max_points = 2048          # décimation pour l’affichage

        # cache pour éviter recalcul identique
        self._last_signature: Optional[Tuple] = None

        # refs UI
        self._lbl = None

    # -------------------- config I/O --------------------
    def export_config(self) -> dict:
        return {
            "fmin": float(self._fmin),
            "fmax": float(self._fmax),
            "seglen_s": float(self._seglen_s),
            "overlap_s": float(self._overlap_s),
            "average": str(self._average),
            "eeg_only": bool(self._eeg_only),
            "max_points": int(self._max_points),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return

        def get_num(k, cur, typ=float, mn=None, mx=None):
            v = cfg.get(k, cur)
            try:
                x = typ(v)
                if mn is not None: x = max(mn, x)
                if mx is not None: x = min(mx, x)
                return x
            except Exception:
                return cur

        def get_str(k, cur, allowed=None):
            v = cfg.get(k, cur)
            s = str(v)
            if allowed and s not in allowed:
                return cur
            return s

        def get_bool(k, cur):
            try:
                return bool(cfg.get(k, cur))
            except Exception:
                return cur

        self._fmin = get_num("fmin", self._fmin, float, 0.0, 5_000.0)
        self._fmax = get_num("fmax", self._fmax, float, 0.05, 10_000.0)
        self._seglen_s = get_num("seglen_s", self._seglen_s, float, 0.1, 60.0)
        self._overlap_s = get_num("overlap_s", self._overlap_s, float, 0.0, 59.9)
        self._average = get_str("average", self._average, allowed=["mean", "median"])
        self._eeg_only = get_bool("eeg_only", self._eeg_only)
        self._max_points = get_num("max_points", self._max_points, int, 128, 100_000)

        # pousser l’état vers le viewer/config
        self._emit_config()
        # recalcul léger
        QTimer.singleShot(0, lambda: self.execute({}))

    def config_hints(self) -> dict:
        return {
            "fields": {
                "fmin": {"type": "float", "min": 0.0, "max": 5000.0, "step": 0.5, "label": "fmin (Hz)"},
                "fmax": {"type": "float", "min": 0.05, "max": 10000.0, "step": 0.5, "label": "fmax (Hz)"},
                "seglen_s": {"type": "float", "min": 0.1, "max": 60.0, "step": 0.1, "label": "Fenêtre (s)"},
                "overlap_s": {"type": "float", "min": 0.0, "max": 59.9, "step": 0.1, "label": "Recouvrement (s)"},
                "average": {"type": "enum", "enum": ["mean", "median"], "label": "Average"},
                "eeg_only": {"type": "bool", "label": "EEG only (Raw)"},
                "max_points": {"type": "int", "min": 128, "max": 100000, "step": 64, "label": "Décimation max points"},
            },
            "_order": ["fmin", "fmax", "seglen_s", "overlap_s", "average", "eeg_only", "max_points"],
        }

    # -------------------- UI --------------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        UiKit.apply_node_style(w)
        outer = QVBoxLayout(w)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(8)

        # ligne 1 : fmin / fmax
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("fmin (Hz):"))
        sp_fmin = QDoubleSpinBox()
        sp_fmin.setRange(0.0, 10000.0)
        sp_fmin.setSingleStep(0.5)
        sp_fmin.setValue(self._fmin)
        sp_fmin.valueChanged.connect(lambda v: self._on_num("fmin", float(v)))
        r1.addWidget(sp_fmin)

        r1.addWidget(QLabel("fmax (Hz):"))
        sp_fmax = QDoubleSpinBox()
        sp_fmax.setRange(0.05, 10000.0)
        sp_fmax.setSingleStep(0.5)
        sp_fmax.setValue(self._fmax)
        sp_fmax.valueChanged.connect(lambda v: self._on_num("fmax", float(v)))
        r1.addWidget(sp_fmax)
        r1.addStretch(1)
        pv.addLayout(r1)

        # ligne 2 : fenetre / recouvrement
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Fenêtre (s):"))
        sp_win = QDoubleSpinBox()
        sp_win.setRange(0.1, 60.0)
        sp_win.setSingleStep(0.1)
        sp_win.setValue(self._seglen_s)
        sp_win.valueChanged.connect(lambda v: self._on_num("seglen_s", float(v)))
        r2.addWidget(sp_win)

        r2.addWidget(QLabel("Recouvrement (s):"))
        sp_ov = QDoubleSpinBox()
        sp_ov.setRange(0.0, 59.9)
        sp_ov.setSingleStep(0.1)
        sp_ov.setValue(self._overlap_s)
        sp_ov.valueChanged.connect(lambda v: self._on_num("overlap_s", float(v)))
        r2.addWidget(sp_ov)
        r2.addStretch(1)
        pv.addLayout(r2)

        # ligne 3 : average / eeg_only / max_points
        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Average:"))
        cb_avg = QComboBox()
        cb_avg.addItems(["mean", "median"])
        cb_avg.setCurrentText(self._average)
        cb_avg.currentTextChanged.connect(lambda t: self._on_str("average", t))
        r3.addWidget(cb_avg)

        chk_eeg = QCheckBox("EEG only (Raw)")
        chk_eeg.setChecked(self._eeg_only)
        chk_eeg.stateChanged.connect(lambda s: self._on_bool("eeg_only", bool(s == Qt.Checked)))
        r3.addWidget(chk_eeg)

        r3.addWidget(QLabel("max_points:"))
        sp_mp = QSpinBox()
        sp_mp.setRange(128, 100000)
        sp_mp.setSingleStep(64)
        sp_mp.setValue(self._max_points)
        sp_mp.valueChanged.connect(lambda v: self._on_num("max_points", int(v)))
        r3.addWidget(sp_mp)

        r3.addStretch(1)
        pv.addLayout(r3)

        # statut
        self._lbl = QLabel("Prêt (attend des données)")
        pv.addWidget(self._lbl)

        outer.addWidget(CollapsibleSection("Paramètres PSD (Welch)", panel, collapsed=True))
        return w

    def _on_num(self, key: str, val: float):
        if key == "fmin": self._fmin = float(val)
        elif key == "fmax": self._fmax = float(val)
        elif key == "seglen_s": self._seglen_s = float(val)
        elif key == "overlap_s": self._overlap_s = float(val)
        elif key == "max_points": self._max_points = int(val)
        self._emit_config()
        QTimer.singleShot(0, lambda: self.execute({}))

    def _on_str(self, key: str, val: str):
        if key == "average" and val in ("mean", "median"):
            self._average = val
        self._emit_config()
        QTimer.singleShot(0, lambda: self.execute({}))

    def _on_bool(self, key: str, val: bool):
        if key == "eeg_only":
            self._eeg_only = bool(val)
        self._emit_config()
        QTimer.singleShot(0, lambda: self.execute({}))

    # -------------------- helpers --------------------
    def _seg_signature(self, arr: Optional[np.ndarray], sf: Optional[float], names: Optional[List[str]]) -> Tuple:
        if arr is None or not isinstance(arr, np.ndarray):
            return (0, 0, 0.0, 0)
        n_ch = int(arr.shape[0]) if arr.ndim >= 1 else 0
        n_samp = int(arr.shape[1]) if arr.ndim >= 2 else 0
        chk = int(np.sum(arr.astype(np.float64)) % 1_000_003) if n_ch and n_samp else 0
        n_nm = len(names) if isinstance(names, (list, tuple)) else 0
        return (n_ch, n_samp, float(sf or 0.0), (chk ^ n_nm))

    def _emit_none(self, msg: str = None):
        if msg and self._lbl:
            self._lbl.setText(msg)
        self.outputs["freqs"].on_next(None)
        self.outputs["psd"].on_next(None)
        self.outputs["ch_names"].on_next(None)
        self.outputs["info"].on_next({"note": msg or "none"})

    # -------------------- execute --------------------
    def execute(self, in_data=None, **kwargs):
        # unifier l’API (tolérante)
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        raw = in_data.get("raw", None)
        seg = in_data.get("segment", None)
        sf = in_data.get("sfreq", None)
        ch_names_in = in_data.get("ch_names", None)

        # Choix du chemin
        if raw is not None:
            return self._run_from_raw(raw)
        elif seg is not None and isinstance(sf, (int, float)):
            return self._run_from_segment(seg, float(sf), ch_names_in)
        else:
            # Pas de données, on n’émet rien (mais pas d’erreur)
            return {}

    # -------------------- compute (Raw) --------------------
    def _run_from_raw(self, raw):
        if not HAVE_MNE:
            self._emit_none(f"Install mne (err: {_MNE_ERR})")
            return {}

        # Prépare picks, sfreq, noms
        try:
            sfreq = float(raw.info.get("sfreq", 0.0))
            if sfreq <= 0:
                self._emit_none("sfreq invalide")
                return {}
        except Exception:
            self._emit_none("sfreq invalide")
            return {}

        if self._eeg_only:
            try:
                picks = mne.pick_types(raw.info, eeg=True, meg=False, eog=False, ecg=False, stim=False, misc=False, exclude=[])
            except Exception:
                picks = None
        else:
            picks = None

        try:
            all_names = list(raw.ch_names)
        except Exception:
            all_names = []
        if picks is None:
            pick_idx = list(range(len(all_names)))
        else:
            pick_idx = list(picks) if hasattr(picks, "__iter__") else list(range(len(all_names)))
        ch_names = [all_names[i] for i in pick_idx] if all_names else [f"ch{i+1}" for i in range(len(pick_idx))]

        # clamp Nyquist / n_per_seg
        nyq = max(1.0, sfreq / 2.0 - 1e-6)
        fmin = max(0.0, float(self._fmin))
        fmax = min(max(fmin + 1e-6, float(self._fmax)), nyq)

        n_per_seg = max(2, int(round(self._seglen_s * sfreq)))
        n_overlap = max(0, int(round(self._overlap_s * sfreq)))
        n_overlap = min(n_overlap, n_per_seg - 1)

        # Ajuste n_per_seg si trop long
        try:
            n_total = int(getattr(raw, "n_times", 0))
            if n_total > 0 and n_per_seg > n_total:
                n_per_seg = max(2, n_total // 2)
                n_overlap = min(n_overlap, n_per_seg - 1)
        except Exception:
            pass

        # Signature cache
        sig = ("raw", id(raw), fmin, fmax, n_per_seg, n_overlap, self._average, bool(self._eeg_only), len(ch_names))
        if sig == self._last_signature:
            return {}

        # Compute PSD
        try:
            # MNE >= 1.0 : compute_psd
            spec = raw.compute_psd(
                method="welch",
                fmin=fmin, fmax=fmax,
                n_per_seg=n_per_seg,
                n_overlap=n_overlap,
                picks=picks,
                average=self._average,
                verbose=False
            )
            F = np.asarray(spec.freqs, dtype=float)
            P = np.asarray(spec.get_data(), dtype=np.float64)  # (n_ch, n_f)
        except Exception:
            # Fallback: psd_array_welch sur matrices
            try:
                X = raw.get_data(picks=picks)
                P, F = psd_array_welch(
                    X, sfreq=sfreq, fmin=fmin, fmax=fmax,
                    n_per_seg=n_per_seg, n_overlap=n_overlap,
                    average=self._average, verbose=False
                )
            except Exception as e:
                self._emit_none(f"Welch error: {e}")
                return {}

        # Anti bande vide
        if F.size == 0 or P.size == 0 or P.shape[1] == 0:
            # tenter une petite relaxation
            fmin2 = max(0.0, fmin - 1.0)
            fmax2 = min(nyq, fmax + 1.0)
            if fmax2 <= fmin2:
                self._emit_none("Plage f vide")
                return {}
            try:
                spec = raw.compute_psd(
                    method="welch",
                    fmin=fmin2, fmax=fmax2,
                    n_per_seg=n_per_seg, n_overlap=n_overlap,
                    picks=picks, average=self._average, verbose=False
                )
                F = np.asarray(spec.freqs, dtype=float)
                P = np.asarray(spec.get_data(), dtype=np.float64)
            except Exception:
                try:
                    X = raw.get_data(picks=picks)
                    P, F = psd_array_welch(
                        X, sfreq=sfreq, fmin=fmin2, fmax=fmax2,
                        n_per_seg=n_per_seg, n_overlap=n_overlap,
                        average=self._average, verbose=False
                    )
                except Exception as e2:
                    self._emit_none(f"Welch vide: {e2}")
                    return {}

        # Décimation max_points
        if isinstance(self._max_points, int) and self._max_points > 0 and F.size > self._max_points:
            dec = int(np.ceil(F.size / float(self._max_points)))
            F = F[::dec]
            P = P[:, ::dec]

        # Emit
        out_info: Dict[str, Any] = {
            "sfreq": sfreq, "nyquist": nyq,
            "fmin": float(fmin), "fmax": float(fmax),
            "n_per_seg": int(n_per_seg), "n_overlap": int(n_overlap),
            "average": self._average, "mode": "raw",
            "n_channels": int(P.shape[0]), "n_freqs": int(P.shape[1]),
        }
        if self._lbl:
            self._lbl.setText(f"PSD: {P.shape[0]} ch × {P.shape[1]} freq (fs={sfreq:.2f} Hz)")

        self.outputs["freqs"].on_next(np.asarray(F, dtype=np.float32))
        self.outputs["psd"].on_next(np.asarray(P, dtype=np.float32))
        self.outputs["ch_names"].on_next(list(ch_names))
        self.outputs["info"].on_next(out_info)

        self._last_signature = sig
        return {}

    # -------------------- compute (segment + sfreq) --------------------
    def _run_from_segment(self, seg_in, sfreq: float, ch_names_in):
        if seg_in is None:
            self._emit_none("segment=None")
            return {}

        A = np.asarray(seg_in)
        if A.ndim == 1:
            A = A[None, :]

        # Heuristique de transposition (canaux en 1ère dimension)
        if A.ndim == 2 and A.shape[0] < A.shape[1]:
            n0, n1 = A.shape
            # si manifestement n0 << n1, on considère (n_ch, n_s) déjà correct
            # sinon, on transpose si n0 > n1
        elif A.ndim == 2 and A.shape[0] > A.shape[1]:
            A = A.T

        n_ch, n_samp = A.shape[0], A.shape[1]
        ch_names = list(ch_names_in) if isinstance(ch_names_in, (list, tuple)) else [f"ch{i+1}" for i in range(n_ch)]

        nyq = max(1.0, sfreq / 2.0 - 1e-6)
        fmin = max(0.0, float(self._fmin))
        fmax = min(max(fmin + 1e-6, float(self._fmax)), nyq)

        n_per_seg = max(2, int(round(self._seglen_s * sfreq)))
        n_overlap = max(0, int(round(self._overlap_s * sfreq)))
        n_overlap = min(n_overlap, n_per_seg - 1)

        # Ajuste si trop long
        if n_per_seg > n_samp:
            n_per_seg = max(2, n_samp // 2)
            n_overlap = min(n_overlap, n_per_seg - 1)

        # Cache signature
        sig = ("segment", n_ch, n_samp, float(sfreq), fmin, fmax, n_per_seg, n_overlap, self._average)
        if sig == self._last_signature:
            return {}

        # Compute PSD
        try:
            P, F = psd_array_welch(
                A, sfreq=sfreq, fmin=fmin, fmax=fmax,
                n_per_seg=n_per_seg, n_overlap=n_overlap,
                average=self._average, verbose=False
            )
        except Exception as e:
            self._emit_none(f"Welch error: {e}")
            return {}

        # Bande vide → léger relâchement
        if F.size == 0 or P.size == 0 or P.shape[1] == 0:
            fmin2 = max(0.0, fmin - 1.0)
            fmax2 = min(nyq, fmax + 1.0)
            if fmax2 <= fmin2:
                self._emit_none("Plage f vide")
                return {}
            try:
                P, F = psd_array_welch(
                    A, sfreq=sfreq, fmin=fmin2, fmax=fmax2,
                    n_per_seg=n_per_seg, n_overlap=n_overlap,
                    average=self._average, verbose=False
                )
            except Exception as e2:
                self._emit_none(f"Welch vide: {e2}")
                return {}

        # Décimation
        if isinstance(self._max_points, int) and self._max_points > 0 and F.size > self._max_points:
            dec = int(np.ceil(F.size / float(self._max_points)))
            F = F[::dec]
            P = P[:, ::dec]

        out_info: Dict[str, Any] = {
            "sfreq": sfreq, "nyquist": nyq,
            "fmin": float(fmin), "fmax": float(fmax),
            "n_per_seg": int(n_per_seg), "n_overlap": int(n_overlap),
            "average": self._average, "mode": "segment",
            "n_channels": int(P.shape[0]), "n_freqs": int(P.shape[1]),
        }
        if self._lbl:
            self._lbl.setText(f"PSD: {P.shape[0]} ch × {P.shape[1]} freq (fs={sfreq:.2f} Hz)")

        self.outputs["freqs"].on_next(np.asarray(F, dtype=np.float32))
        self.outputs["psd"].on_next(np.asarray(P, dtype=np.float32))
        self.outputs["ch_names"].on_next(list(ch_names))
        self.outputs["info"].on_next(out_info)

        self._last_signature = sig
        return {}
