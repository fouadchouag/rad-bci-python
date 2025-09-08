# plugins/bci_ball_controller.py
# -*- coding: utf-8 -*-

import math, numpy as np, sip
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QPainter, QBrush, QPen
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDoubleSpinBox,
    QPushButton, QSizePolicy, QStyle, QCheckBox
)

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

ACTIONS = ["Idle","Left","Right","Up","Down"]


class _BallCanvas(QWidget):
   

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 160)
        self.w, self.h = 480, 280
        self.x, self.y = self.w/2, self.h/2
        self.vx, self.vy = 0.0, 0.0
        self.ball_r = 14.0

    def sizeHint(self):
        return self.minimumSize()

    def reset(self):
        self.x, self.y = self.w/2, self.h/2
        self.vx, self.vy = 0.0, 0.0
        self.update()

    def step(self, ax, ay, speed, friction):
        self.vx += ax * speed
        self.vy += ay * speed
        self.vx *= friction
        self.vy *= friction
        self.x += self.vx
        self.y += self.vy
        r = self.ball_r
        if self.x < r: self.x, self.vx = r, 0.0
        if self.y < r: self.y, self.vy = r, 0.0
        if self.x > self.w-r: self.x, self.vx = self.w-r, 0.0
        if self.y > self.h-r: self.y, self.vy = self.h-r, 0.0
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        p.fillRect(rect, QBrush(Qt.white))
        area = QRectF(10, 10, rect.width()-20, rect.height()-20)
        p.setPen(QPen(Qt.lightGray, 1))
        p.drawRect(area)
        sx = area.x() + (self.x / self.w) * area.width()
        sy = area.y() + (self.y / self.h) * area.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(Qt.gray))
        p.drawEllipse(QRectF(sx-self.ball_r, sy-self.ball_r, 2*self.ball_r, 2*self.ball_r))
        p.end()


class BCI_BallController(BasePlugin):
    """
    Contrôle une balle 2D à partir de pred_idx / proba.

    Entrées:
      - pred_idx (int)
      - proba (dict[str->float]) (optionnel)
      - y_names (list[str])      (optionnel)
      - config_in (dict, optionnel)
      - ball_controller_conf (dict, optionnel)

    Sorties:
      - (UI) — et config_out (dict):
        { K, map, speed, friction, prob_gain, use_prob }
    """

    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'Contrôle une balle 2D à partir de pred_idx / proba.',
  'usage': 'Wire upstream data and route downstream.'}
    

    name = "BCI_BallController"
    language = "Python"
    category = "BCI/Feedback"

    def setup(self):
        self.inputs["pred_idx"] = BehaviorSubject(None)
        self.inputs["proba"]    = BehaviorSubject(None)
        self.inputs["y_names"]  = BehaviorSubject(None)
        self.inputs["config_in"] = BehaviorSubject(None)
        self.inputs["ball_controller_conf"] = BehaviorSubject(None)

        self.outputs["config_out"] = BehaviorSubject(None)

        self._canvas = None
        self._lbl = None

        self._K = 2
        self._y_names = ["Left","Right"]

        self._map = ["Left","Right"]  # par défaut 2 classes
        self._speed = 0.8
        self._friction = 0.92
        self._prob_gain = 1.0
        self._use_prob = True

        self._last_pred = None
        self._last_proba = None

        self._timer = None  # sera parenté au widget UI

        # UI refs pour synchro config
        self._map_row = None
        self._map_cmbs = []
        self._spn_speed = None
        self._spn_friction = None
        self._spn_gain = None
        self._ck_use_prob = None

    # ---------- CONFIG ----------
    def export_config(self) -> dict:
        return {
            "K": int(self._K),
            "map": list(self._map),
            "speed": float(self._speed),
            "friction": float(self._friction),
            "prob_gain": float(self._prob_gain),
            "use_prob": bool(self._use_prob),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        if "K" in cfg:
            try:
                K = int(cfg["K"])
                if K >= 1:
                    self._K = K
            except Exception:
                pass
        if "map" in cfg and isinstance(cfg["map"], (list, tuple)):
            m = [str(x) if str(x) in ACTIONS else "Idle" for x in cfg["map"]]
            if len(m) >= 1:
                self._map = list(m[:self._K]) + (["Idle"] * max(0, self._K - len(m)))
        if "speed" in cfg:
            try: self._speed = float(cfg["speed"])
            except Exception: pass
        if "friction" in cfg:
            try: self._friction = float(cfg["friction"])
            except Exception: pass
        if "prob_gain" in cfg:
            try: self._prob_gain = float(cfg["prob_gain"])
            except Exception: pass
        if "use_prob" in cfg:
            self._use_prob = bool(cfg["use_prob"])

        # sync UI si déjà construit
        if self._map_row is not None:
            self._rebuild_mapping_ui()
        if self._spn_speed: self._spn_speed.setValue(self._speed)
        if self._spn_friction: self._spn_friction.setValue(self._friction)
        if self._spn_gain: self._spn_gain.setValue(self._prob_gain)
        if self._ck_use_prob: self._ck_use_prob.setChecked(self._use_prob)

        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # mapping dynamique
        self._map_row = QVBoxLayout(); v.addLayout(self._map_row)
        self._rebuild_mapping_ui()

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("speed:"))
        self._spn_speed = QDoubleSpinBox(); self._spn_speed.setRange(0.0, 10.0); self._spn_speed.setDecimals(2); self._spn_speed.setSingleStep(0.1); self._spn_speed.setValue(self._speed)
        self._spn_speed.valueChanged.connect(lambda x: (setattr(self, "_speed", float(x)), self._emit_config())); r1.addWidget(self._spn_speed)

        r1.addSpacing(10); r1.addWidget(QLabel("friction:"))
        self._spn_friction = QDoubleSpinBox(); self._spn_friction.setRange(0.80, 0.999); self._spn_friction.setDecimals(3); self._spn_friction.setSingleStep(0.01); self._spn_friction.setValue(self._friction)
        self._spn_friction.valueChanged.connect(lambda x: (setattr(self, "_friction", float(x)), self._emit_config())); r1.addWidget(self._spn_friction)

        r1.addSpacing(10); r1.addWidget(QLabel("prob_gain:"))
        self._spn_gain = QDoubleSpinBox(); self._spn_gain.setRange(0.0, 5.0); self._spn_gain.setDecimals(2); self._spn_gain.setSingleStep(0.1); self._spn_gain.setValue(self._prob_gain)
        self._spn_gain.valueChanged.connect(lambda x: (setattr(self, "_prob_gain", float(x)), self._emit_config())); r1.addWidget(self._spn_gain)

        self._ck_use_prob = QCheckBox("use proba"); self._ck_use_prob.setChecked(self._use_prob)
        self._ck_use_prob.toggled.connect(lambda s: (setattr(self, "_use_prob", bool(s)), self._emit_config())); r1.addWidget(self._ck_use_prob)

        btn_reset = UiKit.make_btn("Reset", role="ghost", icon_sp=QStyle.SP_BrowserReload)
        btn_reset.clicked.connect(self._reset_canvas); r1.addWidget(btn_reset)
        r1.addStretch(1); v.addLayout(r1)

        self._lbl = QLabel("Waiting predictions…")
        v.addWidget(self._lbl)

        self._canvas = _BallCanvas(parent=w)
        root.addWidget(CollapsibleSection("Ball controller (2D)", panel, collapsed=False))
        root.addWidget(self._canvas)

        # --- TIMER sécurisé : parenté au widget, arrêt auto à la destruction
        self._timer = QTimer(parent=w)
        self._timer.setInterval(33)  # ~30 FPS
        self._timer.timeout.connect(self._on_tick_safe)
        self._timer.start()
        w.destroyed.connect(self._on_widget_destroyed)

        # émettre la config initiale
        self._emit_config()
        return w

    # ==== safety ====
    def _on_widget_destroyed(self, *args):
        try:
            if self._timer and self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        self._timer = None
        self._canvas = None
        self._lbl = None

    def __del__(self):
        try:
            if self._timer and self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass

    # ==== UI helpers ====
    def _reset_canvas(self):
        c = self._canvas
        if c is not None and not sip.isdeleted(c):
            c.reset()
        if self._lbl:
            self._lbl.setText("reset")

    def _rebuild_mapping_ui(self):
        # purge
        self._map_cmbs = []
        if self._map_row is None:
            return
        while self._map_row.count():
            it = self._map_row.takeAt(0); w = it.widget()
            if w: w.deleteLater()
        # ajuste map à K
        if len(self._map) != self._K:
            base = ["Left","Right","Up","Down","Idle"]
            self._map = [(base[i] if i < len(base) else "Idle") for i in range(self._K)]
        # rebuild
        for i in range(self._K):
            r = QHBoxLayout()
            r.addWidget(QLabel(f"class {i}:"))
            cmb = QComboBox(); cmb.addItems(ACTIONS); cmb.setCurrentText(self._map[i])
            cmb.currentTextChanged.connect(lambda s, idx=i: self._set_map(idx, s))
            r.addWidget(cmb); r.addStretch(1)
            self._map_cmbs.append(cmb)
            wrap = QWidget(); lw = QVBoxLayout(wrap); lw.setContentsMargins(0,0,0,0); lw.setSpacing(0); lw.addLayout(r)
            self._map_row.addWidget(wrap)

    def _set_map(self, idx, action):
        if 0 <= idx < len(self._map):
            self._map[idx] = action
            self._emit_config()

    def _set_status(self, msg):
        if self._lbl and (not sip.isdeleted(self._lbl)):
            self._lbl.setText(msg)

    # ==== logique ====
    def _cmd_from_pred(self, pred_idx, proba_dict):
        if pred_idx is None or not (0 <= pred_idx < self._K):
            return 0.0, 0.0
        action = self._map[pred_idx]
        ax, ay = 0.0, 0.0
        if action == "Left":  ax = -1.0
        elif action == "Right": ax = +1.0
        elif action == "Up":    ay = -1.0
        elif action == "Down":  ay = +1.0
        if self._use_prob and isinstance(proba_dict, dict):
            try:
                ks = list(proba_dict.keys())
                ps = np.array([float(proba_dict[k]) for k in ks], float)
                psel = float(ps[pred_idx]) if pred_idx < len(ps) else 1.0
                pbg  = float((np.sum(ps) - psel) / max(1, len(ps)-1))
                g = max(0.0, psel - pbg) * self._prob_gain
            except Exception:
                g = 1.0
            ax *= g; ay *= g
        return ax, ay

    def _on_tick_safe(self):
        c = self._canvas
        if c is None or sip.isdeleted(c):
            if self._timer and self._timer.isActive():
                self._timer.stop()
            return
        pred = self._last_pred
        proba = self._last_proba
        ax, ay = self._cmd_from_pred(pred, proba)
        c.step(ax, ay, self._speed, self._friction)

    def execute(self, **kw):
        # merge config
        merged = {}
        c1 = kw.get("config_in"); c2 = kw.get("ball_controller_conf")
        if isinstance(c1, dict): merged.update(c1)
        if isinstance(c2, dict): merged.update(c2)
        if merged: self.import_config(merged)

        # y_names → K
        yn = kw.get("y_names", None)
        if isinstance(yn, (list, tuple)) and len(yn) >= 1:
            if self._y_names != list(yn):
                self._y_names = list(yn)
                self._K = len(self._y_names)
                if self._map_row is not None:
                    self._rebuild_mapping_ui()
                self._emit_config()

        p = kw.get("pred_idx", None)
        if p is not None:
            try: self._last_pred = int(p)
            except Exception: pass

        pr = kw.get("proba", None)
        if isinstance(pr, dict):
            self._last_proba = pr

        if self._lbl and (not sip.isdeleted(self._lbl)):
            self._lbl.setText(f"pred={self._last_pred} | map={self._map} | speed={self._speed:.2f}, fric={self._friction:.3f}")
        return {}