# plugins/riemann_ts_trainer_plugin.py
# -*- coding: utf-8 -*-
"""
RiemannTSTrainer — apprend la Tangent Space (pyRiemann)
→ Section Paramètres pliable (fermée par défaut, sans zone grise)

Entrées:
  - cov   : ndarray (n_ch, n_ch) SPD
  - label : str|int

Sorties:
  - ts_transform : objet TangentSpace entraîné
  - classes      : liste des labels vus
  - n_samples    : int
  - counts       : dict label->count
"""
import os, json, joblib, numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QSizePolicy, QLayout, QFrame
)

from core.node_base import BasePlugin

try:
    from pyriemann.tangentspace import TangentSpace
    _HAVE_RIEMANN = True
except Exception:
    _HAVE_RIEMANN = False


# ---------------------- Section pliable (anti “cadre gris”) ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Reflow forcé (pas de zone grise).
    """
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # fermé par défaut
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
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(10, 8, 10, 8)
        self.body.setSpacing(6)
        self.body.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.set_collapsed(True)

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


# ------------------------------ Plugin ------------------------------
class RiemannTSTrainerPlugin(BasePlugin):
    help = {
        'gotchas': ['Équilibrer les classes ; garder un jeu de test à part.'],
        'inputs': {'cov': 'SPD (n_ch×n_ch)', 'label': 'classe (str|int)'},
        'outputs': {
            'ts_transform': 'pyriemann.TangentSpace entraîné',
            'classes': 'liste des labels vus',
            'n_samples': 'int',
            'counts': 'dict label→count'
        },
        'parameters': [],
        'summary': 'RiemannTSTrainer — apprend la Tangent Space (pyRiemann).',
        'usage': 'Cliquer Ajouter pour empiler (cov,label), puis Entraîner TS.'
    }

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
        self._ts = None

        self._widget = None
        self._lbl_status = None
        self._lbl_counts = None

        if not _HAVE_RIEMANN:
            print("[RiemannTSTrainer] ⚠️ pyriemann non installé. `pip install pyriemann`")

    def build_widget(self):
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("Riemann TS Trainer")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        # --------- Section Paramètres (pliable) ---------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        # Ligne de boutons d’action
        row = QHBoxLayout()
        b_add  = QPushButton("➕ Ajouter")
        b_fit  = QPushButton("🧠 Entraîner TS")
        b_clear= QPushButton("🧹 Effacer")
        b_save = QPushButton("💾 Sauvegarder")
        b_load = QPushButton("📂 Charger")
        for b in (b_add, b_fit, b_clear, b_save, b_load):
            row.addWidget(b)
        row.addStretch(1)
        sec.body.addLayout(row)

        # Infos (toujours visibles)
        self._lbl_status = QLabel("Aucun échantillon.")
        self._lbl_status.setStyleSheet("font-weight:600;")
        self._lbl_counts = QLabel("{}")
        self._lbl_counts.setTextInteractionFlags(Qt.TextSelectableByMouse)

        root.addWidget(sec)
        root.addWidget(QLabel("Comptes par classe:"))
        root.addWidget(self._lbl_counts)
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

    # ---------- helpers ----------
    def _status(self, msg: str):
        if self._lbl_status:
            self._lbl_status.setText(msg)
        print(f"[RiemannTSTrainer] {msg}")

    def _refresh_counts(self):
        counts = {}
        for y in self._y:
            counts[y] = counts.get(y, 0) + 1
        self.outputs["counts"].on_next(counts)
        self.outputs["n_samples"].on_next(len(self._y))
        if self._lbl_counts:
            self._lbl_counts.setText(json.dumps(counts, ensure_ascii=False))

    # ---------- actions ----------
    def _on_add(self):
        cov = self.inputs["cov"].value
        lbl = self.inputs["label"].value
        if cov is None:
            return self._status("⚠️ cov manquante")
        if lbl is None:
            return self._status("⚠️ label manquant")
        c = np.asarray(cov)
        if c.ndim != 2 or c.shape[0] != c.shape[1]:
            return self._status("⚠️ cov doit être carrée (n_ch×n_ch)")
        self._X.append(c.copy())
        self._y.append(lbl)
        self._refresh_counts()
        self._status(f"Échantillon ajouté (total={len(self._y)}).")

    def _on_fit(self):
        if not _HAVE_RIEMANN:
            return self._status("❌ pyriemann manquant (`pip install pyriemann`)")
        if len(self._y) < 2:
            return self._status("⚠️ ≥2 échantillons requis")
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
        self._X.clear()
        self._y.clear()
        self._ts = None
        self.outputs["ts_transform"].on_next(None)
        self.outputs["classes"].on_next(None)
        self._refresh_counts()
        self._status("Dataset effacé.")

    def _on_save(self):
        if self._ts is None:
            return self._status("⚠️ rien à sauvegarder")
        path, _ = QFileDialog.getSaveFileName(self._widget, "Sauvegarder TS", "ts.pkl", "Pickle (*.pkl)")
        if not path:
            return
        try:
            joblib.dump({"ts": self._ts}, path)
            self._status("💾 TS sauvegardée")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self._widget, "Charger TS", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            obj = joblib.load(path)
            self._ts = obj["ts"]
            self.outputs["ts_transform"].on_next(self._ts)
            self._status("📂 TS chargée")
        except Exception as e:
            QMessageBox.critical(self._widget, "Erreur", str(e))

    def execute(self, inputs):
        return  # pas d'entraînement automatique
