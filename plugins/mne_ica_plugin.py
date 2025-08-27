# plugins/mne_ica_plugin.py
# -*- coding: utf-8 -*-
"""
MNEICAPlugin (anti-freeze, pins réduits)
- ICA MNE pour artefacts EOG/ECG, Raw/Epochs.
- Robuste GDF: fit sur une fenêtre courte (par défaut 120 s, centrée) + auto-décimation.
- Pins minimaux:
    raw
    n_components (int|float|None=auto)
    method ('fastica'|'picard'|'infomax' ; def 'fastica')
    decim (int|None=auto)
    picks_eeg_only (bool, def True)
    detect_eog (bool, def True)
    detect_ecg (bool, def False)
    apply (bool, def True)
- Sorties: raw, ica, bad_components, report
- UI pliable.
"""
from typing import Any, Optional, Tuple, List, Union
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QComboBox, QSpinBox, QCheckBox,
    QVBoxLayout, QLayout, QSizePolicy
)
from PyQt5.QtCore import Qt
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

import numpy as np

try:
    import mne
    from mne.preprocessing import ICA
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

Number = Union[int, float]


class MNEICAPlugin(BasePlugin):
    name = "MNEICA"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True

    # Heuristiques anti-freeze (internes, pas exposées en pins)
    _FIT_WINDOW_S_DEFAULT = 120.0      # fenêtre max de fit (Raw)
    _EPOCHS_MAX_FOR_FIT   = 400        # nb max d'époques pour fit
    _TSTEP_S              = 2.0        # taille des sous-blocs pour fit Raw (mémoire)
    _TARGET_FS_FOR_AUTO_DECIM = 300.0  # cible d'auto-décimation si fs élevée
    _MAX_AUTO_COMPONENTS  = 25         # auto n_components si None

    def setup(self):
        # inputs (réduits)
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["n_components"] = BehaviorSubject(None)       # None=auto
        self.inputs["method"] = BehaviorSubject("fastica")
        self.inputs["decim"] = BehaviorSubject(None)              # None=auto
        self.inputs["picks_eeg_only"] = BehaviorSubject(True)
        self.inputs["detect_eog"] = BehaviorSubject(True)
        self.inputs["detect_ecg"] = BehaviorSubject(False)
        self.inputs["apply"] = BehaviorSubject(True)

        # outputs
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["ica"] = BehaviorSubject(None)
        self.outputs["bad_components"] = BehaviorSubject(None)
        self.outputs["report"] = BehaviorSubject(None)

        # cache de fit
        self._ica: Optional[ICA] = None
        self._fitted_on_id: Optional[int] = None
        self._fitted_params: Optional[Tuple] = None

        # ui
        self._widget: Optional[QWidget] = None

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        if self._widget:
            return self._widget

        root = QWidget()
        UiKit.apply_node_style(root)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget()
        f = QFormLayout(panel)

        cb_method = QComboBox()
        cb_method.addItems(["fastica", "picard", "infomax"])
        cb_method.setCurrentText(str(self.inputs["method"].value))
        cb_method.currentTextChanged.connect(lambda t: self.set_input("method", str(t)))
        f.addRow("Méthode", cb_method)

        # 0 => auto(None)
        sp_n = QSpinBox()
        sp_n.setRange(0, 512)
        sp_n.setSpecialValueText("auto")
        sp_n.setValue(0)
        sp_n.valueChanged.connect(lambda v: self.set_input("n_components", (None if v == 0 else int(v))))
        f.addRow("n_components", sp_n)

        # 0 => auto(None)
        sp_dec = QSpinBox()
        sp_dec.setRange(0, 50)
        sp_dec.setSpecialValueText("auto")
        sp_dec.setValue(0)
        sp_dec.valueChanged.connect(lambda v: self.set_input("decim", (None if v == 0 else int(v))))
        f.addRow("decim", sp_dec)

        chk_eeg = QCheckBox("EEG uniquement (picks)")
        chk_eeg.setChecked(bool(self.inputs["picks_eeg_only"].value))
        chk_eeg.stateChanged.connect(lambda s: self.set_input("picks_eeg_only", bool(s == Qt.Checked)))
        f.addRow("", chk_eeg)

        chk_eog = QCheckBox("Détecter EOG")
        chk_eog.setChecked(bool(self.inputs["detect_eog"].value))
        chk_eog.stateChanged.connect(lambda s: self.set_input("detect_eog", bool(s == Qt.Checked)))
        f.addRow("", chk_eog)

        chk_ecg = QCheckBox("Détecter ECG")
        chk_ecg.setChecked(bool(self.inputs["detect_ecg"].value))
        chk_ecg.stateChanged.connect(lambda s: self.set_input("detect_ecg", bool(s == Qt.Checked)))
        f.addRow("", chk_ecg)

        chk_apply = QCheckBox("Appliquer nettoyage")
        chk_apply.setChecked(bool(self.inputs["apply"].value))
        chk_apply.stateChanged.connect(lambda s: self.set_input("apply", bool(s == Qt.Checked)))
        f.addRow("", chk_apply)

        outer.addWidget(CollapsibleSection("Paramètres ICA", panel, collapsed=True))
        self._widget = root
        return root

    # ---------- config I/O ----------
    def export_config(self) -> dict:
        return {
            "n_components": self.inputs["n_components"].value,
            "method": str(self.inputs["method"].value),
            "decim": self.inputs["decim"].value,
            "picks_eeg_only": bool(self.inputs["picks_eeg_only"].value),
            "detect_eog": bool(self.inputs["detect_eog"].value),
            "detect_ecg": bool(self.inputs["detect_ecg"].value),
            "apply": bool(self.inputs["apply"].value),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k in ("n_components", "method", "decim", "picks_eeg_only", "detect_eog", "detect_ecg", "apply"):
            if k in cfg:
                self.inputs[k].on_next(cfg[k])
        self._widget = None

    def config_hints(self) -> dict:
        return {
            "fields": {
                "n_components": {"type": "int", "min": 0, "max": 512, "help": "0=auto"},
                "method": {"enum": ["fastica", "picard", "infomax"]},
                "decim": {"type": "int", "min": 0, "max": 50, "help": "0=auto"},
                "picks_eeg_only": {"type": "bool"},
                "detect_eog": {"type": "bool"},
                "detect_ecg": {"type": "bool"},
                "apply": {"type": "bool"},
            }
        }

    # ---------- helpers ----------
    def _picks_eeg(self, info, eeg_only: bool):
        if not HAVE_MNE or info is None or not eeg_only:
            return None
        try:
            return mne.pick_types(info, eeg=True, meg=False, eog=False, ecg=False,
                                  stim=False, misc=False, exclude=[])
        except Exception:
            return None

    def _need_refit(self, inst: Any, fit_params: Tuple) -> bool:
        return (self._ica is None) or (id(inst) != self._fitted_on_id) or (fit_params != self._fitted_params)

    def _auto_decim(self, sfreq: float, user_decim: Optional[int]) -> Optional[int]:
        if user_decim is not None and user_decim > 0:
            return int(user_decim)
        try:
            if sfreq and sfreq > self._TARGET_FS_FOR_AUTO_DECIM:
                d = int(max(1, round(sfreq / self._TARGET_FS_FOR_AUTO_DECIM)))
                return d
        except Exception:
            pass
        return None

    def _auto_n_components(self, info, user_n_comp):
        if user_n_comp is not None:
            return user_n_comp
        try:
            n_eeg = len(mne.pick_types(info, eeg=True, meg=False, eog=False, ecg=False,
                                       stim=False, misc=False, exclude=[]))
            return max(1, min(n_eeg or info.get("nchan", 32), self._MAX_AUTO_COMPONENTS))
        except Exception:
            return self._MAX_AUTO_COMPONENTS

    def _fit_on_raw(self, raw: "mne.io.BaseRaw", picks, n_components, method, decim):
        # clone de fit: preload + high-pass 1 Hz
        raw_fit = raw.copy()
        try:
            if not getattr(raw_fit, "preload", True):
                raw_fit.load_data()
        except Exception:
            pass
        try:
            raw_fit.filter(l_freq=1.0, h_freq=None, picks=picks, verbose=False)
        except Exception:
            pass

        sf = float(raw_fit.info.get("sfreq", 0.0) or 0.0)
        n_tot = int(getattr(raw_fit, "n_times", 0) or 0)
        # fenêtre max
        max_samps = int(self._FIT_WINDOW_S_DEFAULT * sf) if (sf > 0) else n_tot
        if max_samps <= 0 or n_tot <= 0:
            start = None
            stop = None
        else:
            if n_tot > max_samps:
                # prendre une fenêtre centrée (évite les bords)
                start = (n_tot - max_samps) // 2
                stop = start + max_samps
            else:
                start = 0
                stop = n_tot

        ica = ICA(n_components=n_components, method=method,
                  random_state=97, max_iter=300, fit_params={"tol": 0.0005}, verbose=False)
        ica.fit(raw_fit, picks=picks, start=start, stop=stop,
                decim=decim, tstep=self._TSTEP_S, reject_by_annotation=True, verbose=False)
        return ica

    def _fit_on_epochs(self, epochs: "mne.Epochs", picks, n_components, method, decim):
        # sous-échantillonner #époques pour éviter des durées énormes
        try:
            N = len(epochs)
        except Exception:
            N = 0
        if N > self._EPOCHS_MAX_FOR_FIT:
            epochs_fit = epochs[: self._EPOCHS_MAX_FOR_FIT]
        else:
            epochs_fit = epochs
        ica = ICA(n_components=n_components, method=method,
                  random_state=97, max_iter=300, fit_params={"tol": 0.0005}, verbose=False)
        ica.fit(epochs_fit, picks=picks, decim=decim, reject_by_annotation=True, verbose=False)
        return ica

    # ---------- execute ----------
    def execute(self, in_data=None, **kwargs):
        # Unifier les entrées
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        inst = in_data.get("raw", None)
        if inst is None or not HAVE_MNE:
            # propage tel quel + nettoie les autres sorties
            self.outputs["raw"].on_next(inst)
            self.outputs["ica"].on_next(None)
            self.outputs["bad_components"].on_next(None)
            self.outputs["report"].on_next(None)
            return {}  # <<< IMPORTANT

        method = str(in_data.get("method", self.inputs["method"].value or "fastica")).lower()
        if method not in ("fastica", "picard", "infomax"):
            method = "fastica"

        user_n_comp = in_data.get("n_components", self.inputs["n_components"].value)
        user_decim  = in_data.get("decim", self.inputs["decim"].value)
        picks_eeg_only = bool(in_data.get("picks_eeg_only", self.inputs["picks_eeg_only"].value))
        detect_eog = bool(in_data.get("detect_eog", self.inputs["detect_eog"].value))
        detect_ecg = bool(in_data.get("detect_ecg", self.inputs["detect_ecg"].value))
        apply_clean = bool(in_data.get("apply", self.inputs["apply"].value))

        info = getattr(inst, "info", None)
        picks = self._picks_eeg(info, picks_eeg_only)

        # auto n_components & decim
        sf = float(info.get("sfreq", 0.0)) if isinstance(info, dict) else 0.0
        n_components = self._auto_n_components(info, user_n_comp)
        decim = self._auto_decim(sf, user_decim)

        fit_params = (n_components, method, decim, picks_eeg_only,
                    tuple(picks) if isinstance(picks, (list, tuple, np.ndarray)) else None)

        try:
            # FIT si nécessaire
            if self._need_refit(inst, fit_params):
                if isinstance(inst, mne.io.BaseRaw):
                    self._ica = self._fit_on_raw(inst, picks, n_components, method, decim)
                else:
                    self._ica = self._fit_on_epochs(inst, picks, n_components, method, decim)
                self._fitted_on_id = id(inst)
                self._fitted_params = fit_params
                self._ica.exclude = []

            # Détection artefacts
            bads = []
            if detect_eog:
                try:
                    inds, _ = self._ica.find_bads_eog(inst, verbose=False)
                    bads.extend(list(inds or []))
                except Exception as e:
                    print(f"[MNEICA] EOG detect warn: {e}")
            if detect_ecg:
                try:
                    inds, _ = self._ica.find_bads_ecg(inst, verbose=False)
                    bads.extend(list(inds or []))
                except Exception as e:
                    print(f"[MNEICA] ECG detect warn: {e}")
            bads = sorted(list({int(i) for i in bads}))
            self._ica.exclude = bads

            # Apply sur copie
            out_inst = inst
            if apply_clean and len(bads) > 0:
                out_inst = inst.copy()
                try:
                    if isinstance(out_inst, mne.io.BaseRaw) and not getattr(out_inst, "preload", True):
                        out_inst.load_data()
                except Exception:
                    pass
                self._ica.apply(out_inst, verbose=False)

            report = (f"ICA method={method}, n_components={n_components}, decim={decim}, "
                    f"fs={sf:.2f}Hz, excluded={bads}, apply={apply_clean}")

            self.outputs["raw"].on_next(out_inst)
            self.outputs["ica"].on_next(self._ica)
            self.outputs["bad_components"].on_next(bads)
            self.outputs["report"].on_next(report)
            return {}  # <<< IMPORTANT

        except Exception as e:
            print(f"[MNEICA] Error: {e}")
            self.outputs["raw"].on_next(inst)
            self.outputs["ica"].on_next(self._ica)
            self.outputs["bad_components"].on_next(None)
            self.outputs["report"].on_next(f"Error: {e}")
            return {}  # <<< IMPORTANT
