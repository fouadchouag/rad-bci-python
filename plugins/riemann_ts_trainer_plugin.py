# plugins/riemann_ts_trainer_plugin.py
# -*- coding: utf-8 -*-
"""
RiemannTSTrainer — apprend la Tangent Space (pyRiemann).
Inputs:
  - cov   : ndarray (n_ch, n_ch)
  - label : str|int
Outputs:
  - ts_transform : objet TangentSpace entraîné (fit sur mean SPD)
  - classes      : liste des labels vus
  - n_samples    : int
  - counts       : dict label->count
UI:
  - Boutons: Ajouter, Entraîner TS, Effacer, Sauver, Charger
"""
import os, json, joblib, numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QFileDialog, QMessageBox
from core.node_base import BasePlugin

try:
    from pyriemann.tangentspace import TangentSpace
    _HAVE_RIEMANN = True
except Exception:
    _HAVE_RIEMANN = False

class RiemannTSTrainerPlugin(BasePlugin):
    help = help = { 'gotchas': ['Balance classes; keep held-out test set.'],
  'inputs': {'features': 'array/dict', 'labels': 'array'},
  'outputs': {'model': 'trained model'},
  'parameters': [ { 'default': 'LR',
                    'desc': 'Classifier (LR/SVM/RF/...)',
                    'name': 'model',
                    'type': 'str'},
                  { 'default': 5,
                    'desc': 'Cross-validation folds',
                    'name': 'cv',
                    'type': 'int'},
                  { 'default': 'standard',
                    'desc': 'Feature scaling',
                    'name': 'scaler',
                    'type': 'str'}],
  'summary': 'RiemannTSTrainer — apprend la Tangent Space (pyRiemann).',
  'usage': 'Feed features and labels; connect model to runtime/apply node.'}

    name = "RiemannTSTrainer"
    language = "Python"
    category = "ML / Riemann"

    def setup(self):
        self.inputs["cov"] = BehaviorSubject(None)
        self.inputs["label"] = BehaviorSubject(None)

        self.outputs["ts_transform"] = BehaviorSubject(None)
        self.outputs["classes"] = BehaviorSubject(None)
        self.outputs["n_samples"] = BehaviorSubject(0)
        self.outputs["counts"] = BehaviorSubject({})

        self._X, self._y = [], []
        self._widget = None; self._lbl_status=None; self._lbl_counts=None
        self._ts = None
        if not _HAVE_RIEMANN:
            print("[RiemannTSTrainer] ⚠️ pyriemann non installé. `pip install pyriemann`")

    def build_widget(self):
        if self._widget is not None: return self._widget
        w = QWidget(); root = QVBoxLayout(w)
        self._lbl_status = QLabel("Aucun échantillon."); self._lbl_status.setStyleSheet("font-weight:600;")
        root.addWidget(self._lbl_status)

        btns = QHBoxLayout()
        b_add = QPushButton("➕ Ajouter"); b_fit = QPushButton("🧠 Entraîner TS")
        b_clear = QPushButton("🧹 Effacer"); b_save = QPushButton("💾 Sauvegarder"); b_load = QPushButton("📂 Charger")
        for b in (b_add,b_fit,b_clear,b_save,b_load): btns.addWidget(b)
        root.addLayout(btns)

        root.addWidget(QLabel("Comptes par classe:"))
        self._lbl_counts = QLabel("{}"); self._lbl_counts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._lbl_counts)

        b_add.clicked.connect(self._on_add); b_fit.clicked.connect(self._on_fit)
        b_clear.clicked.connect(self._on_clear); b_save.clicked.connect(self._on_save); b_load.clicked.connect(self._on_load)

        self._widget = w; return w

    def _status(self, msg):
        if self._lbl_status: self._lbl_status.setText(msg)
        print(f"[RiemannTSTrainer] {msg}")

    def _refresh_counts(self):
        counts={}
        for y in self._y: counts[y] = counts.get(y,0) + 1
        self.outputs["counts"].on_next(counts)
        self.outputs["n_samples"].on_next(len(self._y))
        if self._lbl_counts:
            self._lbl_counts.setText(json.dumps(counts, ensure_ascii=False))

    def _on_add(self):
        cov = self.inputs["cov"].value; lbl = self.inputs["label"].value
        if cov is None: return self._status("⚠️ cov manquante")
        if lbl is None: return self._status("⚠️ label manquant")
        c = np.asarray(cov)
        if c.ndim != 2 or c.shape[0] != c.shape[1]: return self._status("⚠️ cov doit être carrée")
        self._X.append(c.copy()); self._y.append(lbl)
        self._refresh_counts(); self._status(f"Échantillon ajouté (total={len(self._y)}).")

    def _on_fit(self):
        if not _HAVE_RIEMANN: return self._status("❌ pyriemann manquant")
        if len(self._y) < 2: return self._status("⚠️ ≥2 échantillons requis")
        try:
            X = np.stack(self._X, axis=0)  # (n_trials, n_ch, n_ch)
        except Exception as e:
            return self._status(f"❌ empilement: {e}")
        ts = TangentSpace(metric='riemann')
        try:
            ts.fit(X)  # apprend la référence (mean SPD)
        except Exception as e:
            return self._status(f"❌ fit TS: {e}")
        self._ts = ts
        self.outputs["ts_transform"].on_next(self._ts)
        self.outputs["classes"].on_next(sorted(set(self._y), key=str))
        self._status("✅ TangentSpace entraînée.")

    def _on_clear(self):
        self._X.clear(); self._y.clear(); self._ts=None
        self.outputs["ts_transform"].on_next(None); self.outputs["classes"].on_next(None)
        self._refresh_counts(); self._status("Dataset effacé.")

    def _on_save(self):
        if self._ts is None: return self._status("⚠️ rien à sauvegarder")
        path,_ = QFileDialog.getSaveFileName(self._widget,"Sauvegarder TS","ts.pkl","Pickle (*.pkl)")
        if not path: return
        try:
            joblib.dump({"ts": self._ts}, path); self._status("💾 TS sauvegardée")
        except Exception as e:
            QMessageBox.critical(self._widget,"Erreur",str(e))

    def _on_load(self):
        path,_ = QFileDialog.getOpenFileName(self._widget,"Charger TS","","Pickle (*.pkl)")
        if not path: return
        try:
            obj = joblib.load(path); self._ts = obj["ts"]
            self.outputs["ts_transform"].on_next(self._ts); self._status("📂 TS chargée")
        except Exception as e:
            QMessageBox.critical(self._widget,"Erreur",str(e))

    def execute(self, inputs): 
        return