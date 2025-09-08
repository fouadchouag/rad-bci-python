# plugins/bci_online_metrics_node.py
# -*- coding: utf-8 -*-

import numpy as np
from rx.subject import BehaviorSubject
from collections import deque
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QSizePolicy, QStyle
from PyQt5.QtCore import Qt, QTimer

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


class BCI_OnlineMetrics(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'in': 'various'},
  'outputs': {'out': 'various'},
  'parameters': [ { 'default': 'default',
                    'desc': 'Routing/aggregation mode',
                    'name': 'mode',
                    'type': 'str'}],
  'summary': 'Métriques en ligne (rolling):',
  'usage': 'Drop in where coordination is needed.'}

    """
    Métriques en ligne (rolling):
      - accuracy sur la dernière fenêtre W
      - confusion cumulée depuis Reset

    Entrées:
      - pred_idx (int)
      - y_idx   (int)  ← markers-to-class
      - y_names (list[str], optionnel)
      - config_in (dict, optionnel)
      - online_metrics_conf (dict, optionnel)

    Sorties:
      - config_out: {"roll": int}
    """
    name = "BCI_OnlineMetrics"
    language = "Python"
    category = "BCI/Utils"

    def setup(self):
        # Inputs
        self.inputs["pred_idx"] = BehaviorSubject(None)
        self.inputs["y_idx"]    = BehaviorSubject(None)
        self.inputs["y_names"]  = BehaviorSubject(None)
        self.inputs["config_in"] = BehaviorSubject(None)
        self.inputs["online_metrics_conf"] = BehaviorSubject(None)

        # Outputs
        self.outputs["config_out"] = BehaviorSubject(None)

        # State
        self._K = 2
        self._y_names = [f"Class{i}" for i in range(self._K)]
        self._roll = 100
        self._q = deque(maxlen=self._roll)  # 1 si bon / 0 sinon
        self._cm = None

        # UI refs
        self._spn_roll = None
        self._lbl_head = None
        self._lbl_cm = None

        # UI update timer (évite maj UI depuis execute)
        self._ui_timer = None

    # ---------- config ----------
    def export_config(self) -> dict:
        return {"roll": int(self._roll)}

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        if "roll" in cfg:
            try:
                r = int(cfg["roll"])
                r = max(5, min(5000, r))
                if r != self._roll:
                    self._roll = r
                    old = list(self._q)[-self._roll:]
                    self._q = deque(old, maxlen=self._roll)
                    if self._spn_roll:
                        self._spn_roll.blockSignals(True)
                        self._spn_roll.setValue(self._roll)
                        self._spn_roll.blockSignals(False)
            except Exception:
                pass
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

        # Ligne de contrôles
        r0 = QHBoxLayout()
        btn = UiKit.make_btn("Reset", role="danger", icon_sp=QStyle.SP_BrowserStop)
        btn.clicked.connect(self._on_reset); r0.addWidget(btn)

        r0.addSpacing(10); r0.addWidget(QLabel("Window N:"))
        self._spn_roll = QSpinBox(); self._spn_roll.setRange(5, 5000); self._spn_roll.setValue(self._roll)
        self._spn_roll.valueChanged.connect(lambda v: self.import_config({"roll": int(v)}))
        r0.addWidget(self._spn_roll)
        r0.addStretch(1)
        v.addLayout(r0)

        # Labels
        self._lbl_head = QLabel("Waiting…")
        v.addWidget(self._lbl_head)

        self._lbl_cm = QLabel("")
        # Monospace + garder l'espacement (pour aligner joliment les colonnes)
        self._lbl_cm.setStyleSheet('font-family: "Courier New", monospace; white-space: pre;')
        self._lbl_cm.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self._lbl_cm)

        root.addWidget(CollapsibleSection("Online metrics (rolling)", panel, collapsed=False))

        # Timer UI (150 ms)
        self._ui_timer = QTimer(w)
        self._ui_timer.setInterval(150)
        self._ui_timer.timeout.connect(self._update_ui)
        self._ui_timer.start()

        # push initial config
        self._emit_config()
        return w

    def _on_reset(self):
        self._q.clear()
        self._cm = None
        if self._lbl_head: self._lbl_head.setText("Reset done.")
        if self._lbl_cm: self._lbl_cm.setText("")

    def _ensure_cm(self, K):
        if self._cm is None or self._cm.shape != (K, K):
            self._cm = np.zeros((K, K), dtype=int)

    def execute(self, **kw):
        # Merge config entrante
        merged = {}
        c1 = kw.get("config_in"); c2 = kw.get("online_metrics_conf")
        if isinstance(c1, dict): merged.update(c1)
        if isinstance(c2, dict): merged.update(c2)
        if merged: self.import_config(merged)

        # noms de classes (peuvent changer à chaud)
        yn = kw.get("y_names", None)
        if isinstance(yn, (list, tuple)) and len(yn) >= 2:
            if list(yn) != self._y_names:
                self._y_names = list(yn)
                self._K = len(self._y_names)
                # réinitialise CM si K change
                self._ensure_cm(self._K)

        # données
        p = kw.get("pred_idx", None)
        y = kw.get("y_idx", None)
        if p is None or y is None:
            return {}

        try:
            p = int(p); y = int(y)
        except Exception:
            return {}

        self._ensure_cm(self._K)
        if 0 <= y < self._K and 0 <= p < self._K:
            self._cm[y, p] += 1
            self._q.append(1 if p == y else 0)

        # Ne pas mettre à jour l'UI ici (thread-safe + débit). Le timer s'en charge.
        return {}

    # ---------- UI render (timer) ----------
    def _update_ui(self):
        # Rolling acc
        n = len(self._q)
        acc = (sum(self._q)/n) if n > 0 else 0.0
        if self._lbl_head:
            self._lbl_head.setText(f"Rolling acc (last {n}/{self._roll}): {acc:.3f}")

        # Confusion
        if self._lbl_cm:
            if self._cm is None:
                self._lbl_cm.setText("")
                return
            # format jolis
            K = self._cm.shape[0]
            names = self._y_names if isinstance(self._y_names, list) and len(self._y_names) == K else [f"Class{i}" for i in range(K)]
            # largeur colonne = max(len(nom), 4) + un peu d'espace
            colw = max(6, max(len(nm) for nm in names) + 1)
            # En-tête
            header = " " * (colw + 2) + " ".join(f"{nm:>{colw}s}" for nm in names)
            rows = [header]
            # Lignes
            for i in range(K):
                row_counts = " ".join(f"{int(self._cm[i, j]):>{colw}d}" for j in range(K))
                rows.append(f"{names[i]:>{colw}s} | {row_counts}")
            self._lbl_cm.setText("Confusion (cumul):\n" + "\n".join(rows))