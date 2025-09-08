# plugins/markers_to_classidx.py
# -*- coding: utf-8 -*-

import re, time, numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QDoubleSpinBox, QSpinBox, QSizePolicy, QStyle, QCheckBox
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


class MarkersToClassIdx(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'Convertit des marqueurs LSL (strings) en y_idx (int) et y_name (str).',
  'usage': 'Wire upstream data and route downstream.'}

    """
    Convertit des marqueurs LSL (strings) en y_idx (int) et y_name (str).

    Entrées:
      - events : list[{'ts': float, 'code': str}]

    Entrées config:
      - config_in (dict)
      - markers_conf (dict)

    Sorties:
      - y_idx, y_name, K, last_event
      - config_out (dict)

    UI:
      - scenario: MI / P300 / SSVEP / Custom
      - mapping (MI/P300/Custom): "code:idx; code:idx; ..."
      - SSVEP freqs: "10,12,15" (classe = index)
      - hold_sec
    """
    name = "MarkersToClassIdx"
    language = "Python"
    category = "BCI/Utils"

    def setup(self):
        self.inputs["events"] = BehaviorSubject(None)
        # config pins
        self.inputs["config_in"]   = BehaviorSubject(None)
        self.inputs["markers_conf"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        self.outputs["y_idx"] = BehaviorSubject(None)
        self.outputs["y_name"] = BehaviorSubject(None)
        self.outputs["K"] = BehaviorSubject(None)
        self.outputs["last_event"] = BehaviorSubject(None)

        # state / ui
        self._scenario = "MI"          # "MI" | "P300" | "SSVEP" | "Custom"
        self._map_text = "769:0; 770:1; 771:2; 772:3"  # for MI/P300/Custom
        self._ssvep_freqs = "10,12,15"
        self._hold_sec = 4.0
        self._auto_reset_on_idle = True

        self._class_names = []  # optional names
        self._current_idx = None
        self._current_until = 0.0

        # ui refs
        self._lbl = None
        self._cmb = None
        self._ed_map = None
        self._ed_freqs = None
        self._sp_hold = None
        self._ck_idle = None

        self._emit_config()

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        return {
            "scenario": self._scenario,
            "map": self._map_text,
            "ssvep_freqs": self._ssvep_freqs,
            "hold_sec": float(self._hold_sec),
            "auto_reset_on_idle": bool(self._auto_reset_on_idle),
            "class_names": list(self._class_names) if self._class_names else None
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        src = cfg
        nodes = cfg.get("nodes") if isinstance(cfg.get("nodes"), dict) else None
        if nodes and isinstance(nodes.get(self.name), dict):
            src = nodes[self.name]

        if "scenario" in src:
            self._scenario = str(src["scenario"])
            if self._cmb:
                i = self._cmb.findText(self._scenario)
                if i >= 0:
                    self._cmb.setCurrentIndex(i)
        if "map" in src:
            self._map_text = str(src["map"])
            if self._ed_map:
                self._ed_map.setText(self._map_text)
        if "ssvep_freqs" in src:
            self._ssvep_freqs = str(src["ssvep_freqs"])
            if self._ed_freqs:
                self._ed_freqs.setText(self._ssvep_freqs)
        if "hold_sec" in src:
            self._hold_sec = float(src["hold_sec"])
            if self._sp_hold:
                self._sp_hold.setValue(self._hold_sec)
        if "auto_reset_on_idle" in src:
            self._auto_reset_on_idle = bool(src["auto_reset_on_idle"])
            if self._ck_idle:
                self._ck_idle.setChecked(self._auto_reset_on_idle)
        if "class_names" in src and isinstance(src["class_names"], (list, tuple)):
            self._class_names = [str(s) for s in src["class_names"]]

        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- UI ----------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Scenario:"))
        self._cmb = QComboBox(); self._cmb.addItems(["MI","P300","SSVEP","Custom"])
        self._cmb.setCurrentText(self._scenario)
        self._cmb.currentIndexChanged.connect(lambda i: (setattr(self,"_scenario", self._cmb.itemText(i)), self._emit_config()))
        r0.addWidget(self._cmb); r0.addStretch(1)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Mapping (code:idx; ...):"))
        self._ed_map = QLineEdit(self._map_text)
        r1.addWidget(self._ed_map, 1)
        self._ed_map.textChanged.connect(lambda t: (setattr(self,"_map_text", t), self._emit_config()))
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("SSVEP freqs (Hz csv):"))
        self._ed_freqs = QLineEdit(self._ssvep_freqs)
        self._ed_freqs.textChanged.connect(lambda t: (setattr(self,"_ssvep_freqs", t), self._emit_config()))
        r2.addWidget(self._ed_freqs, 1)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        r3.addWidget(QLabel("Hold [s]:"))
        self._sp_hold = QDoubleSpinBox(); self._sp_hold.setRange(0.0, 30.0); self._sp_hold.setDecimals(2); self._sp_hold.setValue(self._hold_sec)
        self._sp_hold.valueChanged.connect(lambda v: (setattr(self,"_hold_sec", float(v)), self._emit_config()))
        r3.addWidget(self._sp_hold)

        self._ck_idle = QCheckBox("Reset to None after hold")
        self._ck_idle.setChecked(self._auto_reset_on_idle)
        self._ck_idle.toggled.connect(lambda s: (setattr(self, "_auto_reset_on_idle", bool(s)), self._emit_config()))
        r3.addWidget(self._ck_idle)

        r3.addStretch(1)
        v.addLayout(r3)

        self._lbl = QLabel("Idle"); v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("Markers → ClassIdx", panel, collapsed=False))
        return w

    # ------------- runtime -------------
    def execute(self, **kw):
        # merge config
        merged = {}
        for k in ("config_in", "markers_conf"):
            blk = kw.get(k, None)
            if isinstance(blk, dict):
                merged.update(blk)
        if merged:
            self.import_config(merged)

        events = kw.get("events", None)
        tnow = time.time()

        # expire hold
        if self._current_idx is not None and tnow > self._current_until and self._hold_sec > 0:
            if self._auto_reset_on_idle:
                self._current_idx = None
                self.outputs["y_idx"].on_next(None)
                self.outputs["y_name"].on_next(None)

        if not events:
            return {}

        # traiter la rafale reçue depuis le dernier tick
        last = None
        for ev in events:
            code = str(ev.get("code", ""))
            last = ev
            self._handle_code(code, ev.get("ts", None))

        self.outputs["last_event"].on_next(last)
        return {}

    # ------------- helpers -------------
    def _parse_map(self):
        d={}
        for tok in (self._map_text or "").split(";"):
            tok = tok.strip()
            if not tok or ":" not in tok:
                continue
            k,v = tok.split(":",1)
            k = k.strip(); v = v.strip()
            try:
                d[k] = int(v)
            except Exception:
                pass
        return d

    def _ssvep_list(self):
        try:
            return [float(x.strip()) for x in (self._ssvep_freqs or "").split(",") if x.strip()!=""]
        except Exception:
            return [10.0,12.0,15.0]

    def _handle_code(self, code, ts):
        scen = self._scenario
        idx = None; name = None

        if scen == "MI":
            d = self._parse_map()
            if not d: d = {"769":0,"770":1,"771":2,"772":3}
            if code in d:
                idx = d[code]
                default_names = {0:"Left",1:"Right",2:"Feet",3:"Tongue"}
                name = (self._class_names[idx] if (self._class_names and idx < len(self._class_names)) else default_names.get(idx, f"Class{idx}"))
                self._apply(idx, name)
        elif scen == "P300":
            d = self._parse_map()
            if not d: d = {"NT":0,"TGT":1}
            if code in d:
                idx = d[code]
                name = "TGT" if idx==1 else "NT"
                self._apply(idx, name, hold=False)
        elif scen == "SSVEP":
            m = re.match(r"FREQ[_\- ]?([0-9]+(\.[0-9]+)?)", code.upper())
            if m:
                f = float(m.group(1))
                freqs = self._ssvep_list()
                try:
                    arr = np.asarray(freqs, float)
                    j = int(np.argmin(np.abs(arr - f)))
                    if abs(arr[j]-f) <= 0.25:
                        idx = j; name = f"{arr[j]:.2f}Hz"
                        self._apply(idx, name)
                except Exception:
                    pass
        else:
            d = self._parse_map()
            if code in d:
                idx = d[code]; name = f"Class{idx}"
                self._apply(idx, name)

        if idx is not None and self._lbl:
            self._lbl.setText(f"Event '{code}' → y={idx} ({name})")

    def _apply(self, idx, name, hold=True):
        self._current_idx = int(idx)
        self.outputs["y_idx"].on_next(self._current_idx)
        self.outputs["y_name"].on_next(str(name))
        if hold and self._hold_sec > 0:
            self._current_until = time.time() + float(self._hold_sec)
        else:
            self._current_until = 0.0
        # K estimé (info)
        if "MI" in self._scenario:
            self.outputs["K"].on_next(4)
        elif "P300" in self._scenario:
            self.outputs["K"].on_next(2)
        elif "SSVEP" in self._scenario:
            self.outputs["K"].on_next(len(self._ssvep_list()))
        else:
            d = self._parse_map()
            if d:
                self.outputs["K"].on_next(1 + max(d.values()))