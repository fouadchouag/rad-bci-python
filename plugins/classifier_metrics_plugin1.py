# plugins/classifier_metrics_plugin.py

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QLayout, QSizePolicy, QToolButton
)
from core.node_base import BasePlugin

try:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score
    from sklearn.metrics import confusion_matrix, classification_report
    SKLEARN_OK = True
except Exception:
    SKLEARN_OK = False


# ---------- section repliable (FIX: self._wrap avant _on_toggled) ----------
class _CollapsibleSection(QWidget):
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()  # ← IMPORTANT
        wl = QVBoxLayout(self._wrap); wl.setContentsMargins(0,0,0,0); wl.setSpacing(0)
        self._content = content or QWidget(); self._content.setStyleSheet("background: transparent;")
        wl.addWidget(self._content)

        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(4)
        root.addWidget(self._btn); root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed)
        self._on_toggled(self._btn.isChecked())

    def _poke(self):
        w = self
        while w is not None:
            if w.layout(): w.layout().invalidate()
            w.adjustSize(); w.updateGeometry()
            w = w.parentWidget()

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        if expanded:
            self.setMaximumHeight(16777215); self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            header_h = self._btn.sizeHint().height() + 6
            self.setMaximumHeight(header_h); self.setMinimumHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._poke()


class ClassifierMetricsPlugin(BasePlugin):
    """
    Évalue un dataset {X,y,y_names} (multi-classe) par CV.
    Entrée: dataset (dict) -> 'X':(N,d), 'y':(N,), 'y_names':[...]
    """
    name = "ClassifierMetrics_1"
    language = "Python"
    category = "ML"

    def setup(self):
        self.inputs["dataset"] = BehaviorSubject(None)
        self._dataset = None
        self._lbl_status = None
        self._lbl_text = None
        self._table_cm = None
        self._spn_folds = None

    def build_widget(self):
        w = QWidget()
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(6)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget(); pv = QVBoxLayout(panel); pv.setContentsMargins(8,8,8,8); pv.setSpacing(6)

        row = QHBoxLayout()
        row.addWidget(QLabel("Folds:"))
        self._spn_folds = QSpinBox(); self._spn_folds.setRange(2,10); self._spn_folds.setValue(5)
        row.addWidget(self._spn_folds)
        btn = QPushButton("Evaluate (CV)"); btn.clicked.connect(self._on_evaluate); row.addWidget(btn)
        row.addStretch(1); pv.addLayout(row)

        self._lbl_status = QLabel("Waiting dataset"); pv.addWidget(self._lbl_status)
        self._table_cm = QTableWidget(2,2); pv.addWidget(self._table_cm)
        self._lbl_text = QLabel("No metrics yet"); pv.addWidget(self._lbl_text)

        sec = _CollapsibleSection("Paramètres & Résultats", panel, collapsed=True)
        root.addWidget(sec)
        return w

    def execute(self, **kw):
        ds = kw.get("dataset", None); self._dataset = ds
        if ds is None:
            if self._lbl_status: self._lbl_status.setText("Waiting dataset")
            self._set_cm([], [])
            if self._lbl_text: self._lbl_text.setText("No metrics yet")
            return {}

        X = ds.get("X", None); y = ds.get("y", None); names = ds.get("y_names", None) or []
        try:
            X = None if X is None else np.asarray(X, float)
            y = None if y is None else np.asarray(y, int)
        except Exception:
            X, y = None, None
        if X is None or y is None or len(y)==0:
            if self._lbl_status: self._lbl_status.setText("Empty dataset")
            self._set_cm([], names)
            if self._lbl_text: self._lbl_text.setText("No metrics yet")
            return {}

        uniq = sorted(list(set([int(v) for v in y.tolist()])))
        K = len(uniq)
        if not names or len(names)<K: names=[f"Class{i}" for i in range(K)]
        if self._lbl_status:
            self._lbl_status.setText(f"Dataset ready | N={len(y)}, d={X.shape[1] if X.ndim==2 else 0} | K={K}")
        self._set_cm([[0]*K for _ in range(K)], names)
        if self._lbl_text: self._lbl_text.setText("Ready. Click Evaluate.")
        return {}

    def _on_evaluate(self):
        if not SKLEARN_OK:
            if self._lbl_text: self._lbl_text.setText("Install scikit-learn: pip install scikit-learn")
            return
        ds = self._dataset or {}
        X, y = ds.get("X", None), ds.get("y", None)
        names = ds.get("y_names", None) or []
        if X is None or y is None:
            if self._lbl_text: self._lbl_text.setText("No dataset.")
            return
        X = np.asarray(X, float); y = np.asarray(y, int)
        uniq = sorted(list(set(y.tolist()))); K=len(uniq)
        if not names or len(names)<K: names=[f"Class{i}" for i in range(K)]
        counts=[int(np.sum(y==i)) for i in uniq]
        if min(counts)<2:
            if self._lbl_text: self._lbl_text.setText("Need >=2 samples per class.")
            return
        nfolds_req = int(self._spn_folds.value() if self._spn_folds else 5)
        nfolds = min(nfolds_req, max(2, min(counts)))

        try:
            pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, multi_class="auto"))
            cv = StratifiedKFold(n_splits=nfolds, shuffle=True, random_state=42)
            acc = cross_val_score(pipe, X, y, cv=cv, scoring="accuracy")
            y_pred = cross_val_predict(pipe, X, y, cv=cv)
            cm = confusion_matrix(y, y_pred, labels=uniq)
            rep = classification_report(y, y_pred, labels=uniq, target_names=names, zero_division=0, output_dict=True)
            acc_mean=float(np.mean(acc)); acc_std=float(np.std(acc))
            macro_f1 = float(rep.get("macro avg",{}).get("f1-score", 0.0))
            txt = f"CV({nfolds}) Acc: {acc_mean:.2%} ± {acc_std:.2%} | Macro-F1: {macro_f1:.2f}"
            self._set_cm(cm.tolist(), names)
            if self._lbl_text: self._lbl_text.setText(txt)
        except Exception as e:
            if self._lbl_text: self._lbl_text.setText(f"Eval error: {e}")

    def _set_cm(self, M, names):
        if self._table_cm is None: return
        K = len(names) if names else (len(M) if M else 2)
        self._table_cm.setRowCount(K); self._table_cm.setColumnCount(K)
        if names:
            self._table_cm.setHorizontalHeaderLabels(list(names))
            self._table_cm.setVerticalHeaderLabels(list(names))
        for i in range(K):
            for j in range(K):
                val = "" if not M else (str(int(M[i][j])) if i<len(M) and j<len(M[i]) else "")
                it = QTableWidgetItem(val); it.setTextAlignment(int(Qt.AlignCenter))
                self._table_cm.setItem(i,j,it)
        self._table_cm.resizeColumnsToContents()
