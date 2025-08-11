# plugins/ball_feedback_plugin.py

from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QPushButton
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QBrush, QColor
from core.node_base import BasePlugin
import math
import time


class _BallCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pos = 0.5  # 0..1
        self.setMinimumHeight(120)

    def set_pos01(self, x):
        self._pos = max(0.0, min(1.0, float(x)))
        self.update()

    def pos01(self):
        return self._pos

    def paintEvent(self, _ev):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # fond
        p.fillRect(0, 0, w, h, QColor("#0b1020"))

        # piste
        margin = 24
        y = h // 2
        p.setPen(QPen(QColor("#4a5568"), 2))
        p.drawLine(margin, y, w - margin, y)

        # butées gauche/droite
        p.setBrush(QBrush(QColor("#2d3748")))
        p.setPen(Qt.NoPen)
        p.drawRect(0, y - 3, margin, 6)
        p.drawRect(w - margin, y - 3, margin, 6)

        # balle
        x = margin + self._pos * (w - 2 * margin)
        r = 14
        grad = QColor("#5eead4")  # cyan/vert
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#0ea5e9"), 1.5))
        p.drawEllipse(int(x - r), int(y - r), 2 * r, 2 * r)

        # repères %
        p.setPen(QPen(QColor("#64748b"), 1))
        for k in range(1, 4):
            xx = margin + k * (w - 2 * margin) / 4.0
            p.drawLine(int(xx), y - 8, int(xx), y + 8)


class BallFeedbackPlugin(BasePlugin):
    """
    Déplace une balle à gauche/droite selon la prédiction du classifieur.
    Entrées:
      - pred_label (str)
      - pred_conf (float 0..1)
    UI:
      - champs "Left class" / "Right class" (noms des classes du classifieur)
      - threshold (confiance minimale)
      - speed (vitesse)
      - buttons: Center / Test Left / Test Right
    """
    name = "BallFeedback"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        self.inputs["pred_label"] = BehaviorSubject(None)
        self.inputs["pred_conf"] = BehaviorSubject(None)

        # état
        self._current_label = None
        self._current_conf = 0.0
        self._left_name = "Left"
        self._right_name = "Right"
        self._threshold = 0.6
        self._speed = 0.6  # "écran par seconde"
        self._sim_dir = 0   # -1/0/+1 via boutons test
        self._last_tick = time.time()

        # UI refs
        self._canvas = None
        self._lbl = None
        self._in_left = None
        self._in_right = None
        self._spn_thr = None
        self._spn_speed = None

        # timer anim
        self._timer = QTimer()
        self._timer.setInterval(30)  # ~33 FPS
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    def build_widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # ligne mapping classes
        row_map = QHBoxLayout()
        row_map.addWidget(QLabel("Left class:"))
        self._in_left = QLineEdit(self._left_name)
        row_map.addWidget(self._in_left)
        row_map.addSpacing(8)
        row_map.addWidget(QLabel("Right class:"))
        self._in_right = QLineEdit(self._right_name)
        row_map.addWidget(self._in_right)
        row_map.addStretch(1)
        lay.addLayout(row_map)

        # ligne paramètres
        row_param = QHBoxLayout()
        row_param.addWidget(QLabel("Threshold:"))
        self._spn_thr = QDoubleSpinBox()
        self._spn_thr.setRange(0.0, 1.0)
        self._spn_thr.setSingleStep(0.05)
        self._spn_thr.setValue(self._threshold)
        self._spn_thr.valueChanged.connect(lambda v: setattr(self, "_threshold", float(v)))
        row_param.addWidget(self._spn_thr)

        row_param.addSpacing(8)
        row_param.addWidget(QLabel("Speed:"))
        self._spn_speed = QDoubleSpinBox()
        self._spn_speed.setRange(0.1, 3.0)
        self._spn_speed.setSingleStep(0.1)
        self._spn_speed.setValue(self._speed)
        self._spn_speed.valueChanged.connect(lambda v: setattr(self, "_speed", float(v)))
        row_param.addWidget(self._spn_speed)
        row_param.addStretch(1)
        lay.addLayout(row_param)

        # canvas
        self._canvas = _BallCanvas()
        lay.addWidget(self._canvas)

        # boutons actions
        row_btn = QHBoxLayout()
        btn_center = QPushButton("Center")
        btn_center.clicked.connect(lambda: self._canvas.set_pos01(0.5))
        btn_left = QPushButton("Test Left")
        btn_right = QPushButton("Test Right")
        btn_left.pressed.connect(lambda: self._set_sim(-1))
        btn_left.released.connect(lambda: self._set_sim(0))
        btn_right.pressed.connect(lambda: self._set_sim(+1))
        btn_right.released.connect(lambda: self._set_sim(0))
        row_btn.addWidget(btn_center)
        row_btn.addSpacing(6)
        row_btn.addWidget(btn_left)
        row_btn.addWidget(btn_right)
        row_btn.addStretch(1)
        lay.addLayout(row_btn)

        # status
        self._lbl = QLabel("No predictions")
        lay.addWidget(self._lbl)

        return w

    def execute(self, **kwargs):
        # MAJ des derniers résultats
        lab = kwargs.get("pred_label", None)
        conf = kwargs.get("pred_conf", None)
        if lab is not None:
            self._current_label = str(lab)
        if conf is not None:
            try:
                self._current_conf = float(conf)
            except Exception:
                self._current_conf = 0.0

        # MAJ noms classes depuis l'UI (si l'utilisateur change)
        if self._in_left:
            self._left_name = self._in_left.text().strip() or "Left"
        if self._in_right:
            self._right_name = self._in_right.text().strip() or "Right"

        # statut
        if self._lbl:
            self._lbl.setText(f"Pred: {self._current_label}  |  conf={self._current_conf:.2f}  |  thr={self._threshold:.2f}")

        return {}

    # ----------- anim -----------
    def _set_sim(self, d):
        self._sim_dir = int(d)

    def _on_tick(self):
        # dt
        now = time.time()
        dt = max(0.0, min(0.2, now - self._last_tick))  # clamp dt
        self._last_tick = now

        # direction issue du classifieur
        dir_from_pred = 0
        if self._current_label and self._current_conf >= self._threshold:
            if self._current_label == self._left_name:
                dir_from_pred = -1
            elif self._current_label == self._right_name:
                dir_from_pred = +1

        # simul / override boutons
        direction = self._sim_dir if self._sim_dir != 0 else dir_from_pred

        if direction != 0 and self._canvas:
            step = direction * self._speed * dt  # "écran par seconde"
            self._canvas.set_pos01(self._canvas.pos01() + step)
