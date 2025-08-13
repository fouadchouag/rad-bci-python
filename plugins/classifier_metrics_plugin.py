# plugins/classifier_metrics_plugin.py

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem,
    QLayout, QSizePolicy, QToolButton
)
from core.node_base import BasePlugin

try:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
    SKLEARN_OK = True
except Exception:
    SKLEARN_OK = False


class _CollapsibleSection(QWidget):
    """Section repliable qui retire vraiment la hauteur quand fermée."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0)
        self._wrap_l.setSpacing(0)
        self._content = content or QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._wrap_l.addWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed)
        self._on_toggled(self._btn.isChecked())

    def _poke_ancestors(self):
        w = self
        while w is not None:
            if w.layout():
                w.layout().invalidate()
            w.adjustSize()
            w.updateGeometry()
            w = w.parentWidget()

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        if expanded:
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self._wrap.setMaximumHeight(16777215)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            header_h = self._btn.sizeHint().height() + 6
            self._wrap.setMaximumHeight(0)
            self._wrap.setMinimumHeight(0)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMaximumHeight(header_h)
            self.setMinimumHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._poke_ancestors()


class ClassifierMetricsPlugin(BasePlugin):
    """
    Évalue un dataset publié par EEGClassifier (X/y) via CV.
    Entrée:
      - dataset: dict {X: np.ndarray[N, d], y: np.ndarray[N], y_names: [str,str], ...}
    UI (tout repliable):
      - Folds (2..10), bouton Evaluate (CV)
      - Statut, métriques texte, matrice de confusion 2x2
    """
    name = "ClassifierMetrics"
    language = "Python"
    category = "ML"

    def setup(self):
        self.inputs["dataset"] = BehaviorSubject(None)

        self._dataset = None
        self._lbl_status = None
        self._lbl_metrics = None
        self._table_cm = None
        self._spn_folds = None
        self._btn_eval = None

    def build_widget(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # ----- panneau complet (params + résultats) dans une section repliable -----
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(6)

        # Ligne folds + bouton
        row = QHBoxLayout()
        row.addWidget(QLabel("Folds:"))
        self._spn_folds = QSpinBox()
        self._spn_folds.setRange(2, 10)
        self._spn_folds.setValue(5)
        row.addWidget(self._spn_folds)

        self._btn_eval = QPushButton("Evaluate (CV)")
        self._btn_eval.clicked.connect(self._on_evaluate)
        row.addWidget(self._btn_eval)
        row.addStretch(1)
        pv.addLayout(row)

        # Status / counts (dans la section)
        self._lbl_status = QLabel("Waiting dataset")
        pv.addWidget(self._lbl_status)

        # Metrics text (dans la section)
        self._lbl_metrics = QLabel("No metrics yet")
        pv.addWidget(self._lbl_metrics)

        # Confusion matrix 2x2 (dans la section)
        self._table_cm = QTableWidget(2, 2)
        self._table_cm.setHorizontalHeaderLabels(["Pred A", "Pred B"])
        self._table_cm.setVerticalHeaderLabels(["True A", "True B"])
        pv.addWidget(self._table_cm)

        sec = _CollapsibleSection("Paramètres & Résultats", panel, collapsed=True)
        root.addWidget(sec)

        return w

    def execute(self, **kwargs):
        ds = kwargs.get("dataset", None)
        self._dataset = ds

        if ds is None:
            if self._lbl_status:
                self._lbl_status.setText("Waiting dataset")
            self._reset_metrics_ui(("A", "B"))
            return {}

        X = ds.get("X", None)
        y = ds.get("y", None)
        y_names = ds.get("y_names", ["A", "B"])
        if not isinstance(y_names, (list, tuple)) or len(y_names) < 2:
            y_names = ["A", "B"]
        y_names = list(y_names[:2])

        # Met à jour les entêtes tout de suite
        if self._table_cm:
            self._table_cm.setHorizontalHeaderLabels(y_names)
            self._table_cm.setVerticalHeaderLabels(y_names)

        # Dataset vide / invalide
        if X is None or y is None or len(np.atleast_1d(y)) == 0:
            if self._lbl_status:
                self._lbl_status.setText("Empty dataset")
            self._reset_metrics_ui(y_names)
            return {}

        try:
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=int)
        except Exception:
            if self._lbl_status:
                self._lbl_status.setText("Invalid dataset (types)")
            self._reset_metrics_ui(y_names)
            return {}

        N = int(X.shape[0]) if X is not None else 0
        d = int(X.shape[1]) if (X is not None and X.ndim == 2) else 0
        n0 = int(np.sum(y == 0))
        n1 = int(np.sum(y == 1))
        if self._lbl_status:
            self._lbl_status.setText(f"Dataset ready | N={N}, d={d} | {y_names[0]}={n0} / {y_names[1]}={n1}")

        # On laisse l’utilisateur cliquer “Evaluate (CV)”
        self._reset_metrics_ui(y_names)
        return {}

    # ----------------- actions -----------------
    def _on_evaluate(self):
        if not SKLEARN_OK:
            if self._lbl_metrics:
                self._lbl_metrics.setText("Install scikit-learn: pip install scikit-learn")
            return
        ds = self._dataset or {}
        X, y = ds.get("X", None), ds.get("y", None)
        y_names = ds.get("y_names", ["A", "B"])
        if not isinstance(y_names, (list, tuple)) or len(y_names) < 2:
            y_names = ["A", "B"]
        y_names = list(y_names[:2])

        if X is None or y is None:
            if self._lbl_metrics:
                self._lbl_metrics.setText("No dataset.")
            self._reset_metrics_ui(y_names)
            return

        try:
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=int)
        except Exception as e:
            if self._lbl_metrics:
                self._lbl_metrics.setText(f"Dataset error: {e}")
            self._reset_metrics_ui(y_names)
            return

        if len(y) < 6 or len(set(y)) < 2:
            if self._lbl_metrics:
                self._lbl_metrics.setText("Need more samples (>=6) and both classes.")
            self._reset_metrics_ui(y_names)
            return

        counts = [np.sum(y == 0), np.sum(y == 1)]
        max_folds = int(max(2, min(counts)))
        n_folds_req = int(self._spn_folds.value() if self._spn_folds else 5)
        n_folds = min(n_folds_req, max_folds)

        try:
            pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
            cv = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)

            acc_scores = cross_val_score(pipe, X, y, cv=cv, scoring="accuracy")
            acc_mean, acc_std = float(np.mean(acc_scores)), float(np.std(acc_scores))

            y_pred = cross_val_predict(pipe, X, y, cv=cv)
            cm = confusion_matrix(y, y_pred, labels=[0, 1])
            prec, rec, f1, _ = precision_recall_fscore_support(
                y, y_pred, labels=[0, 1], zero_division=0
            )

            if self._lbl_metrics:
                self._lbl_metrics.setText(
                    f"CV({n_folds}) Acc: {acc_mean:.2%} ± {acc_std:.2%}   |   "
                    f"Precision: {y_names[0]}={prec[0]:.2f}, {y_names[1]}={prec[1]:.2f}   |   "
                    f"Recall: {y_names[0]}={rec[0]:.2f}, {y_names[1]}={rec[1]:.2f}"
                )

            if self._table_cm:
                self._table_cm.setRowCount(2)
                self._table_cm.setColumnCount(2)
                self._table_cm.setHorizontalHeaderLabels(y_names)  # Pred
                self._table_cm.setVerticalHeaderLabels(y_names)    # True
                for i in range(2):
                    for j in range(2):
                        item = QTableWidgetItem(str(int(cm[i, j])))
                        item.setTextAlignment(int(Qt.AlignCenter))
                        self._table_cm.setItem(i, j, item)
                self._table_cm.resizeColumnsToContents()

        except Exception as e:
            if self._lbl_metrics:
                self._lbl_metrics.setText(f"Eval error: {e}")

    def _reset_metrics_ui(self, y_names=("A", "B")):
        if self._lbl_metrics:
            self._lbl_metrics.setText("No metrics yet")
        if self._table_cm:
            self._table_cm.setRowCount(2)
            self._table_cm.setColumnCount(2)
            self._table_cm.setHorizontalHeaderLabels(list(y_names))
            self._table_cm.setVerticalHeaderLabels(list(y_names))
            for i in range(2):
                for j in range(2):
                    self._table_cm.setItem(i, j, QTableWidgetItem(""))
