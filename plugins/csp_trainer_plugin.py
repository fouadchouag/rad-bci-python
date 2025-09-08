# plugins/csp_trainer_plugin.py
# -*- coding: utf-8 -*-
import os, json, numpy as np, joblib
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QSpinBox, QPushButton, QFileDialog, QMessageBox
from core.node_base import BasePlugin
from mne.decoding import CSP
from sklearn.preprocessing import LabelEncoder

class CSPTrainerPlugin(BasePlugin):
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
  'summary': 'Train a machine-learning model for BCI.',
  'usage': 'Feed features and labels; connect model to runtime/apply node.'}

    name = "CSPTrainer"
    language = "Python"
    category = "ML / Features"

    def setup(self):
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["label"] = BehaviorSubject(None)

        self.outputs["feature_transform"] = BehaviorSubject(None)  # objet CSP entraîné
        self.outputs["classes"] = BehaviorSubject(None)
        self.outputs["n_samples"] = BehaviorSubject(0)
        self.outputs["counts"] = BehaviorSubject({})

        self._X, self._y = [], []
        self._le = LabelEncoder()
        self._csp = None

        self._widget = None
        self._lbl_status = None
        self._lbl_counts = None
        self._spin_csp = None

    def build_widget(self):
        if self._widget is not None: return self._widget
        w = QWidget(); root = QVBoxLayout(w)

        self._lbl_status = QLabel("Aucun échantillon."); self._lbl_status.setStyleSheet("font-weight:600;")
        root.addWidget(self._lbl_status)

        form = QFormLayout()
        self._spin_csp = QSpinBox(); self._spin_csp.setRange(2, 64); self._spin_csp.setValue(8)
        form.addRow("CSP n_components", self._spin_csp)
        root.addLayout(form)

        btns = QHBoxLayout()
        b_add = QPushButton("➕ Ajouter")
        b_fit = QPushButton("🧠 Entraîner CSP")
        b_clear = QPushButton("🧹 Effacer")
        b_save = QPushButton("💾 Sauvegarder")
        b_load = QPushButton("📂 Charger")
        for b in (b_add, b_fit, b_clear, b_save, b_load): btns.addWidget(b)
        root.addLayout(btns)

        root.addWidget(QLabel("Comptes par classe:"))
        self._lbl_counts = QLabel("{}"); self._lbl_counts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self._lbl_counts)

        b_add.clicked.connect(self._on_add)
        b_fit.clicked.connect(self._on_fit)
        b_clear.clicked.connect(self._on_clear)
        b_save.clicked.connect(self._on_save)
        b_load.clicked.connect(self._on_load)

        self._widget = w
        return w

    def _ensure_seg(self, seg):
        if seg is None: return None
        arr = np.asarray(seg); 
        if arr.ndim != 2: return None
        return arr if arr.shape[0] < arr.shape[1] else arr.T  # (n_ch, n_t)

    def _status(self, msg):
        if self._lbl_status: self._lbl_status.setText(msg)
        print(f"[CSPTrainer] {msg}")

    def _refresh_counts(self):
        counts = {}
        for y in self._y: counts[y] = counts.get(y, 0) + 1
        self.outputs["counts"].on_next(counts)
        self.outputs["n_samples"].on_next(len(self._y))
        if self._lbl_counts: self._lbl_counts.setText(json.dumps(counts, ensure_ascii=False))

    def _on_add(self):
        seg = self._ensure_seg(self.inputs["segment"].value)
        lbl = self.inputs["label"].value
        if seg is None: return self._status("⚠️ segment invalide")
        if lbl is None: return self._status("⚠️ label manquant")
        self._X.append(seg.copy()); self._y.append(lbl)
        self._refresh_counts(); self._status(f"Échantillon ajouté (total={len(self._y)}).")

    def _on_fit(self):
        if len(self._y) < 2: return self._status("⚠️ ≥2 échantillons requis")
        try:
            X = np.stack(self._X, axis=0)  # (n_trials, n_ch, n_t)
        except Exception as e:
            return self._status(f"❌ empilement X: {e}")
        y_enc = self._le.fit_transform(np.asarray(self._y))
        n_comp = int(self._spin_csp.value()) if self._spin_csp else 8
        csp = CSP(n_components=n_comp, reg='oas', log=True, norm_trace=False)
        try:
            csp.fit(X, y_enc)
        except Exception as e:
            return self._status(f"❌ fit CSP: {e}")
        self._csp = csp
        self.outputs["feature_transform"].on_next(self._csp)
        self.outputs["classes"].on_next(list(self._le.classes_))
        self._status(f"✅ CSP entraîné (n_components={n_comp})")

    def _on_clear(self):
        self._X.clear(); self._y.clear(); self._csp=None
        self.outputs["feature_transform"].on_next(None)
        self.outputs["classes"].on_next(None)
        self._refresh_counts(); self._status("Dataset effacé.")

    def _on_save(self):
        if self._csp is None: return self._status("⚠️ rien à sauvegarder")
        path, _ = QFileDialog.getSaveFileName(self._widget, "Sauvegarder CSP", "csp.pkl", "Pickle (*.pkl)")
        if not path: return
        try:
            joblib.dump({"csp": self._csp, "classes": list(self._le.classes_)}, path)
            self._status(f"💾 Sauvé: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self._widget, "Charger CSP", "", "Pickle (*.pkl)")
        if not path: return
        try:
            obj = joblib.load(path)
            self._csp = obj["csp"]; classes = obj.get("classes", None)
            self.outputs["feature_transform"].on_next(self._csp)
            if classes: self.outputs["classes"].on_next(classes)
            self._status(f"📂 Chargé: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    def execute(self, inputs): 
        return  # pas d'entraînement auto