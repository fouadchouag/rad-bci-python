# -*- coding: utf-8 -*-
"""
MNEResamplePlugin (final)
- Rééchantillonne Raw/Epochs vers une fréquence cible.
- Safe preload: force .load_data() avant .resample()
- Entrées (essentielles):
    raw, sfreq(256.0)
- Sorties:
    raw (rééchantillonné)
- UI pliable
"""
from typing import Any, Optional, Tuple, Union
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import (
    QWidget, QFormLayout, QDoubleSpinBox, QVBoxLayout, QLayout, QSizePolicy
)
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

Number = Union[int, float]


class MNEResamplePlugin(BasePlugin):
    help = help = {
        'summary': 'Resample an MNE Raw or Epochs object to a target sampling frequency.',
        'usage': 'Connect a Raw or Epochs object. Set the target sfreq in the properties panel or via the sfreq input.',
        'inputs': {
            'raw': 'mne.io.Raw or mne.Epochs — input data to resample',
            'sfreq': 'float — target sampling frequency in Hz (default 256.0)',
        },
        'outputs': {
            'raw': 'mne.io.Raw or mne.Epochs — resampled copy',
        },
        'parameters': [
            {'name': 'sfreq', 'type': 'float', 'default': 256.0, 'desc': 'Target sampling frequency in Hz (1–4096)'},
        ],
        'gotchas': [
            'If the current sfreq already matches the target, the original object is returned unchanged (no copy).',
            'Force-loads data before resampling if the Raw object is not preloaded.',
            'Resampling changes the time axis — downstream nodes must handle the new sfreq.',
            'Caching skips re-computation when the same object and target sfreq arrive again.',
        ],
    }

    name = "MNEResample"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["sfreq"] = BehaviorSubject(256.0)

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

        sb = QDoubleSpinBox()
        sb.setRange(1.0, 4096.0)
        sb.setDecimals(1)
        sb.setSingleStep(1.0)
        sb.setValue(float(self.inputs["sfreq"].value or 256.0))
        sb.valueChanged.connect(lambda v: self.set_input("sfreq", float(v)))
        f.addRow("sfreq (Hz)", sb)

        outer.addWidget(CollapsibleSection("Paramètres Resample", panel, collapsed=True))
        self._widget = root
        return root

    def export_config(self) -> dict:
        return {"sfreq": float(self.inputs["sfreq"].value or 256.0)}

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        if "sfreq" in cfg:
            self.inputs["sfreq"].on_next(cfg["sfreq"])
        self._widget = None

    def config_hints(self) -> dict:
        return {"fields": {"sfreq": {"type": "float", "min": 1.0, "max": 4096.0, "step": 1.0}}}

    def _same(self, inst: Any, params: Tuple) -> bool:
        return (id(inst) == self._last_in_id) and (params == self._last_params)

    def _current_sfreq(self, inst: Any) -> Optional[float]:
        try:
            info = getattr(inst, "info", None)
            if info and "sfreq" in info:
                return float(info["sfreq"])
        except Exception:
            return None
        return None

    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        inst = in_data.get("raw", None)
        if inst is None or not HAVE_MNE:
            self.outputs["raw"].on_next(inst)
            return

        sfreq = in_data.get("sfreq", self.inputs["sfreq"].value)
        try:
            sfreq = float(sfreq)
        except Exception:
            self.outputs["raw"].on_next(inst)
            return
        if sfreq <= 0:
            self.outputs["raw"].on_next(inst)
            return

        cur = self._current_sfreq(inst)
        if cur is not None and abs(cur - sfreq) < 1e-6:
            self.outputs["raw"].on_next(inst)
            return

        params = (float(sfreq),)
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

            out.resample(sfreq=sfreq, npad="auto", window="boxcar", n_jobs="auto", verbose=False)
            self._last_in_id = id(inst)
            self._last_params = params
            self.outputs["raw"].on_next(out)
        except Exception as e:
            print(f"[MNEResample] Error: {e}")
            self.outputs["raw"].on_next(inst)