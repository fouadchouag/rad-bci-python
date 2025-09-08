# -*- coding: utf-8 -*-
"""
MNENotchFilterPlugin (final)
- Filtre en encoche (notch) pour retirer secteur 50/60 Hz et harmon. (Raw/Epochs)
- Safe preload: force .load_data() avant notch_filter pour éviter RuntimeError MNE
- Entrées (minimisées):
    raw: mne.io.Raw | mne.Epochs
    freqs: float | list[float]  (def: 50.0)
    harmonics_max: int          (def: 0)   -> 0 = pas d'harmoniques
    picks_eeg_only: bool        (def: True)
    phase: str                  (def: 'zero')  ['zero','zero-double']
- Sorties:
    raw: même type filtré
- UI: section pliable (CollapsibleSection)
"""
from typing import Any, List, Optional, Sequence, Tuple, Union
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox,
    QVBoxLayout, QLayout, QSizePolicy
)

from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

Number = Union[int, float]


class MNENotchFilterPlugin(BasePlugin):
    help = help = { 'gotchas': [ 'Choose FIR/IIR consistent with sfreq.',
               'Mind edge effects on short windows.'],
  'inputs': { 'raw': 'mne.Raw (opt.)',
              'segment': '2D float [ch x samples] (opt.)',
              'sfreq': 'float (Hz if segment)'},
  'outputs': {'raw': 'filtered Raw', 'segment': 'filtered array'},
  'parameters': [ { 'default': 1.0,
                    'desc': 'High-pass cutoff',
                    'name': 'hp',
                    'type': 'float|None',
                    'unit': 'Hz'},
                  { 'default': 40.0,
                    'desc': 'Low-pass cutoff',
                    'name': 'lp',
                    'type': 'float|None',
                    'unit': 'Hz'},
                  { 'default': 50.0,
                    'desc': 'Notch (mains)',
                    'name': 'notch',
                    'type': 'float|None',
                    'unit': 'Hz'}],
  'summary': 'MNENotchFilterPlugin (final)',
  'usage': 'Insert after a reader or inlet; tune band edges.'}

    name = "MNENotchFilter"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True

    # ---------- lifecycle ----------
    def setup(self):
        # Inputs (minimisés)
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["freqs"] = BehaviorSubject(50.0)
        self.inputs["harmonics_max"] = BehaviorSubject(0)
        self.inputs["picks_eeg_only"] = BehaviorSubject(True)
        self.inputs["phase"] = BehaviorSubject("zero")

        # Outputs
        self.outputs["raw"] = BehaviorSubject(None)

        # Cache
        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None

        # UI ref
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

        sb_f = QDoubleSpinBox()
        sb_f.setRange(1.0, 2000.0)
        sb_f.setDecimals(2)
        sb_f.setSingleStep(1.0)
        sb_f.setValue(float(self.inputs["freqs"].value or 50.0))
        sb_f.valueChanged.connect(lambda v: self.set_input("freqs", float(v)))
        f.addRow("Fréquence (Hz)", sb_f)

        sp_h = QSpinBox()
        sp_h.setRange(0, 10)
        sp_h.setValue(int(self.inputs["harmonics_max"].value or 0))
        sp_h.valueChanged.connect(lambda v: self.set_input("harmonics_max", int(v)))
        f.addRow("Harmoniques (max)", sp_h)

        cb_phase = QComboBox()
        cb_phase.addItems(["zero", "zero-double"])
        try:
            cb_phase.setCurrentText(str(self.inputs["phase"].value))
        except Exception:
            pass
        cb_phase.currentTextChanged.connect(lambda t: self.set_input("phase", str(t)))
        f.addRow("Phase FIR", cb_phase)

        chk_eeg = QCheckBox("EEG uniquement (picks)")
        chk_eeg.setChecked(bool(self.inputs["picks_eeg_only"].value))
        chk_eeg.stateChanged.connect(lambda s: self.set_input("picks_eeg_only", bool(s == Qt.Checked)))
        f.addRow("", chk_eeg)

        outer.addWidget(CollapsibleSection("Paramètres Notch", panel, collapsed=True))
        self._widget = root
        return root

    # ---------- config I/O ----------
    def export_config(self) -> dict:
        return {
            "freqs": self.inputs["freqs"].value,
            "harmonics_max": int(self.inputs["harmonics_max"].value or 0),
            "picks_eeg_only": bool(self.inputs["picks_eeg_only"].value),
            "phase": str(self.inputs["phase"].value),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k in ("freqs", "harmonics_max", "picks_eeg_only", "phase"):
            if k in cfg:
                self.inputs[k].on_next(cfg[k])
        # sync UI if exists
        self._widget = None  # UI will be rebuilt by host if needed

    def config_hints(self) -> dict:
        return {
            "fields": {
                "freqs": {"type": "float", "min": 1.0, "max": 2000.0, "step": 1.0},
                "harmonics_max": {"type": "int", "min": 0, "max": 10},
                "picks_eeg_only": {"type": "bool"},
                "phase": {"enum": ["zero", "zero-double"]},
            }
        }

    # ---------- helpers ----------
    @staticmethod
    def _to_freq_list(freqs: Union[Number, Sequence[Number], None], harmonics_max: int) -> List[float]:
        if freqs is None:
            return []
        base = [float(freqs)] if isinstance(freqs, (int, float)) else [float(f) for f in freqs]
        out: List[float] = []
        for f0 in base:
            if f0 <= 0:
                continue
            out.append(float(f0))
            for k in range(2, int(harmonics_max or 0) + 1):
                out.append(k * float(f0))
        return sorted(list({round(f, 6) for f in out if f > 0}))

    def _is_same(self, raw_obj: Any, params: Tuple) -> bool:
        return (id(raw_obj) == self._last_in_id) and (params == self._last_params)

    # ---------- execute ----------
    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        inst = in_data.get("raw", None)
        if inst is None or not HAVE_MNE:
            self.outputs["raw"].on_next(inst)
            return

        freqs_in = in_data.get("freqs", self.inputs["freqs"].value)
        harmonics_max = int(in_data.get("harmonics_max", self.inputs["harmonics_max"].value or 0))
        picks_eeg_only = bool(in_data.get("picks_eeg_only", self.inputs["picks_eeg_only"].value))
        phase = str(in_data.get("phase", self.inputs["phase"].value or "zero"))

        freqs_list = self._to_freq_list(freqs_in, harmonics_max)
        if not freqs_list:
            self.outputs["raw"].on_next(inst)  # pass-through
            return

        params = (tuple(freqs_list), harmonics_max, picks_eeg_only, phase)
        if self._is_same(inst, params):
            return

        try:
            out = inst.copy()
            # preload safety
            try:
                if isinstance(out, mne.io.BaseRaw) and not getattr(out, "preload", True):
                    out.load_data()
            except Exception:
                pass

            picks = None
            if picks_eeg_only and hasattr(out, "info"):
                try:
                    picks = mne.pick_types(out.info, eeg=True, meg=False, eog=False, ecg=False,
                                           stim=False, misc=False, exclude=[])
                except Exception:
                    picks = None

            out.notch_filter(freqs=freqs_list, picks=picks, method="fir",
                             fir_design="firwin", phase=phase, verbose=False)
            self._last_in_id = id(inst)
            self._last_params = params
            self.outputs["raw"].on_next(out)
        except Exception as e:
            print(f"[MNENotchFilter] Error: {e}")
            self.outputs["raw"].on_next(inst)