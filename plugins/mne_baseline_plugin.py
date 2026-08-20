# -*- coding: utf-8 -*-
"""
MNEBaselinePlugin
- Applique une baseline sur des mne.Epochs (epochs.apply_baseline).
- Tolère execute(in_data=dict, **kwargs) ou execute(**kwargs).
- UI pliable (CollapsibleSection) + compat ConfigNode (export/import/config_hints).

Entrées:
    epochs: mne.Epochs (requis)
    baseline: tuple|list|None   (ex: (None, 0.0) ; None = pas de baseline)

Sorties:
    epochs: mne.Epochs (filtré baseline)
"""

from typing import Optional, Tuple, Any
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QDoubleSpinBox,
    QLayout, QSizePolicy
)

from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

import mne


class MNEBaselinePlugin(BasePlugin):
    help = help = {
        'summary': 'Apply a time-baseline correction to mne.Epochs via apply_baseline().',
        'usage': 'Connect mne.Epochs to the "epochs" input. Set baseline via UI or the "baseline" input tuple (start, end) in seconds.',
        'inputs': {
            'epochs': 'mne.Epochs — the epochs to baseline-correct',
            'baseline': 'tuple (start, end) in seconds, or None — e.g. (None, 0.0) means pre-stimulus to onset',
        },
        'outputs': {
            'epochs': 'mne.Epochs — baseline-corrected copy',
            'config_out': 'dict — exported configuration (auto, baseline_start, baseline_end)',
        },
        'parameters': [
            {'name': 'auto', 'type': 'bool', 'default': True, 'desc': 'Use default baseline (None, 0.0); when off, manual start/end values are used'},
            {'name': 'baseline_start', 'type': 'float', 'default': None, 'desc': 'Manual baseline start in seconds (None = start of epoch)'},
            {'name': 'baseline_end', 'type': 'float', 'default': 0.0, 'desc': 'Manual baseline end in seconds (None = end of epoch)'},
        ],
        'gotchas': [
            'If a baseline tuple is provided via the input pin it takes priority over the UI settings.',
            'On error, the unmodified epochs are passed through to avoid breaking the pipeline.',
            'Caching skips re-computation when the same epochs object and baseline parameters arrive again.',
        ],
    }

    name = "MNEBaseline"
    language = "Python"
    category = "Segmentation"
    supports_collapse = True

    def setup(self):
        # IO
        self.inputs["epochs"] = BehaviorSubject(None)
        self.inputs["baseline"] = BehaviorSubject((None, 0.0))   # défaut: (None, 0.0)
        self.outputs["epochs"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # état UI
        self._auto = True               # Auto = (None, 0.0)
        self._b_start = None            # float|None
        self._b_end = 0.0               # float|None

        # cache
        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None

        # UI refs
        self._lbl = None
        self._chk_auto = None
        self._sp_start = None
        self._sp_end = None

    # ---------------- Config I/O ----------------
    def export_config(self) -> dict:
        return {
            "auto": bool(self._auto),
            "baseline_start": (None if self._b_start is None else float(self._b_start)),
            "baseline_end":   (None if self._b_end   is None else float(self._b_end)),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self._auto = bool(cfg.get("auto", self._auto))
        bs = cfg.get("baseline_start", self._b_start)
        be = cfg.get("baseline_end", self._b_end)
        self._b_start = None if bs is None else float(bs)
        self._b_end   = None if be is None else float(be)

        if self._chk_auto:
            self._chk_auto.blockSignals(True); self._chk_auto.setChecked(self._auto); self._chk_auto.blockSignals(False)
        if self._sp_start:
            self._sp_start.blockSignals(True); self._sp_start.setValue(float(self._b_start or 0.0)); self._sp_start.setEnabled(not self._auto); self._sp_start.blockSignals(False)
        if self._sp_end:
            self._sp_end.blockSignals(True); self._sp_end.setValue(float(self._b_end or 0.0)); self._sp_end.setEnabled(not self._auto); self._sp_end.blockSignals(False)

        self._emit_config()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "auto": {"type": "bool", "label": "Auto (None, 0.0)"},
                "baseline_start": {"type": "float", "min": -10.0, "max": 10.0, "step": 0.01, "help": "Début baseline (s) ou None"},
                "baseline_end": {"type": "float", "min": -10.0, "max": 10.0, "step": 0.01, "help": "Fin baseline (s) ou None"},
            },
            "_order": ["auto", "baseline_start", "baseline_end"],
        }

    # ---------------- UI ----------------
    def build_widget(self) -> QWidget:
        root = QWidget()
        UiKit.apply_node_style(root)
        v = QVBoxLayout(root)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(8)

        r1 = QHBoxLayout()
        self._chk_auto = QCheckBox("Auto baseline (None, 0.0)")
        self._chk_auto.setChecked(self._auto)
        self._chk_auto.stateChanged.connect(self._on_auto_toggled)
        r1.addWidget(self._chk_auto)
        r1.addStretch(1)
        pv.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Start (s):"))
        self._sp_start = QDoubleSpinBox()
        self._sp_start.setRange(-10.0, 10.0)
        self._sp_start.setSingleStep(0.01)
        self._sp_start.setDecimals(3)
        self._sp_start.setValue(float(self._b_start or 0.0))
        self._sp_start.valueChanged.connect(self._on_values_changed)
        r2.addWidget(self._sp_start)

        r2.addSpacing(10)
        r2.addWidget(QLabel("End (s):"))
        self._sp_end = QDoubleSpinBox()
        self._sp_end.setRange(-10.0, 10.0)
        self._sp_end.setSingleStep(0.01)
        self._sp_end.setDecimals(3)
        self._sp_end.setValue(float(self._b_end or 0.0))
        self._sp_end.valueChanged.connect(self._on_values_changed)
        r2.addWidget(self._sp_end)

        r2.addStretch(1)
        pv.addLayout(r2)

        self._lbl = QLabel("Idle (no epochs)")
        pv.addWidget(self._lbl)

        v.addWidget(CollapsibleSection("Baseline (Epochs)", panel, collapsed=True))

        # appliquer l’état initial UI
        self._sp_start.setEnabled(not self._auto)
        self._sp_end.setEnabled(not self._auto)

        self._emit_config()
        return root

    def _on_auto_toggled(self, _state):
        self._auto = bool(self._chk_auto.isChecked())
        self._sp_start.setEnabled(not self._auto)
        self._sp_end.setEnabled(not self._auto)
        self._emit_config()
        # relancer traitement si epochs présent
        self._run_if_ready(self.inputs.get("epochs", None).value if "epochs" in self.inputs else None)

    def _on_values_changed(self, _v):
        # MAJ valeurs locales si manuel
        if not self._auto:
            self._b_start = float(self._sp_start.value())
            self._b_end = float(self._sp_end.value())
            self._emit_config()
            self._run_if_ready(self.inputs.get("epochs", None).value if "epochs" in self.inputs else None)

    # ---------------- Helpers ----------------
    def _normalize_baseline(self, in_data: dict) -> Optional[Tuple[Optional[float], Optional[float]]]:
        # priorité aux kwargs/in_data["baseline"] si fourni
        base = in_data.get("baseline", None)
        if base is not None:
            try:
                if isinstance(base, (list, tuple)) and len(base) == 2:
                    a = None if base[0] is None else float(base[0])
                    b = None if base[1] is None else float(base[1])
                    return (a, b)
            except Exception:
                pass
        # sinon: UI
        if self._auto:
            return (None, 0.0)
        else:
            return (None if self._b_start is None else float(self._b_start),
                    None if self._b_end   is None else float(self._b_end))

    def _is_same_request(self, epochs_obj: Any, baseline_tuple: Tuple) -> bool:
        return (id(epochs_obj) == self._last_in_id) and (baseline_tuple == self._last_params)

    def _run_if_ready(self, epochs):
        if epochs is None:
            self.outputs["epochs"].on_next(None)
            if self._lbl: self._lbl.setText("Idle (no epochs)")
            return
        # re-déclenche traitement avec les derniers réglages
        self.execute(epochs=epochs)

    # ---------------- Exécution ----------------
    def execute(self, in_data=None, **kwargs):
        # Unifier
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        epochs = in_data.get("epochs", None)
        if epochs is None:
            self.outputs["epochs"].on_next(None)
            if self._lbl: self._lbl.setText("Idle (no epochs)")
            return {}

        try:
            baseline = self._normalize_baseline(in_data)
            params = (baseline,)

            if self._is_same_request(epochs, params):
                return {}

            out = epochs.copy()
            out.apply_baseline(baseline)

            self._last_in_id = id(epochs)
            self._last_params = params

            self.outputs["epochs"].on_next(out)
            if self._lbl:
                self._lbl.setText(f"Applied baseline={baseline} | N={len(out)}")
        except Exception as e:
            # Pass-through en cas d'erreur
            self.outputs["epochs"].on_next(epochs)
            if self._lbl:
                self._lbl.setText(f"Error: {e}")
        return {}