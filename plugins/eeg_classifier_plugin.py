# plugins/eeg_classifier_plugin.py

import os
import pickle
import numpy as np

from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QComboBox,
    QLayout, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin

try:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
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
            if w.layout(): w.layout().invalidate()
            w.adjustSize(); w.updateGeometry()
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


class EEGClassifierPlugin(BasePlugin):
    help = {
        'summary': '2-class (Left/Right) EEG classifier with record-train-predict workflow.',
        'inputs': {
            'features': 'dict[channel_name -> {band_name: value}] — bandpower features from upstream',
            'band_labels': 'list[str] — ordered band names matching the feature dict',
        },
        'outputs': {
            'pred_label': 'str — predicted class name (e.g. "Left" or "Right")',
            'pred_conf': 'float — confidence of prediction (0..1)',
            'dataset': 'dict {X, y, y_names, feature_mode, bands} — emitted on every sample for metrics nodes',
        },
        'parameters': [
            {'name': 'feature_mode', 'type': 'str', 'default': 'mean_all', 'desc': '"mean_all" (average bandpower across all channels) or "c3c4_ab" (C3/C4 alpha+beta features). Set via UI combo.'},
        ],
        'gotchas': [
            'Requires scikit-learn (pip install scikit-learn) for training.',
            'Train button disabled until both classes have >= 4 samples.',
            'C3/C4 mode silently falls back to MeanAll if C3 or C4 channels are not found in the feature dict.',
            'Saved models are pickle files — do not load untrusted .pkl files.',
            'Model-version mismatch (different bands or feature_mode) can reduce accuracy.',
            'Class names are read from UI text fields; only two classes are supported.',
        ],
        'usage': 'Connect features and band_labels from a BandpowerExt node. Record samples for each class via the UI, train, then predictions stream on pred_label/pred_conf.',
    }

    """
    Classification 2 classes (Left/Right) simplifiée.
    Entrées :
      - features: dict[channel] -> {band: value}
      - band_labels: list[str]
    Sorties :
      - pred_label: str
      - pred_conf: float (0..1)
      - dataset: dict {X, y, y_names, feature_mode, bands}  (pour ClassifierMetrics)
    UI :
      - Tout le panneau est repliable pour ne pas surcharger le montage.
    """
    name = "EEGClassifier"
    language = "Python"
    category = "ML"

    def setup(self):
        # Inputs
        self.inputs["features"] = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)

        # Outputs
        self.outputs["pred_label"] = BehaviorSubject(None)
        self.outputs["pred_conf"] = BehaviorSubject(None)
        self.outputs["dataset"] = BehaviorSubject(None)  # exposition pour les métriques

        # État
        self._bands = None
        self._latest_vec = None
        self._X, self._y = [], []
        self._y_names = ["Left", "Right"]
        self._recording_class = None            # 0 / 1 / None
        self._clf = None
        self._feature_mode = "mean_all"         # "mean_all" ou "c3c4_ab"

        # UI refs
        self._lbl_status = None
        self._btn_rec0 = None
        self._btn_rec1 = None
        self._in_c0 = None
        self._in_c1 = None
        self._btn_train = None
        self._btn_save = None
        self._btn_load = None
        self._btn_clear = None
        self._combo_mode = None

    # ------------------------- UI -------------------------
    def build_widget(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # ---- panneau complet dans une section repliable ----
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # Feature mode
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Features:"))
        self._combo_mode = QComboBox()
        self._combo_mode.addItems(["MeanAll", "C3/C4 alpha+beta"])
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        row_mode.addWidget(self._combo_mode)
        row_mode.addStretch(1)
        lay.addLayout(row_mode)

        # Class names
        row_names = QHBoxLayout()
        row_names.addWidget(QLabel("Class A:"))
        self._in_c0 = QLineEdit(self._y_names[0])
        row_names.addWidget(self._in_c0)
        row_names.addSpacing(8)
        row_names.addWidget(QLabel("Class B:"))
        self._in_c1 = QLineEdit(self._y_names[1])
        row_names.addWidget(self._in_c1)
        row_names.addStretch(1)
        lay.addLayout(row_names)

        # Record buttons
        row_rec = QHBoxLayout()
        self._btn_rec0 = QPushButton("Record A (idle)")
        self._btn_rec1 = QPushButton("Record B (idle)")
        self._btn_rec0.setCheckable(True)
        self._btn_rec1.setCheckable(True)
        self._btn_rec0.clicked.connect(self._toggle_rec0)
        self._btn_rec1.clicked.connect(self._toggle_rec1)
        row_rec.addWidget(self._btn_rec0)
        row_rec.addWidget(self._btn_rec1)
        row_rec.addStretch(1)
        lay.addLayout(row_rec)

        # Train / Save / Load / Clear
        row_ml = QHBoxLayout()
        self._btn_train = QPushButton("Train")
        self._btn_save = QPushButton("Save Model")
        self._btn_load = QPushButton("Load Model")
        self._btn_clear = QPushButton("Clear dataset")
        self._btn_train.clicked.connect(self._on_train)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_load.clicked.connect(self._on_load)
        self._btn_clear.clicked.connect(self._on_clear)
        row_ml.addWidget(self._btn_train)
        row_ml.addWidget(self._btn_save)
        row_ml.addWidget(self._btn_load)
        row_ml.addWidget(self._btn_clear)
        row_ml.addStretch(1)
        lay.addLayout(row_ml)

        # Status
        self._lbl_status = QLabel("No data | sklearn: " + ("OK" if SKLEARN_OK else "missing"))
        lay.addWidget(self._lbl_status)

        # Section repliable (fermée par défaut)
        sec = _CollapsibleSection("Paramètres & Enregistrement", panel, collapsed=True)
        root.addWidget(sec)

        return w

    # ------------------------- RUNTIME -------------------------
    def execute(self, **kwargs):
        features = kwargs.get("features", None)
        bands = kwargs.get("band_labels", None)

        if bands is not None:
            self._bands = list(bands)

        if features is None or self._bands is None:
            self._set_status("Waiting for features/bands")
            return {}

        # Vectorisation
        vec = self._vector_from_features(features, self._bands)
        self._latest_vec = vec

        # Enregistrement (si actif)
        self._update_recording(vec)

        # Prédiction
        if self._clf is not None:
            try:
                proba = float(max(self._clf.predict_proba([vec])[0]))
                pred_idx = int(self._clf.predict([vec])[0])
                pred_name = self._y_names[pred_idx]
                self.outputs["pred_label"].on_next(pred_name)
                self.outputs["pred_conf"].on_next(proba)
                self._set_status(f"Pred: {pred_name} ({proba:.2f}) | A:{self._count(0)} B:{self._count(1)} | mode={self._feature_mode}")
            except Exception as e:
                self._set_status(f"Predict error: {e}")
        else:
            self._set_status(f"Collecting… A:{self._count(0)} B:{self._count(1)} | mode={self._feature_mode}")

        return {}

    # ------------------------- HELPERS -------------------------
    def _on_mode_changed(self, _idx):
        txt = self._combo_mode.currentText().strip().lower()
        self._feature_mode = "c3c4_ab" if "c3/c4" in txt else "mean_all"

        # (optionnel) reset enregistrement pour éviter mélange de features hétérogènes
        # self._X.clear(); self._y.clear(); self._emit_dataset()

    def _vector_from_features(self, features_dict, bands):
        """
        features_dict: {channel: {band: value}}
        bands: list[str] (ordre des bandes venant de BandpowerExt)
        """
        if self._feature_mode == "c3c4_ab":
            return self._vec_c3c4_alpha_beta(features_dict, bands)
        else:
            # MeanAll : moyenne par bande sur tous les canaux
            vals = []
            for b in bands:
                per_ch = [features_dict.get(ch, {}).get(b, np.nan) for ch in features_dict.keys()]
                vals.append(np.nanmean(per_ch))
            arr = np.array(vals, dtype=float)
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    def _vec_c3c4_alpha_beta(self, features_dict, bands):
        # Choisir les noms de bandes
        def pick_band(candidates):
            for name in candidates:
                if name in bands:
                    return name
            return None

        b_alpha = pick_band(["alpha", "mu"]) or (bands[0] if bands else "alpha")
        b_beta  = pick_band(["beta"])        or (bands[1] if len(bands) > 1 else "beta")

        # Trouver C3 / C4 de façon tolérante
        def find_chan(pattern):
            pu = pattern.upper()
            for ch in features_dict.keys():
                if pu in ch.upper():
                    return ch
            return None

        chC3 = find_chan("C3")
        chC4 = find_chan("C4")

        # fallback -> MeanAll si C3/C4 manquants
        if chC3 is None or chC4 is None:
            vals = []
            for b in bands:
                per_ch = [features_dict.get(ch, {}).get(b, np.nan) for ch in features_dict.keys()]
                vals.append(np.nanmean(per_ch))
            arr = np.array(vals, dtype=float)
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

        def get(ch, b):
            return float(features_dict.get(ch, {}).get(b, np.nan))

        aC3 = get(chC3, b_alpha); bC3 = get(chC3, b_beta)
        aC4 = get(chC4, b_alpha); bC4 = get(chC4, b_beta)

        def safe_div(a, b):
            a = 0.0 if not np.isfinite(a) else a
            b = 1e-12 if (not np.isfinite(b) or abs(b) < 1e-12) else b
            return a / b

        vec = np.array([
            aC3, bC3, aC4, bC4,
            aC3 - aC4, bC3 - bC4,
            safe_div(aC3, aC4), safe_div(bC3, bC4)
        ], dtype=float)

        return np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

    def _toggle_rec0(self, checked):
        if checked:
            if self._btn_rec1.isChecked():
                self._btn_rec1.setChecked(False)
            self._recording_class = 0
            self._btn_rec0.setText("Record A (ON)")
            self._btn_rec1.setText("Record B (idle)")
        else:
            self._recording_class = None
            self._btn_rec0.setText("Record A (idle)")

        self._y_names[0] = self._in_c0.text().strip() or "Left"
        self._y_names[1] = self._in_c1.text().strip() or "Right"

    def _toggle_rec1(self, checked):
        if checked:
            if self._btn_rec0.isChecked():
                self._btn_rec0.setChecked(False)
            self._recording_class = 1
            self._btn_rec1.setText("Record B (ON)")
            self._btn_rec0.setText("Record A (idle)")
        else:
            self._recording_class = None
            self._btn_rec1.setText("Record B (idle)")

        self._y_names[0] = self._in_c0.text().strip() or "Left"
        self._y_names[1] = self._in_c1.text().strip() or "Right"

    def _update_recording(self, vec):
        if self._recording_class is None:
            return
        try:
            self._X.append(vec.astype(float).copy())
            self._y.append(int(self._recording_class))
            self._emit_dataset()
        except Exception:
            pass

    def _emit_dataset(self):
        try:
            X = np.stack(self._X, axis=0) if len(self._X) > 0 else None
            y = np.array(self._y, dtype=int) if len(self._y) > 0 else None
        except Exception:
            X, y = None, None
        payload = {
            "X": X,
            "y": y,
            "y_names": list(self._y_names),
            "feature_mode": self._feature_mode,
            "bands": list(self._bands) if self._bands is not None else None,
        }
        self.outputs["dataset"].on_next(payload)

    def _count(self, cls_idx):
        return sum(1 for yy in self._y if yy == cls_idx)

    def _on_train(self):
        if not SKLEARN_OK:
            self._set_status("scikit-learn not installed. `pip install scikit-learn`")
            return
        if len(self._X) < 4 or len(set(self._y)) < 2:
            self._set_status("Need more samples (both classes).")
            return
        try:
            X = np.stack(self._X, axis=0)
            y = np.array(self._y, dtype=int)
            self._clf = make_pipeline(
                StandardScaler(),
                LogisticRegression(max_iter=1000)
            )
            self._clf.fit(X, y)
            self._set_status(f"Model trained | N={len(y)} | A:{self._count(0)} B:{self._count(1)} | mode={self._feature_mode}")
        except Exception as e:
            self._set_status(f"Train error: {e}")

    def _on_save(self):
        if self._clf is None:
            self._set_status("No model to save.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Save model", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            with open(path, "wb") as f:
                pickle.dump({
                    "clf": self._clf,
                    "y_names": self._y_names,
                    "bands": self._bands,
                    "feature_mode": self._feature_mode
                }, f)
            self._set_status(f"Model saved: {os.path.basename(path)}")
        except Exception as e:
            self._set_status(f"Save error: {e}")

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(None, "Load model", "", "Pickle (*.pkl)")
        if not path:
            return
        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)
            self._clf = obj.get("clf", None)
            self._y_names = obj.get("y_names", self._y_names)
            self._bands = obj.get("bands", self._bands)
            self._feature_mode = obj.get("feature_mode", self._feature_mode)

            # refresh UI
            if self._in_c0: self._in_c0.setText(self._y_names[0])
            if self._in_c1: self._in_c1.setText(self._y_names[1])
            if self._combo_mode:
                self._combo_mode.setCurrentIndex(1 if self._feature_mode == "c3c4_ab" else 0)

            self._set_status(f"Model loaded: {os.path.basename(path)} | mode={self._feature_mode}")
        except Exception as e:
            self._set_status(f"Load error: {e}")

    def _on_clear(self):
        self._X.clear()
        self._y.clear()
        self._clf = None
        # --- reset prédictions pour les consommateurs (BallFeedback)
        self.outputs["pred_label"].on_next(None)
        self.outputs["pred_conf"].on_next(0.0)
        # --- notifier dataset vidé
        self.outputs["dataset"].on_next(None)
        self._emit_dataset()
        self._set_status("Dataset cleared.")

    def _set_status(self, msg):
        if self._lbl_status:
            self._lbl_status.setText(msg)