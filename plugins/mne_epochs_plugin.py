# plugins/mne_epochs_plugin.py
# -*- coding: utf-8 -*-
"""
MNEEpochs
- Construit des Epochs MNE à partir d'un Raw + événements (events explicites ou auto depuis annotations).
- Pins essentiels:
    IN : raw, events (opt), event_id (opt), tmin, tmax, baseline (opt),
         picks_eeg_only, preload, detrend, reject_by_annotation
    OUT: epochs, events, config_out
- UI pliable + config compatible (export/import/config_hints)
- Exécution robuste: execute(in_data={...}, **kwargs) → retourne {}
"""

from typing import Any, Dict, Optional, Tuple, Union
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

import mne

# Qt
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QCheckBox,
    QLineEdit, QSizePolicy, QLayout, QLabel
)


class MNEEpochsPlugin(BasePlugin):
    help = help = {
        'summary': 'Create mne.Epochs from an MNE Raw object plus events (explicit or auto-extracted from annotations).',
        'usage': 'Connect a Raw object. Optionally supply events array and event_id. Routed epochs go to feature extraction or classifier nodes.',
        'inputs': {
            'raw': 'mne.io.Raw — the continuous recording to segment into epochs',
            'events': 'np.ndarray (N, 3) — optional explicit events; if None, events are extracted from annotations',
            'event_id': 'dict | int | str | None — event_id mapping for mne.Epochs; None = all events',
            'tmin': 'float — epoch start time in seconds relative to event (default -0.2)',
            'tmax': 'float — epoch end time in seconds relative to event (default 0.8)',
            'baseline': 'tuple (start, end) | None — baseline correction window in seconds; None = no baseline',
            'picks_eeg_only': 'bool — restrict to EEG channels (default True)',
            'preload': 'bool — load data into memory immediately (default True)',
            'detrend': 'None | 0 | 1 — detrending mode; None=off, 0=constant, 1=linear',
            'reject_by_annotation': 'bool — reject epochs overlapping annotated bad segments (default True)',
        },
        'outputs': {
            'epochs': 'mne.Epochs — the epoched data (or None if no valid events)',
            'events': 'np.ndarray (N, 3) — the events array actually used',
            'config_out': 'dict — exported configuration snapshot',
        },
        'parameters': [
            {'name': 'event_id', 'type': 'any', 'default': None, 'desc': 'dict|int|str|None — event ID filter; None means use all detected events'},
            {'name': 'tmin', 'type': 'float', 'default': -0.2, 'desc': 'Epoch start (s) relative to each event'},
            {'name': 'tmax', 'type': 'float', 'default': 0.8, 'desc': 'Epoch end (s) relative to each event'},
            {'name': 'baseline', 'type': 'tuple|None', 'default': None, 'desc': 'Baseline window (start, end) in seconds; None to skip'},
            {'name': 'picks_eeg_only', 'type': 'bool', 'default': True, 'desc': 'Restrict epochs to EEG channels'},
            {'name': 'preload', 'type': 'bool', 'default': True, 'desc': 'Load epoch data into memory immediately'},
            {'name': 'detrend', 'type': 'int|None', 'default': None, 'desc': 'Detrending: None=off, 0=constant, 1=linear'},
            {'name': 'reject_by_annotation', 'type': 'bool', 'default': True, 'desc': 'Drop epochs that overlap bad annotations'},
        ],
        'gotchas': [
            'If no events array is supplied, events are auto-extracted via mne.events_from_annotations — the Raw must have annotations.',
            'If event_id is a string and no matching annotation is found, output will be None.',
            'Setting preload=False may cause issues with downstream nodes that need in-memory data.',
            'Caching skips re-epoching if the same raw, parameters, and events signature arrive again.',
        ],
    }

    name = "MNEEpochs"
    language = "Python"
    category = "Segmentation"
    supports_collapse = True

    # ------------- lifecycle -------------
    def setup(self):
        # IN pins (essentiels)
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["events"] = BehaviorSubject(None)          # np.ndarray [N,3] (opt)
        self.inputs["event_id"] = BehaviorSubject(None)        # dict|int|str|None
        self.inputs["tmin"] = BehaviorSubject(-0.2)
        self.inputs["tmax"] = BehaviorSubject(0.8)
        self.inputs["baseline"] = BehaviorSubject(None)        # (None, 0.0) ou None
        self.inputs["picks_eeg_only"] = BehaviorSubject(True)
        self.inputs["preload"] = BehaviorSubject(True)
        self.inputs["detrend"] = BehaviorSubject(None)         # None|0|1
        self.inputs["reject_by_annotation"] = BehaviorSubject(True)

        # OUT pins
        self.outputs["epochs"] = BehaviorSubject(None)
        self.outputs["events"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # état/cache
        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None
        self._last_events_sig: Optional[Tuple[int, int]] = None

        # refs UI
        self._widget: Optional[QWidget] = None
        self._ed_event_id: Optional[QLineEdit] = None
        self._sp_tmin: Optional[QDoubleSpinBox] = None
        self._sp_tmax: Optional[QDoubleSpinBox] = None
        self._ed_base_a: Optional[QLineEdit] = None
        self._ed_base_b: Optional[QLineEdit] = None
        self._chk_eeg: Optional[QCheckBox] = None
        self._chk_preload: Optional[QCheckBox] = None
        self._chk_rba: Optional[QCheckBox] = None
        self._lbl_status: Optional[QLabel] = None

        self._emit_config()

    # ------------- config I/O -------------
    def export_config(self) -> dict:
        return {
            "event_id": self.inputs["event_id"].value,
            "tmin": float(self.inputs["tmin"].value),
            "tmax": float(self.inputs["tmax"].value),
            "baseline": self.inputs["baseline"].value,
            "picks_eeg_only": bool(self.inputs["picks_eeg_only"].value),
            "preload": bool(self.inputs["preload"].value),
            "detrend": self.inputs["detrend"].value,
            "reject_by_annotation": bool(self.inputs["reject_by_annotation"].value),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return

        def set_val(pin, val):
            try:
                self.inputs[pin].on_next(val)
            except Exception:
                pass

        # tmin/tmax
        for k in ("tmin", "tmax"):
            if k in cfg:
                try: set_val(k, float(cfg[k]))
                except Exception: pass

        # baseline
        if "baseline" in cfg:
            b = cfg.get("baseline")
            if isinstance(b, (list, tuple)) and len(b) == 2:
                a = None if b[0] is None else float(b[0])
                c = None if b[1] is None else float(b[1])
                set_val("baseline", (a, c))
            elif b is None:
                set_val("baseline", None)

        # bools
        for k in ("picks_eeg_only", "preload", "reject_by_annotation"):
            if k in cfg:
                try: set_val(k, bool(cfg[k]))
                except Exception: pass

        # detrend
        if "detrend" in cfg:
            d = cfg["detrend"]
            set_val("detrend", (int(d) if d in (0, 1) else None))

        # event_id (on garde tel quel; string/int/dict/None)
        if "event_id" in cfg:
            set_val("event_id", cfg["event_id"])

        # sync UI
        try:
            if self._sp_tmin: self._sp_tmin.setValue(float(self.inputs["tmin"].value))
            if self._sp_tmax: self._sp_tmax.setValue(float(self.inputs["tmax"].value))
            if self._ed_base_a and self._ed_base_b:
                bs = self.inputs["baseline"].value
                a = "" if bs is None or bs[0] is None else str(bs[0])
                b = "" if bs is None or bs[1] is None else str(bs[1])
                self._ed_base_a.setText(a); self._ed_base_b.setText(b)
            if self._chk_eeg: self._chk_eeg.setChecked(bool(self.inputs["picks_eeg_only"].value))
            if self._chk_preload: self._chk_preload.setChecked(bool(self.inputs["preload"].value))
            if self._chk_rba: self._chk_rba.setChecked(bool(self.inputs["reject_by_annotation"].value))
            if self._ed_event_id and self.inputs["event_id"].value is not None:
                self._ed_event_id.setText(str(self.inputs["event_id"].value))
        except Exception:
            pass

        self._emit_config()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "event_id": {"type": "any", "help": "dict|int|str|None"},
                "tmin": {"type": "float", "min": -10.0, "max": 10.0, "step": 0.05},
                "tmax": {"type": "float", "min": -10.0, "max": 10.0, "step": 0.05},
                "baseline": {"type": "list", "help": "(a,b) en secondes, None pour désactiver"},
                "picks_eeg_only": {"type": "bool"},
                "preload": {"type": "bool"},
                "detrend": {"type": "enum", "enum": [None, 0, 1]},
                "reject_by_annotation": {"type": "bool"},
            },
            "_order": ["event_id", "tmin", "tmax", "baseline", "picks_eeg_only", "preload", "detrend", "reject_by_annotation"],
        }

    # ------------- UI -------------
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        root = QWidget()
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget()
        form = QFormLayout(panel)

        # event_id (texte libre: int/str/dict)
        ed_eid = QLineEdit()
        ed_eid.setPlaceholderText("ex: {'StimA':1, 'StimB':2}  ou  1  ou  'StimA'  (laisser vide = tous)")
        if self.inputs["event_id"].value is not None:
            ed_eid.setText(str(self.inputs["event_id"].value))
        ed_eid.editingFinished.connect(lambda: self._on_ui_event_id(ed_eid.text()))
        form.addRow("event_id", ed_eid)
        self._ed_event_id = ed_eid

        # tmin / tmax
        sp_tmin = QDoubleSpinBox(); sp_tmin.setRange(-10.0, 10.0); sp_tmin.setDecimals(3); sp_tmin.setSingleStep(0.05)
        sp_tmin.setValue(float(self.inputs["tmin"].value)); sp_tmin.valueChanged.connect(lambda v: self._set_pin("tmin", float(v)))
        form.addRow("tmin (s)", sp_tmin); self._sp_tmin = sp_tmin

        sp_tmax = QDoubleSpinBox(); sp_tmax.setRange(-10.0, 10.0); sp_tmax.setDecimals(3); sp_tmax.setSingleStep(0.05)
        sp_tmax.setValue(float(self.inputs["tmax"].value)); sp_tmax.valueChanged.connect(lambda v: self._set_pin("tmax", float(v)))
        form.addRow("tmax (s)", sp_tmax); self._sp_tmax = sp_tmax

        # baseline (deux champs)
        ed_ba = QLineEdit(); ed_bb = QLineEdit()
        ed_ba.setPlaceholderText("a (s) ou vide"); ed_bb.setPlaceholderText("b (s) ou vide")
        bs = self.inputs["baseline"].value
        if isinstance(bs, (list, tuple)) and len(bs) == 2:
            ed_ba.setText("" if bs[0] is None else str(bs[0]))
            ed_bb.setText("" if bs[1] is None else str(bs[1]))
        ed_ba.editingFinished.connect(lambda: self._on_ui_baseline(ed_ba.text(), ed_bb.text()))
        ed_bb.editingFinished.connect(lambda: self._on_ui_baseline(ed_ba.text(), ed_bb.text()))
        form.addRow("baseline (a,b)", ed_ba); form.addRow("", ed_bb)
        self._ed_base_a, self._ed_base_b = ed_ba, ed_bb

        # options bool
        chk_eeg = QCheckBox("EEG uniquement"); chk_eeg.setChecked(bool(self.inputs["picks_eeg_only"].value))
        chk_eeg.stateChanged.connect(lambda s: self._set_pin("picks_eeg_only", bool(s == Qt.Checked)))
        form.addRow("", chk_eeg); self._chk_eeg = chk_eeg

        chk_pl = QCheckBox("Preload"); chk_pl.setChecked(bool(self.inputs["preload"].value))
        chk_pl.stateChanged.connect(lambda s: self._set_pin("preload", bool(s == Qt.Checked)))
        form.addRow("", chk_pl); self._chk_preload = chk_pl

        chk_rba = QCheckBox("Reject by annotation"); chk_rba.setChecked(bool(self.inputs["reject_by_annotation"].value))
        chk_rba.stateChanged.connect(lambda s: self._set_pin("reject_by_annotation", bool(s == Qt.Checked)))
        form.addRow("", chk_rba); self._chk_rba = chk_rba

        self._lbl_status = QLabel("")
        form.addRow("info", self._lbl_status)

        outer.addWidget(CollapsibleSection("Epoching settings", panel, collapsed=True))

        self._widget = root
        self._emit_config()
        return root

    def _set_pin(self, pin, val):
        try:
            self.inputs[pin].on_next(val)
            self._emit_config()
            r = self.inputs["raw"].value
            if r is not None:
                self.execute(raw=r)   # relance si déjà connecté
        except Exception:
            pass

    def _on_ui_event_id(self, txt: str):
        val = self._parse_event_id(txt)
        self._set_pin("event_id", val)

    def _on_ui_baseline(self, a_txt: str, b_txt: str):
        def _f(s):
            s = s.strip()
            if s == "":
                return None
            try: return float(s)
            except Exception: return None
        self._set_pin("baseline", (_f(a_txt), _f(b_txt)))

    # ------------- helpers -------------
    @staticmethod
    def _events_signature(arr: Optional[np.ndarray]) -> Tuple[int, int]:
        if arr is None or not isinstance(arr, np.ndarray) or arr.ndim != 2 or arr.shape[1] != 3:
            return (0, 0)
        N = int(arr.shape[0])
        chk = int(np.sum(arr.astype(np.int64)) % 1000003)
        return (N, chk)

    @staticmethod
    def _coerce_baseline(x: Any):
        if x is None:
            return None
        if isinstance(x, (list, tuple)) and len(x) == 2:
            a, b = x
            a = None if a is None else float(a)
            b = None if b is None else float(b)
            return (a, b)
        return None

    @staticmethod
    def _normalize_event_id(eid_in: Any, ann_map: Optional[Dict[str, int]]):
        if eid_in is None:
            return None
        if isinstance(eid_in, dict):
            return {str(k): int(v) for k, v in eid_in.items()}
        if isinstance(eid_in, (int, np.integer)):
            return int(eid_in)
        if isinstance(eid_in, str):
            if ann_map:
                if eid_in in ann_map:
                    return {eid_in: ann_map[eid_in]}
                sub = {k: v for k, v in ann_map.items() if eid_in.lower() in k.lower()}
                return sub if sub else None
            else:
                return {eid_in: 1}
        return None

    @staticmethod
    def _parse_event_id(txt: str):
        s = (txt or "").strip()
        if s == "":
            return None
        # tenter dict
        try:
            # attention: eval sécurisé minimal
            d = eval(s, {"__builtins__": {}}, {})
            if isinstance(d, dict):
                return {str(k): int(v) for k, v in d.items()}
        except Exception:
            pass
        # tenter int
        try:
            return int(float(s))
        except Exception:
            pass
        # sinon string
        return s

    def _is_same_request(self, raw_obj: Any, params: Tuple, events_sig: Tuple[int, int]) -> bool:
        return (id(raw_obj) == self._last_in_id) and (params == self._last_params) and (events_sig == self._last_events_sig)

    # ------------- execute -------------
    def execute(self, in_data: Optional[Dict[str, Any]] = None, **kwargs) -> dict:
        """
        Supporte:
          - execute(in_data={...})
          - execute(raw=..., tmin=..., tmax=..., ...)
        Retourne toujours {}.
        """
        try:
            if in_data is None or not isinstance(in_data, dict):
                in_data = {}
            if kwargs:
                in_data.update(kwargs)

            raw = in_data.get("raw", None)
            if raw is None:
                self.outputs["epochs"].on_next(None)
                self.outputs["events"].on_next(None)
                if self._lbl_status: self._lbl_status.setText("No raw")
                return {}

            events_in = in_data.get("events", self.inputs["events"].value)
            event_id_in = in_data.get("event_id", self.inputs["event_id"].value)
            tmin = float(in_data.get("tmin", self.inputs["tmin"].value))
            tmax = float(in_data.get("tmax", self.inputs["tmax"].value))
            baseline = self._coerce_baseline(in_data.get("baseline", self.inputs["baseline"].value))
            picks_eeg_only = bool(in_data.get("picks_eeg_only", self.inputs["picks_eeg_only"].value))
            preload = bool(in_data.get("preload", self.inputs["preload"].value))
            detrend = in_data.get("detrend", self.inputs["detrend"].value)
            reject_by_annotation = bool(in_data.get("reject_by_annotation", self.inputs["reject_by_annotation"].value))
            if detrend not in (None, 0, 1):
                detrend = None

            # events / mapping
            ann_event_map = None
            if events_in is None:
                ev, eid = mne.events_from_annotations(raw, verbose=False)
                events_arr = ev if isinstance(ev, np.ndarray) else None
                ann_event_map = eid if isinstance(eid, dict) else None
            else:
                events_arr = events_in if isinstance(events_in, np.ndarray) else None

            events_sig = self._events_signature(events_arr)
            event_id_norm = self._normalize_event_id(event_id_in, ann_event_map)

            if events_arr is None or not isinstance(events_arr, np.ndarray) or events_arr.ndim != 2 or events_arr.shape[1] != 3 or events_arr.shape[0] == 0:
                if self._lbl_status: self._lbl_status.setText("No valid events")
                self.outputs["epochs"].on_next(None)
                self.outputs["events"].on_next(None)
                return {}

            picks = None
            if picks_eeg_only and hasattr(raw, "info"):
                try:
                    picks = mne.pick_types(raw.info, eeg=True, meg=False, eog=False, ecg=False, stim=False, misc=False, exclude=[])
                except Exception:
                    picks = None

            params = (float(tmin), float(tmax), baseline, bool(picks_eeg_only), bool(preload),
                      (detrend if detrend is None else int(detrend)), bool(reject_by_annotation),
                      tuple(sorted(event_id_norm.items())) if isinstance(event_id_norm, dict) else (event_id_norm,))
            if self._is_same_request(raw, params, events_sig):
                return {}

            epochs = mne.Epochs(
                raw=raw,
                events=events_arr,
                event_id=event_id_norm,
                tmin=tmin, tmax=tmax,
                baseline=baseline,
                picks=picks,
                preload=preload,
                detrend=detrend,
                reject_by_annotation=reject_by_annotation,
                verbose=False
            )

            self._last_in_id = id(raw)
            self._last_params = params
            self._last_events_sig = events_sig

            self.outputs["epochs"].on_next(epochs)
            self.outputs["events"].on_next(events_arr)
            if self._lbl_status:
                self._lbl_status.setText(f"Epochs: N={len(epochs)}  t=[{tmin},{tmax}]  baseline={baseline}")
        except Exception as e:
            try:
                print(f"[MNEEpochs] Error: {e}")
            except Exception:
                pass
            self.outputs["epochs"].on_next(None)
            self.outputs["events"].on_next(None)
        return {}