# plugins/bci_trainer_node.py
# -*- coding: utf-8 -*-

import os
import json
import pickle
import traceback
import numpy as np
from rx.subject import BehaviorSubject
from concurrent.futures import ThreadPoolExecutor

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QSizePolicy, QStyle, QDoubleSpinBox
)

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# --- scikit-learn (optionnel) ---
try:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
    from sklearn.model_selection import (
        StratifiedKFold, cross_val_score, cross_val_predict, train_test_split
    )
    from sklearn.metrics import (
        confusion_matrix, accuracy_score, balanced_accuracy_score, f1_score
    )
    SK_OK = True
except Exception:
    SK_OK = False


class BCI_Trainer(BasePlugin):
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
  'summary': 'Entraîne un modèle scikit-learn en THREAD (non-bloquant UI) et publie un '
             'rapport complet.',
  'usage': 'Feed features and labels; connect model to runtime/apply node.'}

    """
    Entraîne un modèle scikit-learn en THREAD (non-bloquant UI) et publie un rapport complet.

    Entrée:
      - dataset: dict {"X":(N,F), "y":(N,), "y_names":[...]}

    Sorties:
      - model   : pipeline sklearn entraînée
      - report  : dict métriques (CV, confusion, etc.)
      - config_out : dict (echo de la config courante)
    """
    name = "BCI_Trainer"
    language = "Python"
    category = "BCI/ML"

    # ------------------------------------------------------------------ #
    # Lifecycle / IO                                                     #
    # ------------------------------------------------------------------ #
    def setup(self):
        # Data in
        self.inputs["dataset"] = BehaviorSubject(None)

        # Config in/out
        self.inputs["config_in"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # Model / report out
        self.outputs["model"] = BehaviorSubject(None)
        self.outputs["report"] = BehaviorSubject(None)

        # Hyperparams (modifiables via UI / config)
        self._algo = "LogisticRegression"  # "LogisticRegression" | "LDA"
        self._cv_k = 5
        self._balanced = True
        self._holdout = 0.0  # 0..0.49

        # Async job
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._future = None

        # UI refs
        self._lbl = None
        self._btn_train = None
        self._btn_save = None
        self._btn_load = None
        self._btn_export = None
        self._cmb_algo = None
        self._spk = None
        self._ck_bal = None
        self._sp_ho = None

        # State
        self._model = None
        self._y_names = None
        self._last_report = None
        self._cached_ds = None

        # Premier broadcast de config
        self._emit_config()

    # ------------------------------------------------------------------ #
    # Config API                                                         #
    # ------------------------------------------------------------------ #
    def export_config(self) -> dict:
        return {
            "algo": self._algo,
            "cv_k": int(self._cv_k),
            "balanced": bool(self._balanced),
            "holdout": float(self._holdout),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        algo = cfg.get("algo", None)
        if isinstance(algo, str) and algo:
            a = algo.lower()
            if "lda" in a:
                self._algo = "LDA"
            elif "log" in a or "lr" in a:
                self._algo = "LogisticRegression"
        if "cv_k" in cfg:
            self._cv_k = max(2, int(cfg.get("cv_k")))
        if "balanced" in cfg:
            self._balanced = bool(cfg.get("balanced"))
        if "holdout" in cfg:
            ho = float(cfg.get("holdout"))
            self._holdout = min(max(0.0, ho), 0.49)

        # Sync UI si visibles
        if self._cmb_algo:
            self._cmb_algo.setCurrentText(self._algo)
        if self._spk:
            self._spk.setValue(self._cv_k)
        if self._ck_bal:
            self._ck_bal.setChecked(self._balanced)
        if self._sp_ho:
            self._sp_ho.setValue(self._holdout)

        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # UI                                                                 #
    # ------------------------------------------------------------------ #
    def build_widget(self):
        w = QWidget()
        UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Row: algo + CV + balanced + holdout
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Algo:"))
        self._cmb_algo = QComboBox()
        self._cmb_algo.addItems(["LogisticRegression", "LDA"])
        self._cmb_algo.setCurrentText(self._algo)

        def _on_algo_changed(s):
            self._algo = s
            self._emit_config()

        self._cmb_algo.currentTextChanged.connect(_on_algo_changed)
        r0.addWidget(self._cmb_algo)

        r0.addSpacing(12)
        r0.addWidget(QLabel("CV k-fold:"))
        self._spk = QSpinBox()
        self._spk.setRange(2, 20)
        self._spk.setValue(self._cv_k)

        def _on_k_changed(v):
            self._cv_k = int(v)
            self._emit_config()

        self._spk.valueChanged.connect(_on_k_changed)
        r0.addWidget(self._spk)

        self._ck_bal = QCheckBox("balanced (logreg)")
        self._ck_bal.setChecked(self._balanced)

        def _on_bal_changed(s):
            self._balanced = bool(s)
            self._emit_config()

        self._ck_bal.toggled.connect(_on_bal_changed)
        r0.addWidget(self._ck_bal)

        r0.addSpacing(12)
        r0.addWidget(QLabel("Hold-out test_size:"))
        self._sp_ho = QDoubleSpinBox()
        self._sp_ho.setRange(0.0, 0.49)
        self._sp_ho.setSingleStep(0.05)
        self._sp_ho.setDecimals(2)
        self._sp_ho.setValue(self._holdout)

        def _on_ho_changed(x):
            self._holdout = float(x)
            self._emit_config()

        self._sp_ho.valueChanged.connect(_on_ho_changed)
        r0.addWidget(self._sp_ho)
        r0.addStretch(1)
        v.addLayout(r0)

        # Row: actions
        r1 = QHBoxLayout()
        self._btn_train = UiKit.make_btn("Train (async)", role="primary", icon_sp=QStyle.SP_MediaPlay)
        self._btn_train.clicked.connect(self._on_train)
        r1.addWidget(self._btn_train)

        self._btn_save = UiKit.make_btn("Save model", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        self._btn_save.clicked.connect(self._on_save)
        r1.addWidget(self._btn_save)

        self._btn_load = UiKit.make_btn("Load model", role="ghost", icon_sp=QStyle.SP_DialogOpenButton)
        self._btn_load.clicked.connect(self._on_load)
        r1.addWidget(self._btn_load)

        self._btn_export = UiKit.make_btn("Export report", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        self._btn_export.clicked.connect(self._on_export_report)
        r1.addWidget(self._btn_export)

        r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel(("scikit-learn OK" if SK_OK else "Install scikit-learn"))
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("BCI Trainer (threaded + metrics)", panel, collapsed=False))
        return w

    # ------------------------------------------------------------------ #
    # Runtime                                                            #
    # ------------------------------------------------------------------ #
    def execute(self, **kw):
        # Config entrante (optionnelle)
        cfg = kw.get("config_in", None)
        if isinstance(cfg, dict) and cfg:
            self.import_config(cfg)

        # Dataset
        ds = kw.get("dataset", None)
        if isinstance(ds, dict):
            X = ds.get("X", None)
            y = ds.get("y", None)
            if ds.get("y_names", None) is not None:
                self._y_names = list(ds["y_names"])
            try:
                if X is not None and y is not None:
                    X = np.asarray(X)
                    y = np.asarray(y).ravel()
                    if X.ndim == 2 and y.ndim == 1 and len(y) == X.shape[0] and X.shape[0] > 0:
                        self._cached_ds = {"X": X.copy(), "y": y.copy(), "y_names": list(self._y_names or [])}
                        if self._lbl is not None:
                            self._lbl.setText(
                                f"Dataset ready: N={len(y)} | F={X.shape[1]} | K={len(np.unique(y))}"
                            )
                        return {}
            except Exception:
                pass
        return {}

    # ------------------------------------------------------------------ #
    # Training helpers                                                   #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _make_pipeline(algo: str, balanced: bool):
        if algo == "LDA":
            return make_pipeline(StandardScaler(with_mean=True), LinearDiscriminantAnalysis())
        return make_pipeline(
            StandardScaler(with_mean=True),
            LogisticRegression(max_iter=1000, class_weight=("balanced" if balanced else None))
        )

    @staticmethod
    def _train_job(X, y, algo, cvk, balanced, holdout):
        """
        Job exécuté dans un thread :
        - limite BLAS à 1 pour préserver la réactivité UI
        - parallélise la CV via joblib (process) si dispo
        """
        os.environ.setdefault("OMP_NUM_THREADS", "1")

        # Contexte perfs (optionnel) depuis core.rt_perf
        try:
            from core.rt_perf import blas_limits, joblib_loky
        except Exception:
            from contextlib import contextmanager
            @contextmanager
            def blas_limits(*_a, **_k):
                yield
            @contextmanager
            def joblib_loky(*_a, **_k):
                yield

        clf = BCI_Trainer._make_pipeline(algo, balanced)
        cv = StratifiedKFold(n_splits=cvk, shuffle=True, random_state=42)

        # CV / predict (multi-process si possible)
        with blas_limits(1), joblib_loky(n_jobs=-1):
            scores = cross_val_score(clf, X, y, cv=cv, n_jobs=-1)  # accuracy
            y_pred_cv = cross_val_predict(clf, X, y, cv=cv, n_jobs=-1, method="predict")

        labels = np.unique(y)
        cm = confusion_matrix(y, y_pred_cv, labels=labels)
        acc = accuracy_score(y, y_pred_cv)
        bal_acc = balanced_accuracy_score(y, y_pred_cv)
        f1m = f1_score(y, y_pred_cv, average="macro")
        per_class_acc = (cm.diagonal() / np.maximum(1, cm.sum(axis=1))).astype(float)

        # fit final
        with blas_limits(1):
            clf.fit(X, y)

        # hold-out optionnel
        hold = None
        if holdout and 0.0 < holdout < 0.5:
            Xtr, Xte, ytr, yte = train_test_split(
                X, y, test_size=holdout, stratify=y, random_state=123
            )
            clf_ho = BCI_Trainer._make_pipeline(algo, balanced)
            with blas_limits(1):
                clf_ho.fit(Xtr, ytr)
                y_hat = clf_ho.predict(Xte)
            cm_ho = confusion_matrix(yte, y_hat, labels=labels)
            hold = {
                "acc": float(accuracy_score(yte, y_hat)),
                "bal_acc": float(balanced_accuracy_score(yte, y_hat)),
                "f1_macro": float(f1_score(yte, y_hat, average="macro")),
                "confusion": cm_ho.tolist()
            }

        report = {
            "cv_mean": float(np.mean(scores)),
            "cv_std": float(np.std(scores)),
            "N": int(X.shape[0]),
            "K": int(len(labels)),
            "labels": labels.tolist(),
            "cv_confusion": cm.tolist(),
            "cv_acc": float(acc),
            "cv_bal_acc": float(bal_acc),
            "cv_f1_macro": float(f1m),
            "cv_per_class_acc": per_class_acc.tolist(),
            "algo": algo,
            "balanced": bool(balanced),
            "cv_folds": int(cvk),
            "holdout": hold
        }
        return clf, report

    # ------------------------------------------------------------------ #
    # UI handlers                                                        #
    # ------------------------------------------------------------------ #
    def _on_train(self):
        if not SK_OK:
            if self._lbl:
                self._lbl.setText("scikit-learn missing. pip install scikit-learn")
            return

        ds = self._cached_ds
        if ds is None:
            src = self.inputs["dataset"].value
            if isinstance(src, dict) and src.get("X") is not None and src.get("y") is not None:
                try:
                    X = np.asarray(src["X"])
                    y = np.asarray(src["y"]).ravel()
                    if X.ndim == 2 and y.ndim == 1 and len(y) == X.shape[0] and X.shape[0] > 0:
                        ds = {"X": X, "y": y, "y_names": list(src.get("y_names", []) or [])}
                except Exception:
                    ds = None

        if ds is None:
            if self._lbl:
                self._lbl.setText("No dataset.")
            return

        X = np.asarray(ds["X"], float)
        y = np.asarray(ds["y"], int)
        if X.ndim != 2 or y.ndim != 1 or len(y) != X.shape[0]:
            if self._lbl:
                self._lbl.setText("Shape mismatch.")
            return

        if self._btn_train:
            self._btn_train.setEnabled(False)
        if self._lbl:
            self._lbl.setText("Training… (async)")

        self._future = self._executor.submit(
            BCI_Trainer._train_job, X, y, self._algo, self._cv_k, self._balanced, self._holdout
        )
        self._future.add_done_callback(self._on_done)

    def _on_done(self, fut):
        try:
            clf, report = fut.result()
            self._model = clf
            self._last_report = report
            if self._lbl:
                m, s = report["cv_mean"], report["cv_std"]
                ba, f1m = report["cv_bal_acc"], report["cv_f1_macro"]
                self._lbl.setText(
                    f"Done. CV={m:.3f}±{s:.3f} | BalAcc={ba:.3f} | F1m={f1m:.3f} | N={report['N']} | K={report['K']}"
                )
            self.outputs["model"].on_next(clf)
            self.outputs["report"].on_next(report)
        except Exception as e:
            msg = f"Train error: {e}\n{traceback.format_exc(limit=2)}"
            if self._lbl:
                self._lbl.setText(msg)
        finally:
            if self._btn_train:
                self._btn_train.setEnabled(True)

    def _on_save(self):
        if self._model is None:
            if self._lbl:
                self._lbl.setText("No model to save.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Save model", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                pickle.dump(
                    {"model": self._model, "y_names": self._y_names, "report": self._last_report},
                    f
                )
            if self._lbl:
                self._lbl.setText(f"Saved: {os.path.basename(path)}")
        except Exception as e:
            if self._lbl:
                self._lbl.setText(f"Save error: {e}")

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(None, "Load model", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            self._model = obj.get("model", None)
            self._y_names = obj.get("y_names", self._y_names)
            self._last_report = obj.get("report", None)
            if self._model is None:
                if self._lbl:
                    self._lbl.setText("Invalid file.")
                return
            self.outputs["model"].on_next(self._model)
            if self._last_report is not None:
                self.outputs["report"].on_next(self._last_report)
            if self._lbl:
                self._lbl.setText(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            if self._lbl:
                self._lbl.setText(f"Load error: {e}")

    def _on_export_report(self):
        if not self._last_report:
            if self._lbl:
                self._lbl.setText("No report to export.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Export report", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._last_report, f, indent=2, ensure_ascii=False)
            if self._lbl:
                self._lbl.setText(f"Report exported: {os.path.basename(path)}")
        except Exception as e:
            if self._lbl:
                self._lbl.setText(f"Export error: {e}")