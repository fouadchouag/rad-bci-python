# -*- coding: utf-8 -*-
"""
MNEBandpassFilterPlugin (final)
- Filtre passe-bande MNE sur Raw/Epochs.
- Safe preload: force .load_data() avant filter()
- Entrées (essentielles):
    raw, l_freq(1.0), h_freq(40.0), picks_eeg_only(True), phase('zero')
- Sorties:
    raw (filtré)
- UI pliable
"""
from typing import Any, Optional, Tuple
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QDoubleSpinBox, QCheckBox, QComboBox,
    QVBoxLayout, QLayout, QSizePolicy
)

from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class MNEBandpassFilterPlugin(BasePlugin):
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
  'summary': 'MNEBandpassFilterPlugin (final)',
  'usage': 'Insert after a reader or inlet; tune band edges.'}

    name = "MNEBandpassFilter"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["l_freq"] = BehaviorSubject(1.0)
        self.inputs["h_freq"] = BehaviorSubject(40.0)
        self.inputs["picks_eeg_only"] = BehaviorSubject(True)
        self.inputs["phase"] = BehaviorSubject("zero")  # MNE FIR phase

        self.outputs["raw"] = BehaviorSubject(None)

        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None
        self._widget: Optional[QWidget] = None

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

        sb_l = QDoubleSpinBox()
        sb_l.setRange(0.0, 500.0)
        sb_l.setDecimals(2)
        sb_l.setSingleStep(0.5)
        sb_l.setValue(float(self.inputs["l_freq"].value or 1.0))
        sb_l.valueChanged.connect(lambda v: self.set_input("l_freq", float(v)))
        f.addRow("l_freq (Hz)", sb_l)

        sb_h = QDoubleSpinBox()
        sb_h.setRange(0.0, 500.0)
        sb_h.setDecimals(2)
        sb_h.setSingleStep(0.5)
        sb_h.setValue(float(self.inputs["h_freq"].value or 40.0))
        sb_h.valueChanged.connect(lambda v: self.set_input("h_freq", float(v)))
        f.addRow("h_freq (Hz)", sb_h)

        cb_phase = QComboBox()
        cb_phase.addItems(["zero", "zero-double"])
        cb_phase.setCurrentText(str(self.inputs["phase"].value))
        cb_phase.currentTextChanged.connect(lambda t: self.set_input("phase", str(t)))
        f.addRow("Phase FIR", cb_phase)

        chk = QCheckBox("EEG uniquement (picks)")
        chk.setChecked(bool(self.inputs["picks_eeg_only"].value))
        chk.stateChanged.connect(lambda s: self.set_input("picks_eeg_only", bool(s == Qt.Checked)))
        f.addRow("", chk)

        outer.addWidget(CollapsibleSection("Paramètres Bandpass", panel, collapsed=True))
        self._widget = root
        return root

    def export_config(self) -> dict:
        return {
            "l_freq": float(self.inputs["l_freq"].value or 0.0),
            "h_freq": float(self.inputs["h_freq"].value or 0.0),
            "picks_eeg_only": bool(self.inputs["picks_eeg_only"].value),
            "phase": str(self.inputs["phase"].value),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k in ("l_freq", "h_freq", "picks_eeg_only", "phase"):
            if k in cfg:
                self.inputs[k].on_next(cfg[k])
        self._widget = None

    def config_hints(self) -> dict:
        return {
            "fields": {
                "l_freq": {"type": "float", "min": 0.0, "max": 500.0, "step": 0.5},
                "h_freq": {"type": "float", "min": 0.0, "max": 500.0, "step": 0.5},
                "picks_eeg_only": {"type": "bool"},
                "phase": {"enum": ["zero", "zero-double"]},
            }
        }

    def _same(self, inst: Any, params: Tuple) -> bool:
        return (id(inst) == self._last_in_id) and (params == self._last_params)

    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        inst = in_data.get("raw", None)
        if inst is None or not HAVE_MNE:
            self.outputs["raw"].on_next(inst)
            return

        l_f = in_data.get("l_freq", self.inputs["l_freq"].value)
        h_f = in_data.get("h_freq", self.inputs["h_freq"].value)
        picks_eeg_only = bool(in_data.get("picks_eeg_only", self.inputs["picks_eeg_only"].value))
        phase = str(in_data.get("phase", self.inputs["phase"].value))

        params = (float(l_f) if l_f is not None else None,
                  float(h_f) if h_f is not None else None,
                  picks_eeg_only, phase)
        if self._same(inst, params):
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

            out.filter(l_freq=l_f, h_freq=h_f, picks=picks,
                       phase=phase, verbose=False)
            self._last_in_id = id(inst)
            self._last_params = params
            self.outputs["raw"].on_next(out)
        except Exception as e:
            print(f"[MNEBandpassFilter] Error: {e}")
            self.outputs["raw"].on_next(inst)