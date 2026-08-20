# plugins/bci_predictor_node.py
# -*- coding: utf-8 -*-

import pickle, numpy as np
from collections import deque
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QSpinBox, QCheckBox, QSizePolicy, QStyle
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


def _features_to_vec(features: dict, band_labels: list):
    if features is None or band_labels is None:
        return None
    bands = list(band_labels)
    if isinstance(features, dict) and "GLOBAL" in features and isinstance(features["GLOBAL"], dict):
        return np.asarray([float(features["GLOBAL"].get(b, 0.0)) for b in bands], float)
    # moyenne multi-canaux
    chs = list(features.keys())
    vals = []
    for b in bands:
        per = [features.get(ch, {}).get(b, np.nan) for ch in chs]
        vals.append(float(np.nanmean(per)))
    return np.asarray(vals, float)


class BCI_Predictor(BasePlugin):
    help = {
        'summary': 'Online BCI predictor: applies a trained model to incoming features and outputs class predictions with confidence.',
        'usage': 'Connect features (from BCI_Features) and a trained model (from BCI_Trainer). Outputs predicted class index, label, confidence, and per-class probabilities.',
        'inputs': {
            'features': 'dict — per-channel band values from BCI_Features',
            'band_labels': 'list[str] — feature dimension labels',
            'model': 'trained scikit-learn Pipeline (optional; can also load from file)',
            'y_names_in': 'list[str] — class names (optional; overrides internal)',
            'config_in': 'dict — generic config from BCI_Config',
            'predictor_conf': 'dict — predictor-specific config',
        },
        'outputs': {
            'pred_idx': 'int — predicted class index',
            'pred_label': 'str — predicted class name',
            'pred_conf': 'float — confidence (max probability)',
            'proba': 'dict — {label_name: float} per-class probabilities',
            'y_names': 'list[str] — class names',
            'config_out': 'dict — current parameter state',
        },
        'parameters': [
            {'name': 'smooth_N', 'type': 'int', 'default': 1, 'desc': 'Smoothing window size for probability averaging (1–50)'},
            {'name': 'smooth_enabled', 'type': 'bool', 'default': True, 'desc': 'Enable/disable probability smoothing'},
        ],
        'gotchas': [
            'The model must be trained with the same features (same bands, same mode) used at inference.',
            'Smoothing (smooth_N > 1) reduces jitter but adds latency.',
            'If no model is connected, you can load one from a file via the properties panel.',
        ],
    }

    """
    Prédicteur en ligne pour BCI.
    Entrées data:
      - features (dict)     ← depuis BCI_Features
      - band_labels (list)  ← idem
      - model (optionnel)   ← injection modèle (depuis Trainer)
      - y_names_in (optionnel) ← noms des classes (depuis Trainer/Config)

    Entrées config:
      - config_in (dict)       ← générique (scène / BCI_Config.config)
      - predictor_conf (dict)  ← dédiée

    Sorties:
      - pred_idx (int), pred_label (str), pred_conf (float)
      - proba (dict: {label: p})
      - y_names (list[str])
      - config_out (dict)      ← export de la config courante
    """
    name = "BCI_Predictor"
    language = "Python"
    category = "ML"

    # ---------------- setup ----------------
    def setup(self):
        # data in
        self.inputs["features"]     = BehaviorSubject(None)
        self.inputs["band_labels"]  = BehaviorSubject(None)
        self.inputs["model"]        = BehaviorSubject(None)
        self.inputs["y_names_in"]   = BehaviorSubject(None)

        # config in
        self.inputs["config_in"]     = BehaviorSubject(None)
        self.inputs["predictor_conf"] = BehaviorSubject(None)

        # outputs
        self.outputs["pred_idx"]   = BehaviorSubject(None)
        self.outputs["pred_label"] = BehaviorSubject(None)
        self.outputs["pred_conf"]  = BehaviorSubject(None)
        self.outputs["proba"]      = BehaviorSubject(None)
        self.outputs["y_names"]    = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # état
        self._clf = None
        self._y_names = None
        self._smooth = 1
        self._use_smooth = True
        self._buf = None  # deque
        self._bands_schema = None  # pour info/diagnostic

        # ui
        self._lbl = None
        self._sp_smooth = None
        self._ck_enable = None

        # émettre la config initiale
        self._emit_config()

    # ---------------- UI ----------------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        btn = UiKit.make_btn("Load model (.pkl)", role="ghost", icon_sp=QStyle.SP_DialogOpenButton)
        btn.clicked.connect(self._on_load); r0.addWidget(btn)

        r0.addSpacing(12); r0.addWidget(QLabel("Smoothing N:"))
        self._sp_smooth = QSpinBox(); self._sp_smooth.setRange(1, 50); self._sp_smooth.setValue(self._smooth)
        self._sp_smooth.valueChanged.connect(lambda x: self._set_smooth(int(x)) or self._emit_config()); r0.addWidget(self._sp_smooth)

        self._ck_enable = QCheckBox("enable"); self._ck_enable.setChecked(self._use_smooth)
        self._ck_enable.toggled.connect(self._on_toggle_smooth); r0.addWidget(self._ck_enable)
        r0.addStretch(1); v.addLayout(r0)

        self._lbl = QLabel("No model loaded.")
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("BCI Predictor", panel, collapsed=False))
        return w

    # ---------------- CONFIG API ----------------
    def export_config(self) -> dict:
        """Renvoie la config minimale et portable du predictor."""
        return {
            "smoothing": {"enabled": bool(self._use_smooth), "N": int(self._smooth)},
            "y_names": list(self._y_names) if isinstance(self._y_names, (list, tuple)) else None
        }

    def import_config(self, cfg: dict):
        """
        Accepte:
          - {"smoothing":{"enabled":True,"N":5}, "y_names":[...]}
          - ou directement {"enabled":..,"N":..} (tolérance)
        """
        if not isinstance(cfg, dict): return
        block = cfg.get("smoothing", cfg)

        if isinstance(block, dict):
            if "enabled" in block:
                self._use_smooth = bool(block.get("enabled"))
            if "N" in block:
                self._smooth = max(1, int(block.get("N")))
                self._set_smooth(self._smooth)

        if "y_names" in cfg and isinstance(cfg["y_names"], (list, tuple)):
            self._y_names = [str(s) for s in cfg["y_names"]]
            try: self.outputs["y_names"].on_next(list(self._y_names))
            except Exception: pass

        # sync UI
        if self._ck_enable: self._ck_enable.setChecked(self._use_smooth)
        if self._sp_smooth: self._sp_smooth.setValue(self._smooth)

        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------------- helpers ----------------
    def _on_toggle_smooth(self, s):
        self._use_smooth = bool(s)
        self._emit_config()

    def _set_smooth(self, n):
        self._smooth = max(1, int(n))
        self._buf = deque(maxlen=self._smooth)

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(None, "Load model", "", "Pickle (*.pkl)")
        if not path: return
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            # pkl récent: dict {"model":..., "y_names":..., "report":...}
            self._clf = obj.get("model", None) if isinstance(obj, dict) else None
            if self._clf is None:
                # compat: pkl = pipeline directement
                self._clf = obj
            # y_names
            yn = None
            if isinstance(obj, dict):
                yn = obj.get("y_names", None)
            if isinstance(yn, (list, tuple)) and len(yn) > 0:
                self._y_names = list(yn)
                self.outputs["y_names"].on_next(self._y_names)
            # buffer
            self._set_smooth(self._smooth if self._buf is None else self._buf.maxlen)
            if self._lbl: self._lbl.setText(f"Model loaded. Classes={len(self._y_names or [])}")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Load error: {e}")

    # ---------------- runtime ----------------
    def execute(self, **kw):
        # 1) config entrante (avec/sans câbles)
        merged = {}
        if isinstance(kw.get("config_in"), dict):        merged.update(kw["config_in"])
        if isinstance(kw.get("predictor_conf"), dict):   merged.update(kw["predictor_conf"])
        if merged: self.import_config(merged)

        # 2) update modèle via pin (optionnel)
        m = kw.get("model", None)
        if m is not None and m is not self._clf:
            # tolère dict {"model":..., "y_names":[...]}
            if isinstance(m, dict) and "model" in m:
                self._clf = m.get("model")
                yn = m.get("y_names", None)
                if isinstance(yn, (list, tuple)):
                    self._y_names = list(yn)
                    self.outputs["y_names"].on_next(self._y_names)
            else:
                self._clf = m
            if self._lbl: self._lbl.setText("Model set from input.")

        # 3) y_names via pin (optionnel)
        yn_in = kw.get("y_names_in", None)
        if isinstance(yn_in, (list, tuple)) and len(yn_in) > 0:
            self._y_names = [str(s) for s in yn_in]
            self.outputs["y_names"].on_next(self._y_names)
            self._emit_config()

        if self._clf is None:
            return {}

        feats = kw.get("features", None)
        bands = kw.get("band_labels", None)
        if feats is None or bands is None:
            return {}

        # mémorise le schéma des bandes pour diagnostiquer les incohérences
        if self._bands_schema is None and bands is not None:
            self._bands_schema = list(bands)
        elif bands is not None and list(bands) != self._bands_schema:
            if self._lbl:
                self._lbl.setText(f"Warning: band_labels changed. Was {self._bands_schema}, now {list(bands)}.")
            self._bands_schema = list(bands)

        x = _features_to_vec(feats, bands)
        if x is None or not np.all(np.isfinite(x)):
            if self._lbl: self._lbl.setText("Bad vector.")
            return {}

        try:
            # proba (1xK)
            if hasattr(self._clf, "predict_proba"):
                p = self._clf.predict_proba([x])[0]
            else:
                yi = self._clf.predict([x])[0]
                K = len(self._y_names or [])
                p = np.zeros(K, float)
                if 0 <= int(yi) < K: p[int(yi)] = 1.0

            if self._use_smooth:
                if self._buf is None: self._set_smooth(self._smooth)
                self._buf.append(p.copy())
                p = np.mean(np.stack(self._buf, axis=0), axis=0)

            idx = int(np.argmax(p)); conf = float(np.max(p))
            name = (self._y_names[idx] if (self._y_names and idx < len(self._y_names)) else f"Class{idx}")
            proba_dict = { (self._y_names[i] if (self._y_names and i < len(self._y_names)) else f"Class{i}") : float(p[i]) for i in range(len(p)) }

            self.outputs["pred_idx"].on_next(idx)
            self.outputs["pred_label"].on_next(name)
            self.outputs["pred_conf"].on_next(conf)
            self.outputs["proba"].on_next(proba_dict)

            if self._lbl:
                self._lbl.setText(f"Pred: {name} ({conf:.2f}) | F={x.size} | smooth={self._smooth if self._use_smooth else 1}")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Predict error: {e}")
        return {}