# plugins/online_metrics_node.py
# -*- coding: utf-8 -*-

import numpy as np
from collections import deque
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QCheckBox,
    QSizePolicy, QStyle
)
from core.node_base import BasePlugin
        # Assure-toi que ces deux fichiers existent déjà chez toi :
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


def _alive(w):
    try:
        import sip
        return (w is not None) and (not sip.isdeleted(w))
    except Exception:
        return w is not None


def _cohen_kappa(conf):
    conf = np.asarray(conf, float)
    N = conf.sum()
    if N <= 0:
        return 0.0
    po = np.trace(conf) / N
    pe = (conf.sum(axis=0) * conf.sum(axis=1)).sum() / (N * N)
    denom = (1.0 - pe)
    if denom <= 1e-12:
        return 0.0
    return float((po - pe) / denom)


class OnlineMetrics(BasePlugin):
    help = help = { 'gotchas': [
                 'Both pred_idx and y_idx must be non-negative integers; negative values are silently ignored.',
                 'Auto-K only expands K when new indices appear; use Reset to shrink back.',
                 'Confusion matrix output is a copy — safe to mutate externally.',
                 'Cohen\'s kappa returns 0.0 when total samples are zero or agreement is at chance level.'],
  'inputs': {'pred_idx': 'int — predicted class index (non-negative)',
             'y_idx': 'int — ground truth class index (non-negative)'},
  'outputs': {'metrics': 'dict — {acc_window, acc_cum, kappa, n_total, window_size, K}',
              'confusion': 'np.ndarray (K,K) — cumulative confusion matrix (copy)'},
  'parameters': [ { 'default': 200,
                    'desc': 'Rolling accuracy window size',
                    'name': 'win_N',
                    'type': 'int'},
                  { 'default': True,
                    'desc': 'Automatically expand K when new class indices appear',
                    'name': 'auto_K',
                    'type': 'bool'},
                  { 'default': 4,
                    'desc': 'Number of classes (used when auto_K is off)',
                    'name': 'K',
                    'type': 'int'}],
  'summary': 'Computes online metrics by comparing pred_idx vs y_idx: rolling accuracy '
             '(window N), cumulative accuracy, Cohen\'s kappa, and cumulative confusion matrix. '
             'Auto-expands K when new class indices appear.',
  'usage': 'Connect pred_idx from classifier and y_idx from ground truth marker. '
           'Outputs a metrics dict and confusion matrix for downstream display or logging.'}

    """
    Compare en ligne pred_idx vs y_idx et calcule:
      - accuracy roulante (fenêtre N)
      - accuracy cumulée
      - Cohen's kappa
      - matrice de confusion (cumulative)

    Entrées:
      - pred_idx : int (prédiction courante)
      - y_idx    : int (vérité terrain courante)

    Sorties:
      - metrics : dict {
            "acc_window": float,
            "acc_cum": float,
            "kappa": float,
            "n_total": int,
            "window_size": int,
            "K": int,
        }
      - confusion : np.ndarray (K,K) cumulative
    """
    name = "OnlineMetrics"
    language = "Python"
    category = "BCI/Utils"

    def setup(self):
        self.inputs["pred_idx"] = BehaviorSubject(None)
        self.inputs["y_idx"]    = BehaviorSubject(None)

        self.outputs["metrics"]   = BehaviorSubject(None)
        self.outputs["confusion"] = BehaviorSubject(None)

        self._win_N = 200          # taille fenêtre roulante
        self._auto_K = True        # augmente K auto si nouveaux indices
        self._K = 4                # K min si auto-K désactivé
        self._pairs = deque(maxlen=self._win_N)
        self._conf = np.zeros((self._K, self._K), dtype=int)
        self._n_total = 0

        self._lbl_main = None
        self._lbl_cum  = None

    def build_widget(self):
        w = QWidget()
        UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Window size (N):"))
        spN = QSpinBox(); spN.setRange(10, 100000); spN.setValue(self._win_N)
        spN.valueChanged.connect(self._on_change_win)
        r0.addWidget(spN)

        ck_auto = QCheckBox("Auto-K (expand)")
        ck_auto.setChecked(self._auto_K)
        ck_auto.toggled.connect(self._on_toggle_autoK)
        r0.addWidget(ck_auto)

        r0.addWidget(QLabel("K (if auto-K off):"))
        spK = QSpinBox(); spK.setRange(2, 50); spK.setValue(self._K)
        spK.valueChanged.connect(self._on_change_k)
        r0.addWidget(spK)

        btn_reset = UiKit.make_btn("Reset", role="danger", icon_sp=QStyle.SP_BrowserStop)
        btn_reset.clicked.connect(self._on_reset)
        r0.addWidget(btn_reset)
        r0.addStretch(1)
        v.addLayout(r0)

        self._lbl_main = QLabel("acc_window=— | acc_cum=— | kappa=— | n=0 | K=4")
        v.addWidget(self._lbl_main)
        self._lbl_cum  = QLabel("Confusion: empty")
        v.addWidget(self._lbl_cum)

        root.addWidget(CollapsibleSection("Online Metrics", panel, collapsed=False))
        return w

    # UI handlers
    def _on_change_win(self, val):
        self._win_N = int(val)
        self._pairs = deque(self._pairs, maxlen=self._win_N)

    def _on_toggle_autoK(self, s):
        self._auto_K = bool(s)

    def _on_change_k(self, val):
        if self._auto_K:
            return
        newK = int(val)
        if newK != self._K:
            self._resize_conf(newK)

    def _on_reset(self):
        self._pairs.clear()
        self._n_total = 0
        self._conf = np.zeros((self._K, self._K), dtype=int)
        self._emit()

    # runtime
    def execute(self, **kw):
        p = kw.get("pred_idx", None)
        y = kw.get("y_idx", None)
        if p is None or y is None:
            return {}
        try:
            p = int(p); y = int(y)
        except Exception:
            return {}
        if p < 0 or y < 0:
            return {}

        # auto-K
        max_idx = max(p, y)
        if self._auto_K and (max_idx >= self._K):
            self._resize_conf(max_idx + 1)
        if p >= self._K or y >= self._K:
            return {}

        self._pairs.append((p, y))
        self._conf[y, p] += 1
        self._n_total += 1

        acc_window = self._acc_window()
        acc_cum = float(np.trace(self._conf) / max(1, self._conf.sum()))
        kappa = _cohen_kappa(self._conf)

        if _alive(self._lbl_main):
            self._lbl_main.setText(
                f"acc_window={acc_window:.3f} | acc_cum={acc_cum:.3f} | kappa={kappa:.3f} | n={self._n_total} | K={self._K}"
            )
        if _alive(self._lbl_cum):
            cm = self._conf
            rows = [" ".join(f"{v:5d}" for v in cm[i]) for i in range(min(self._K, 8))]
            self._lbl_cum.setText("Confusion (rows=true, cols=pred):\n" + "\n".join(rows))

        metrics = {
            "acc_window": float(acc_window),
            "acc_cum": float(acc_cum),
            "kappa": float(kappa),
            "n_total": int(self._n_total),
            "window_size": int(self._win_N),
            "K": int(self._K),
        }
        self.outputs["metrics"].on_next(metrics)
        self.outputs["confusion"].on_next(self._conf.copy())
        return {}

    # helpers
    def _resize_conf(self, newK: int):
        newK = int(max(2, newK))
        if newK == self._K:
            return
        conf2 = np.zeros((newK, newK), dtype=int)
        kmin = min(self._K, newK)
        conf2[:kmin, :kmin] = self._conf[:kmin, :kmin]
        self._conf = conf2
        self._K = newK

    def _acc_window(self):
        if len(self._pairs) == 0:
            return 0.0
        ok = sum(1 for (p, y) in self._pairs if p == y)
        return ok / float(len(self._pairs))

    def _emit(self):
        acc_cum = float(np.trace(self._conf) / max(1, self._conf.sum()))
        kappa = _cohen_kappa(self._conf)
        metrics = {
            "acc_window": float(self._acc_window()),
            "acc_cum": float(acc_cum),
            "kappa": float(kappa),
            "n_total": int(self._n_total),
            "window_size": int(self._win_N),
            "K": int(self._K),
        }
        self.outputs["metrics"].on_next(metrics)
        self.outputs["confusion"].on_next(self._conf.copy())