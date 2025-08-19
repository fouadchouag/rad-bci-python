# plugins/bci_command_router.py
# -*- coding: utf-8 -*-

import time
from collections import deque
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QDoubleSpinBox,
    QSpinBox, QCheckBox, QSizePolicy, QStyle
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    from pylsl import StreamInfo, StreamOutlet, CF_STRING
    LSL_OK = True
except Exception:
    LSL_OK = False


_CMD2VEC = {
    "LEFT":  (-1.0,  0.0),
    "RIGHT": ( 1.0,  0.0),
    "UP":    ( 0.0, -1.0),
    "DOWN":  ( 0.0,  1.0),
    "STOP":  ( 0.0,  0.0),
}


class BCI_CommandRouter(BasePlugin):
    """
    Transforme les prédictions en commandes stables (LEFT/RIGHT/UP/DOWN/STOP)
    avec seuil de confiance, dwell, lissage majorité et période réfractaire.
    Peut émettre un stream LSL 'BCI_CMD' (type=Markers) lisible par la balle.

    Entrées:
      - pred_idx  : int
      - pred_conf : float (optionnel)
      - proba     : dict (optionnel)
      - pred_label: str (optionnel)

    Sorties:
      - command: str
      - dx, dy: floats
    """
    name = "BCI_CommandRouter"
    language = "Python"
    category = "BCI/Control"

    def setup(self):
        self.inputs["pred_idx"]   = BehaviorSubject(None)
        self.inputs["pred_conf"]  = BehaviorSubject(None)
        self.inputs["proba"]      = BehaviorSubject(None)
        self.inputs["pred_label"] = BehaviorSubject(None)

        self.outputs["command"] = BehaviorSubject(None)
        self.outputs["dx"] = BehaviorSubject(0.0)
        self.outputs["dy"] = BehaviorSubject(0.0)

        self._map_text = "0:LEFT; 1:RIGHT; 2:UP; 3:DOWN; *:STOP"
        self._conf_thr = 0.60
        self._dwell_ms = 300
        self._refr_ms  = 500
        self._smooth_N = 3
        self._nc_idx   = -1
        self._emit_lsl = True

        self._history = deque(maxlen=20)   # (t, idx, conf)
        self._last_emit_t = 0.0
        self._current_cmd = "STOP"

        self._outlet = None

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Mapping (idx:CMD; ...):"))
        ed = QLineEdit(self._map_text)
        ed.textChanged.connect(lambda t: setattr(self, "_map_text", t))
        r0.addWidget(ed, 1)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("conf_thr:"))
        spc = QDoubleSpinBox(); spc.setRange(0.0, 1.0); spc.setSingleStep(0.01); spc.setDecimals(2); spc.setValue(self._conf_thr)
        spc.valueChanged.connect(lambda x: setattr(self, "_conf_thr", float(x))); r1.addWidget(spc)

        r1.addSpacing(8); r1.addWidget(QLabel("dwell [ms]:"))
        spd = QSpinBox(); spd.setRange(0, 5000); spd.setValue(self._dwell_ms)
        spd.valueChanged.connect(lambda v: setattr(self, "_dwell_ms", int(v))); r1.addWidget(spd)

        r1.addSpacing(8); r1.addWidget(QLabel("refractory [ms]:"))
        spr = QSpinBox(); spr.setRange(0, 5000); spr.setValue(self._refr_ms)
        spr.valueChanged.connect(lambda v: setattr(self, "_refr_ms", int(v))); r1.addWidget(spr)

        r1.addSpacing(8); r1.addWidget(QLabel("smooth N:"))
        sps = QSpinBox(); sps.setRange(1, 15); sps.setValue(self._smooth_N)
        sps.valueChanged.connect(lambda v: setattr(self, "_smooth_N", int(v))); r1.addWidget(sps)

        r1.addSpacing(8); r1.addWidget(QLabel("NC idx:"))
        spn = QSpinBox(); spn.setRange(-1, 50); spn.setValue(self._nc_idx)
        spn.valueChanged.connect(lambda v: setattr(self, "_nc_idx", int(v))); r1.addWidget(spn)
        r1.addStretch(1)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        ck = QCheckBox("Emit LSL (name='BCI_CMD', type='Markers')")
        ck.setChecked(self._emit_lsl); ck.toggled.connect(self._toggle_lsl)
        r2.addWidget(ck)
        lbl = QLabel("LSL: " + ("OK" if LSL_OK else "missing"))
        r2.addWidget(lbl); r2.addStretch(1)
        v.addLayout(r2)

        root.addWidget(CollapsibleSection("Command Router", panel, collapsed=False))
        return w

    # LSL outlet toggle
    def _toggle_lsl(self, s):
        self._emit_lsl = bool(s)
        if not self._emit_lsl:
            self._outlet = None
            return
        if self._outlet is None and LSL_OK:
            try:
                info = StreamInfo(name="BCI_CMD", type="Markers", channel_count=1,
                                  nominal_srate=0.0, channel_format=CF_STRING, source_id="bci_cmd_router")
                self._outlet = StreamOutlet(info)
            except Exception:
                self._outlet = None

    def _parse_map(self):
        d={}
        for tok in (self._map_text or "").split(";"):
            tok = tok.strip()
            if not tok or ":" not in tok: continue
            k,v = tok.split(":",1)
            k = k.strip(); v = (v or "").strip().upper()
            d[k] = v
        if "*" not in d: d["*"]="STOP"
        return d

    @staticmethod
    def _majority_idx(items):
        if not items: return None
        counts = {}
        for i in items:
            counts[i] = counts.get(i, 0) + 1
        return max(counts.items(), key=lambda kv: kv[1])[0]

    def _emit_cmd(self, cmd):
        self._current_cmd = cmd
        dx,dy = _CMD2VEC.get(cmd, (0.0,0.0))
        try:
            self.outputs["command"].on_next(cmd)
            self.outputs["dx"].on_next(float(dx))
            self.outputs["dy"].on_next(float(dy))
        except Exception:
            pass
        if self._emit_lsl and self._outlet is not None:
            try:
                self._outlet.push_sample([cmd])
            except Exception:
                pass

    def execute(self, **kw):
        idx = kw.get("pred_idx", None)
        conf = kw.get("pred_conf", None)
        proba = kw.get("proba", None)

        if idx is None:
            return {}

        t = time.time()
        # confiance
        c = None
        try:
            c = float(conf) if conf is not None else None
        except Exception:
            c = None
        if (c is None) and isinstance(proba, dict) and proba:
            try:
                c = float(max(proba.values()))
            except Exception:
                c = None

        # seuil
        if (c is not None) and (c < float(self._conf_thr)):
            idx_eff = self._nc_idx if self._nc_idx >= 0 else None
        else:
            try:
                idx_eff = int(idx)
            except Exception:
                idx_eff = None

        # history
        self._history.append((t, idx_eff, c if c is not None else 1.0))

        # réfractaire
        if (t - self._last_emit_t) * 1000.0 < self._refr_ms:
            return {}

        # dwell
        dwell = self._dwell_ms / 1000.0
        items = [ii for (tt,ii,cc) in self._history if (t-tt) <= dwell]
        if len(items) == 0:
            return {}

        # majorité (sur derniers N valides)
        last_valid = [ii for (tt,ii,cc) in reversed(self._history) if ii is not None]
        if len(last_valid) == 0:
            if self._current_cmd != "STOP":
                self._emit_cmd("STOP")
                self._last_emit_t = t
            return {}

        maj = BCI_CommandRouter._majority_idx(last_valid[:max(1,self._smooth_N)])

        # mapping
        mapping = self._parse_map()
        cmd = mapping.get(str(maj), mapping.get("*","STOP"))

        # émettre si changement
        if cmd != self._current_cmd:
            self._emit_cmd(cmd)
            self._last_emit_t = t

        return {}
