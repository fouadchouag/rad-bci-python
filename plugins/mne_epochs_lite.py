# plugins/mne_epochs_lite.py
# -*- coding: utf-8 -*-
"""
MNEEpochsLite — Epoching minimal & robuste
Ordre des événements: Annotations -> STIM -> fixed-length -> manuel.
Pins (minimaux):
  IN : raw, use_annotations(bool), epoch_len_s(float), step_s(float)
  OUT: epochs, events, config_out
UI: pliable. Exécution tolérante: execute(in_data=..., **kwargs)
"""
from typing import Any, Dict, Optional, Tuple
import numpy as np
import mne
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QCheckBox,
    QLabel, QSizePolicy, QLayout
)


class MNEEpochsLite(BasePlugin):
    help = help = { 'gotchas': ['Check event alignment and baseline.'],
  'inputs': {'events': 'array/list (optional)', 'raw': 'mne.Raw'},
  'outputs': {'epochs': 'mne.Epochs (if events)', 'segment': '2D float [ch x samples]'},
  'parameters': [ { 'default': -0.2,
                    'desc': 'Epoch start',
                    'name': 'tmin',
                    'type': 'float',
                    'unit': 's'},
                  { 'default': 0.8,
                    'desc': 'Epoch end',
                    'name': 'tmax',
                    'type': 'float',
                    'unit': 's'}],
  'summary': 'MNEEpochsLite — Epoching minimal & robuste',
  'usage': 'Connect Raw; optionally provide events; route to features/ML.'}

    name = "MNEEpochsLite"
    language = "Python"
    category = "Segmentation"
    supports_collapse = True

    # ---------------- lifecycle ----------------
    def setup(self):
        # IN (essentiels)
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["use_annotations"] = BehaviorSubject(True)
        self.inputs["epoch_len_s"] = BehaviorSubject(1.0)
        self.inputs["step_s"] = BehaviorSubject(1.0)

        # OUT
        self.outputs["epochs"] = BehaviorSubject(None)
        self.outputs["events"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # cache
        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None
        self._last_events_sig: Optional[Tuple[int, int]] = None

        # UI
        self._widget = None
        self._lbl = None

        self._emit_config()

    # ---------------- config I/O ----------------
    def export_config(self) -> dict:
        return {
            "use_annotations": bool(self.inputs["use_annotations"].value),
            "epoch_len_s": float(self.inputs["epoch_len_s"].value),
            "step_s": float(self.inputs["step_s"].value),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return

        def _set(pin, v):
            try:
                self.inputs[pin].on_next(v)
            except Exception:
                pass

        if "use_annotations" in cfg:
            _set("use_annotations", bool(cfg["use_annotations"]))
        if "epoch_len_s" in cfg:
            try:
                _set("epoch_len_s", max(0.05, float(cfg["epoch_len_s"])))
            except Exception:
                pass
        if "step_s" in cfg:
            try:
                _set("step_s", max(0.05, float(cfg["step_s"])))
            except Exception:
                pass

        self._emit_config()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "use_annotations": {"type": "bool", "label": "Utiliser les annotations si présentes"},
                "epoch_len_s": {"type": "float", "min": 0.05, "max": 30.0, "step": 0.05, "label": "Durée epoch (s)"},
                "step_s": {"type": "float", "min": 0.05, "max": 30.0, "step": 0.05, "label": "Pas / step (s)"},
            },
            "_order": ["use_annotations", "epoch_len_s", "step_s"],
        }

    # ---------------- UI ----------------
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        root = QWidget()
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget()
        form = QFormLayout(panel)

        chk_ann = QCheckBox("Utiliser les annotations si présentes")
        chk_ann.setChecked(bool(self.inputs["use_annotations"].value))
        chk_ann.stateChanged.connect(lambda s: self._set_pin("use_annotations", bool(s == Qt.Checked)))
        form.addRow("", chk_ann)

        sp_len = QDoubleSpinBox()
        sp_len.setRange(0.05, 30.0); sp_len.setSingleStep(0.05); sp_len.setDecimals(3)
        sp_len.setValue(float(self.inputs["epoch_len_s"].value))
        sp_len.valueChanged.connect(lambda v: self._set_pin("epoch_len_s", float(v)))
        form.addRow("Durée epoch (s)", sp_len)

        sp_step = QDoubleSpinBox()
        sp_step.setRange(0.05, 30.0); sp_step.setSingleStep(0.05); sp_step.setDecimals(3)
        sp_step.setValue(float(self.inputs["step_s"].value))
        sp_step.valueChanged.connect(lambda v: self._set_pin("step_s", float(v)))
        form.addRow("Pas / step (s)", sp_step)

        self._lbl = QLabel("")
        form.addRow("info", self._lbl)

        outer.addWidget(CollapsibleSection("Paramètres d'epoching (lite)", panel, collapsed=True))
        self._widget = root
        self._emit_config()
        return root

    def _set_pin(self, pin, val):
        try:
            self.inputs[pin].on_next(val)
            self._emit_config()
            r = self.inputs["raw"].value
            if r is not None:
                self.execute(raw=r)  # relance si connecté
        except Exception:
            pass

    # ---------------- helpers ----------------
    @staticmethod
    def _events_signature(arr: Optional[np.ndarray]) -> Tuple[int, int]:
        if arr is None or not isinstance(arr, np.ndarray) or arr.ndim != 2 or arr.shape[1] != 3:
            return (0, 0)
        N = int(arr.shape[0])
        chk = int(np.sum(arr.astype(np.int64)) % 1000003)
        return (N, chk)

    def _same_request(self, raw_obj: Any, params: Tuple, ev_sig: Tuple[int, int]) -> bool:
        return (id(raw_obj) == self._last_in_id) and (params == self._last_params) and (ev_sig == self._last_events_sig)

    @staticmethod
    def _safe_manual_events(raw, step_s: float, code: int = 1) -> Optional[np.ndarray]:
        """Fallback manuel ultra-robuste: crée des événements réguliers en échantillons."""
        try:
            sf = float(raw.info.get("sfreq", 0.0))
            n_times = int(getattr(raw, "n_times", 0))
            first = int(getattr(raw, "first_samp", 0))
        except Exception:
            return None
        if sf <= 0 or n_times <= 0:
            return None

        dur_s = n_times / sf
        if step_s <= 0:
            step_s = max(0.05, dur_s)  # au moins un événement

        # positions en secondes, puis conversion en échantillons (offset first_samp)
        t = np.arange(0.0, max(dur_s - 1.0 / sf, 0.0) + 1e-9, step_s, dtype=float)
        if t.size == 0:
            t = np.array([0.0], dtype=float)
        samp = np.clip(np.round(first + t * sf).astype(np.int64), first, first + n_times - 1)
        events = np.column_stack([
            samp,
            np.zeros_like(samp, dtype=np.int64),
            np.full_like(samp, code, dtype=np.int64),
        ])
        return events.astype(np.int32, copy=False)

    def _find_events_via_stim(self, raw) -> Optional[np.ndarray]:
        """Essaie de détecter un canal STIM et d'extraire des events."""
        try:
            stim_picks = mne.pick_types(raw.info, stim=True)
            if stim_picks is not None and len(stim_picks) > 0:
                stim_name = raw.ch_names[int(stim_picks[0])]
                ev = mne.find_events(raw, stim_channel=stim_name,
                                     shortest_event=1, initial_event=True,
                                     verbose=False)
                if isinstance(ev, np.ndarray) and ev.ndim == 2 and ev.shape[1] == 3 and ev.shape[0] > 0:
                    return ev.astype(np.int32, copy=False)
        except Exception:
            pass
        return None

    # ---------------- execute ----------------
    def execute(self, in_data: Optional[Dict[str, Any]] = None, **kwargs) -> dict:
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        raw = in_data.get("raw", None)
        if raw is None:
            self.outputs["epochs"].on_next(None)
            self.outputs["events"].on_next(None)
            if self._lbl:
                self._lbl.setText("No raw")
            return {}

        use_ann = bool(in_data.get("use_annotations", self.inputs["use_annotations"].value))
        epoch_len = max(0.05, float(in_data.get("epoch_len_s", self.inputs["epoch_len_s"].value)))
        step = max(0.05, float(in_data.get("step_s", self.inputs["step_s"].value)))

        # ---------- 1) annotations ----------
        events = None
        src = "none"
        try:
            has_ann = hasattr(raw, "annotations") and raw.annotations is not None and len(raw.annotations) > 0
            if use_ann and has_ann:
                ev, _map = mne.events_from_annotations(raw, verbose=False)
                if isinstance(ev, np.ndarray) and ev.shape[0] > 0 and ev.shape[1] == 3:
                    events = ev.astype(np.int32, copy=False)
                    src = "annotations"
        except Exception:
            events = None

        # ---------- 2) STIM fallback ----------
        if events is None:
            ev2 = self._find_events_via_stim(raw)
            if ev2 is not None:
                events = ev2
                src = "stim"

        # ---------- 3) fixed-length fallback ----------
        if events is None:
            try:
                ev3 = mne.make_fixed_length_events(raw, id=1, start=0.0, stop=None, duration=step, verbose=False)
                if isinstance(ev3, np.ndarray) and ev3.shape[0] > 0 and ev3.shape[1] == 3:
                    events = ev3.astype(np.int32, copy=False)
                    src = "fixed"
            except Exception:
                events = None

        # ---------- 4) manuel ultime ----------
        if events is None:
            events = self._safe_manual_events(raw, step_s=step, code=1)
            if events is not None:
                src = "manual"

        # Sans events -> stop propre
        if events is None or not isinstance(events, np.ndarray) or events.ndim != 2 or events.shape[1] != 3 or events.shape[0] == 0:
            self.outputs["epochs"].on_next(None)
            self.outputs["events"].on_next(None)
            if self._lbl:
                self._lbl.setText("No events (file too short / STIM absent?)")
            return {}

        ev_sig = self._events_signature(events)
        params = (bool(use_ann), float(epoch_len), float(step))
        if self._same_request(raw, params, ev_sig):
            return {}

        # Picks EEG-only
        picks = None
        try:
            if hasattr(raw, "info"):
                picks = mne.pick_types(raw.info, eeg=True, meg=False, eog=False, ecg=False, stim=False, misc=False, exclude=[])
        except Exception:
            picks = None

        # Epochs: fenêtres [0, epoch_len]
        try:
            epochs = mne.Epochs(
                raw=raw,
                events=events,
                event_id=None,        # inclure toutes classes
                tmin=0.0, tmax=epoch_len,
                baseline=None,
                picks=picks,
                preload=True,         # assure la dispo mémoire même si raw est lazy
                detrend=None,
                reject_by_annotation=True,
                verbose=False
            )
        except Exception as e:
            try:
                print(f"[MNEEpochsLite] Error: {e}")
            except Exception:
                pass
            self.outputs["epochs"].on_next(None)
            self.outputs["events"].on_next(None)
            if self._lbl:
                self._lbl.setText("Epochs failed")
            return {}

        # Cache + sorties
        self._last_in_id = id(raw)
        self._last_params = params
        self._last_events_sig = ev_sig

        self.outputs["epochs"].on_next(epochs)
        self.outputs["events"].on_next(events)
        if self._lbl:
            self._lbl.setText(f"Epochs: N={len(epochs)}  len={epoch_len:.3f}s  step={step:.3f}s  src={src}")
        return {}