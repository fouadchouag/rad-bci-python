# plugins/csp_trainer_plugin.py
# -*- coding: utf-8 -*-
import os, json, numpy as np, joblib
from rx.subject import BehaviorSubject

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QSpinBox, QPushButton,
    QFileDialog, QMessageBox, QSizePolicy, QLayout, QFrame
)

from core.node_base import BasePlugin
from mne.decoding import CSP
from sklearn.preprocessing import LabelEncoder


# ------------ Section pliable (anti “cadre gris”) ------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Forçage d'update pour éviter toute zone grise.
    """
    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # démarrage fermé
        self._btn.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding:6px 8px; font-weight:600;"
            " border:1px solid #ccc; border-radius:6px; background:#f7f7f7;"
            "}"
        )
        self._btn.toggled.connect(self._on_toggled)
        root.addWidget(self._btn)

        self._content = QWidget()
        self._content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(10, 8, 10, 8)
        self._lay.setSpacing(6)
        self._lay.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.set_collapsed(True)  # fermé par défaut

    def content_layout(self):
        return self._lay

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)
        self._apply(collapsed)
        self._update_title()
        self._reflow()

    def _on_toggled(self, checked: bool):
        self._apply(collapsed=not checked)
        self._update_title()
        self._reflow()

    def _apply(self, collapsed: bool):
        if collapsed:
            self._content.setMaximumHeight(0)
            self._content.setMinimumHeight(0)
            self._content.setVisible(False)
            self._line.setVisible(False)
        else:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            self._content.setMinimumHeight(0)
            self._line.setVisible(True)

    def _update_title(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._title[2:] if self._title[:2] in ("▼ ", "▶ ") else self._title
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry(); self.updateGeometry()
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._bubble_adjust)

    def _bubble_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout(): w.layout().activate()
                w.adjustSize(); w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


class CSPTrainerPlugin(BasePlugin):
    help = {
        'gotchas': ['Balance classes; keep held-out test set.'],
        'inputs': {'features': 'array/dict', 'labels': 'array'},
        'outputs': {'model': 'trained model'},
        'parameters': [
            {'name': 'model', 'type': 'str', 'default': 'LR', 'desc': 'Classifier (LR/SVM/RF/...)'},
            {'name': 'cv', 'type': 'int', 'default': 5, 'desc': 'Cross-validation folds'},
            {'name': 'scaler', 'type': 'str', 'default': 'standard', 'desc': 'Feature scaling'}
        ],
        'summary': 'Train a machine-learning model for BCI.',
        'usage': 'Feed features and labels; connect model to runtime/apply node.'
    }

    name = "CSPTrainer"
    language = "Python"
    category = "ML / Features"

    def setup(self):
        # Entrées (segment + label pour entraîner CSP sur trials)
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["label"] = BehaviorSubject(None)

        # Sorties
        self.outputs["feature_transform"] = BehaviorSubject(None)  # objet CSP entraîné
        self.outputs["classes"] = BehaviorSubject(None)
        self.outputs["n_samples"] = BehaviorSubject(0)
        self.outputs["counts"] = BehaviorSubject({})
        self.outputs["status"] = BehaviorSubject("")

        self._X, self._y = [], []
        self._le = LabelEncoder()
        self._csp = None

        # UI refs
        self._widget = None
        self._lbl_status = None
        self._lbl_counts = None
        self._spin_csp = None

    # ---------------- UI ----------------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # --- Section Paramètres (fermée par défaut) ---
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self._spin_csp = QSpinBox()
        self._spin_csp.setRange(2, 64)
        self._spin_csp.setValue(8)
        form.addRow("CSP n_components", self._spin_csp)

        # Boutons
        btns = QHBoxLayout()
        b_add = QPushButton("➕ Ajouter")
        b_fit = QPushButton("🧠 Entraîner CSP")
        b_clear = QPushButton("🧹 Effacer")
        b_save = QPushButton("💾 Sauvegarder")
        b_load = QPushButton("📂 Charger")
        for b in (b_add, b_fit, b_clear, b_save, b_load):
            btns.addWidget(b)
        btns.addStretch(1)

        # Comptes (on le place DANS la section pour que tout disparaisse au repli)
        lab_counts_title = QLabel("Comptes par classe :")
        self._lbl_counts = QLabel("{}")
        self._lbl_counts.setTextInteractionFlags(Qt.TextSelectableByMouse)

        box = QWidget()
        box_l = QVBoxLayout(box)
        box_l.setContentsMargins(0, 0, 0, 0)
        box_l.setSpacing(6)
        box_l.addLayout(form)
        box_l.addLayout(btns)
        box_l.addWidget(lab_counts_title)
        box_l.addWidget(self._lbl_counts)

        sec.content_layout().addWidget(box)
        root.addWidget(sec)

        # Statut (toujours visible)
        self._lbl_status = QLabel("Aucun échantillon.")
        self._lbl_status.setStyleSheet("color:#666;")
        root.addWidget(self._lbl_status)

        # Contraintes anti “cadre gris”
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        # Connexions
        b_add.clicked.connect(self._on_add)
        b_fit.clicked.connect(self._on_fit)
        b_clear.clicked.connect(self._on_clear)
        b_save.clicked.connect(self._on_save)
        b_load.clicked.connect(self._on_load)

        self._widget = w
        return w

    # ---------------- Helpers ----------------
    def _ensure_seg(self, seg):
        if seg is None:
            return None
        arr = np.asarray(seg)
        if arr.ndim != 2:
            return None
        return arr if arr.shape[0] < arr.shape[1] else arr.T  # (n_ch, n_t)

    def _status(self, msg):
        if self._lbl_status:
            self._lbl_status.setText(msg)
        try:
            self.outputs["status"].on_next(msg)
        except Exception:
            pass
        print(f"[CSPTrainer] {msg}")

    def _refresh_counts(self):
        counts = {}
        for y in self._y:
            counts[y] = counts.get(y, 0) + 1
        self.outputs["counts"].on_next(counts)
        self.outputs["n_samples"].on_next(len(self._y))
        if self._lbl_counts:
            self._lbl_counts.setText(json.dumps(counts, ensure_ascii=False))

    # ---------------- Slots ----------------
    def _on_add(self):
        seg = self._ensure_seg(self.inputs["segment"].value)
        lbl = self.inputs["label"].value
        if seg is None:
            return self._status("⚠️ segment invalide")
        if lbl is None:
            return self._status("⚠️ label manquant")
        self._X.append(seg.copy()); self._y.append(lbl)
        self._refresh_counts()
        self._status(f"Échantillon ajouté (total={len(self._y)}).")

    def _on_fit(self):
        if len(self._y) < 2:
            return self._status("⚠️ ≥2 échantillons requis")
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
        self._X.clear(); self._y.clear(); self._csp = None
        self.outputs["feature_transform"].on_next(None)
        self.outputs["classes"].on_next(None)
        self._refresh_counts()
        self._status("Dataset effacé.")

    def _on_save(self):
        if self._csp is None:
            return self._status("⚠️ rien à sauvegarder")
        path, _ = QFileDialog.getSaveFileName(self._widget, "Sauvegarder CSP", "csp.pkl", "Pickle (*.pkl)")
        if not path:
            return
        try:
            joblib.dump({"csp": self._csp, "classes": list(self._le.classes_)}, path)
            self._status(f"💾 Sauvé: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self._widget, "Charger CSP", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            obj = joblib.load(path)
            self._csp = obj["csp"]; classes = obj.get("classes", None)
            self.outputs["feature_transform"].on_next(self._csp)
            if classes:
                self.outputs["classes"].on_next(classes)
            self._status(f"📂 Chargé: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    # Pas d'entraînement automatique en "execute"
    def execute(self, inputs):
        return
