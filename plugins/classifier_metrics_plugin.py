# plugins/classifier_metrics_plugin.py

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem
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


class ClassifierMetricsPlugin(BasePlugin):
    """
    Évalue un dataset publié par EEGClassifier (X/y) via CV.
    Entrée:
      - dataset: dict {X: np.ndarray[N, d], y: np.ndarray[N], y_names: [str,str], ...}
    UI:
      - Folds (2..10), bouton Evaluate (CV)
      - Affiche: Accuracy (moy ± std), Precision/Recall par classe, Matrice de confusion 2x2
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
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

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
        lay.addLayout(row)

        # Status / counts
        self._lbl_status = QLabel("Waiting dataset")
        lay.addWidget(self._lbl_status)

        # Metrics text
        self._lbl_metrics = QLabel("No metrics yet")
        lay.addWidget(self._lbl_metrics)

        # Confusion matrix 2x2
        self._table_cm = QTableWidget(2, 2)
        self._table_cm.setHorizontalHeaderLabels(["Pred A", "Pred B"])
        self._table_cm.setVerticalHeaderLabels(["True A", "True B"])
        lay.addWidget(self._table_cm)

        return w

    def execute(self, **kwargs):
        ds = kwargs.get("dataset", None)
        if ds is None:
            # rien à évaluer
            if self._lbl_status:
                self._lbl_status.setText("Waiting dataset")
            self._reset_metrics_ui()
            return {}

        self._dataset = ds
        X, y = ds.get("X", None), ds.get("y", None)
        y_names = ds.get("y_names", ["A", "B"])

        # maj des entêtes avec les bons noms de classes
        if self._table_cm:
            self._table_cm.setHorizontalHeaderLabels(y_names)
            self._table_cm.setVerticalHeaderLabels(y_names)

        if X is None or y is None or len(y) == 0:
            if self._lbl_status:
                self._lbl_status.setText("Empty dataset")
            self._reset_metrics_ui(y_names)
            return {}

        # ... (le reste inchangé : affichage N, counts, etc.)


    # ----------------- actions -----------------
    def _on_evaluate(self):
        if not SKLEARN_OK:
            if self._lbl_metrics:
                self._lbl_metrics.setText("Install scikit-learn: pip install scikit-learn")
            return
        ds = self._dataset or {}
        X, y = ds.get("X", None), ds.get("y", None)
        y_names = ds.get("y_names", ["A", "B"])
        if X is None or y is None or len(y) < 6 or len(set(y)) < 2:
            if self._lbl_metrics:
                self._lbl_metrics.setText("Need more samples (>=6) and both classes.")
            return

        try:
            X = np.asarray(X, dtype=float)
            y = np.asarray(y, dtype=int)

            if X is None or y is None or len(y) < 6 or len(set(y)) < 2:
                if self._lbl_metrics:
                    self._lbl_metrics.setText("Need more samples (>=6) and both classes.")
                self._reset_metrics_ui(y_names)
                return


            # n_splits ne peut pas dépasser le min de la taille des classes
            counts = [np.sum(y == 0), np.sum(y == 1)]
            max_folds = int(max(2, min(counts)))
            n_folds_req = int(self._spn_folds.value())
            n_folds = min(n_folds_req, max_folds)

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
            from PyQt5.QtWidgets import QTableWidgetItem
            for i in range(2):
                for j in range(2):
                    self._table_cm.setItem(i, j, QTableWidgetItem(""))

