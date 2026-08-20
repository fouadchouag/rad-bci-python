# plugins/bci_collector_node.py
# -*- coding: utf-8 -*-

import os, numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QCheckBox, QFileDialog, QSizePolicy, QStyle
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
        vec = [float(features["GLOBAL"].get(b, 0.0)) for b in bands]
        return np.asarray(vec, dtype=float)
    chs = list(features.keys())
    vals = []
    for b in bands:
        per_ch = [features.get(ch, {}).get(b, np.nan) for ch in chs]
        vals.append(float(np.nanmean(per_ch)))
    return np.asarray(vals, dtype=float)


class BCICollector(BasePlugin):
    help = {
        'summary': 'Collect features and labels into a dataset dict for training. Supports manual recording or marker-based assignment.',
        'usage': 'Connect BCI_Features output. Press Record buttons to assign class labels, or enable use_markers for automatic assignment.',
        'inputs': {
            'features': 'dict — per-channel band values from BCI_Features',
            'band_labels': 'list[str] — feature dimension labels',
            'y_idx': 'int — class index from external markers (when use_markers=True)',
            'feature_mode': 'str — feature mode identifier',
            'config_in': 'dict — generic config from BCI_Config',
        },
        'outputs': {
            'dataset': 'dict — {"X": ndarray(N,F), "y": ndarray(N,), "y_names": list, "bands": list, "feature_mode": str|None}',
            'config_out': 'dict — current parameter state',
        },
        'parameters': [
            {'name': 'K', 'type': 'int', 'default': 2, 'desc': 'Number of classes (2–8)'},
            {'name': 'y_names', 'type': 'list', 'default': ['Left', 'Right'], 'desc': 'Class label names'},
            {'name': 'use_markers', 'type': 'bool', 'default': False, 'desc': 'Use y_idx input for class assignment instead of manual buttons'},
        ],
        'gotchas': [
            'Ensure features are consistent (same bands, same mode) across all recorded trials.',
            'Press "Reset" to clear accumulated data before starting a new recording session.',
            'The dataset output is ready to connect to BCI_Trainer.',
        ],
    }

    name = "BCICollector"
    language = "Python"
    category = "BCI/Utils"

    def setup(self):
        # inputs data
        self.inputs["features"]     = BehaviorSubject(None)
        self.inputs["band_labels"]  = BehaviorSubject(None)
        self.inputs["y_idx"]        = BehaviorSubject(None)
        self.inputs["feature_mode"] = BehaviorSubject(None)

        # 🔌 config (générique)
        self.inputs["config_in"]    = BehaviorSubject(None)

        # outputs
        self.outputs["dataset"] = BehaviorSubject(None)

        # 🔌 sortie config
        self.outputs["config_out"]  = BehaviorSubject(None)

        # state
        self._K = 2
        self._y_names = ["Left", "Right"]
        self._use_markers = False
        self._recording_class = None
        self._X = []
        self._y = []

        self._bands_schema = None
        self._F = None

        # ui refs
        self._lbl = None
        self._spnK = None
        self._name_edits = []
        self._rec_btns = []
        self._classes_box = None
        self._ck_use_markers = None

        self._emit_config()

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        return {"K": int(self._K), "y_names": list(self._y_names[:self._K]), "use_markers": bool(self._use_markers)}

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        if "K" in cfg:
            try: self._K = max(2, min(8, int(cfg.get("K"))))
            except Exception: pass
        if "y_names" in cfg and isinstance(cfg["y_names"], (list, tuple)):
            yn = [str(s) for s in cfg["y_names"]]
            if len(yn) >= 2:
                self._y_names = yn + ([""] * max(0, self._K - len(yn)))
        if "use_markers" in cfg:
            self._use_markers = bool(cfg.get("use_markers"))
        # sync UI
        if self._spnK: self._spnK.setValue(self._K)
        if self._ck_use_markers: self._ck_use_markers.setChecked(self._use_markers)
        self._rebuild_classes_ui()
        self._emit_config()
        self._emit_dataset_status()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- UI ----------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # top row: K + use markers
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Classes:"))
        self._spnK = QSpinBox(); self._spnK.setRange(2, 8); self._spnK.setValue(self._K)
        self._spnK.valueChanged.connect(self._on_change_K)
        r0.addWidget(self._spnK)

        self._ck_use_markers = QCheckBox("Use y_idx (markers)")
        self._ck_use_markers.setChecked(self._use_markers)
        self._ck_use_markers.toggled.connect(self._on_toggle_use_markers)
        r0.addWidget(self._ck_use_markers); r0.addStretch(1)
        v.addLayout(r0)

        # classes rows
        self._classes_box = QVBoxLayout()
        v.addLayout(self._classes_box)
        self._rebuild_classes_ui()

        # buttons row
        r1 = QHBoxLayout()
        btn_save = UiKit.make_btn("Save .npz", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        btn_save.clicked.connect(self._on_save)
        btn_clear = UiKit.make_btn("Clear", role="danger", icon_sp=QStyle.SP_TrashIcon)
        btn_clear.clicked.connect(self._on_clear)
        r1.addWidget(btn_save); r1.addWidget(btn_clear); r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel("Ready. Connect features & (option) y_idx.")
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("BCI Collector", panel, collapsed=False))
        return w

    def _on_change_K(self, v):
        try: k = int(v)
        except Exception: k = 2
        self._K = max(2, min(8, k))
        if len(self._y_names) < self._K:
            self._y_names += [f"Class{i}" for i in range(len(self._y_names), self._K)]
        else:
            self._y_names = self._y_names[:self._K]
        self._rebuild_classes_ui()
        self._emit_config()
        self._emit_dataset_status()

    def _on_toggle_use_markers(self, s):
        self._use_markers = bool(s)
        if self._use_markers:
            self._recording_class = None
            for b in self._rec_btns:
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        self._emit_config()
        self._refresh_counts_ui()

    def _rebuild_classes_ui(self):
        while self._classes_box and self._classes_box.count():
            item = self._classes_box.takeAt(0)
            w = item.widget()
            if w: w.deleteLater()
        self._name_edits.clear(); self._rec_btns.clear()

        for i in range(self._K):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Class {i}:"))
            ed = QLineEdit(self._y_names[i] if i < len(self._y_names) else f"Class{i}")
            self._name_edits.append(ed); row.addWidget(ed, 1)
            btn = UiKit.make_btn(f"Record {i} (idle) — N=0", role="primary", checkable=True)
            btn.clicked.connect(lambda checked, idx=i: self._toggle_rec(idx, checked))
            self._rec_btns.append(btn); row.addWidget(btn)
            wrap = QWidget(); lw = QVBoxLayout(wrap); lw.setContentsMargins(0,0,0,0); lw.setSpacing(0); lw.addLayout(row)
            self._classes_box.addWidget(wrap)
        self._refresh_counts_ui()

    def _toggle_rec(self, idx, checked):
        for i, ed in enumerate(self._name_edits):
            self._y_names[i] = ed.text().strip() or self._y_names[i]
        if self._use_markers:
            for b in self._rec_btns:
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            self._recording_class = None
            self._set_status("Markers mode ON: y = y_idx.")
            return

        if checked:
            for j, b in enumerate(self._rec_btns):
                if j != idx and b.isChecked():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            self._recording_class = int(idx)
        else:
            if self._recording_class == idx:
                self._recording_class = None
        self._refresh_counts_ui()

    def _counts(self):
        if not self._y: return [0]*self._K
        cnt = [0]*self._K
        for yi in self._y:
            if 0 <= yi < self._K:
                cnt[yi] += 1
        return cnt

    def _refresh_counts_ui(self):
        cnt = self._counts()
        for i, btn in enumerate(self._rec_btns):
            on = (self._recording_class == i) and (not self._use_markers)
            btn.setText(f"Record {i} ({'ON' if on else 'idle'}) — N={cnt[i]}")

    def _set_status(self, msg):
        if self._lbl: self._lbl.setText(msg)

    def _emit_dataset_status(self):
        cnt = self._counts()
        n = sum(cnt)
        mode = 'markers' if self._use_markers else 'record buttons'
        self._set_status(f"N={n} | counts={cnt} | K={self._K} | mode={mode}")

    def _add_sample(self, vec, cls):
        try:
            self._X.append(np.asarray(vec, float).copy())
            self._y.append(int(cls))
            self._emit_dataset()
            self._refresh_counts_ui()
            self._emit_dataset_status()
        except Exception as e:
            self._set_status(f"Append error: {e}")

    def _emit_dataset(self):
        try:
            X = np.stack(self._X, axis=0) if len(self._X) > 0 else None
            y = np.asarray(self._y, dtype=int) if len(self._y) > 0 else None
        except Exception:
            X, y = None, None
        bands_in = self.inputs["band_labels"].value
        bands = list(self._bands_schema) if self._bands_schema else (list(bands_in) if bands_in is not None else None)
        ds = {
            "X": X,
            "y": y,
            "y_names": list(self._y_names[:self._K]),
            "bands": bands,
            "feature_mode": str(self.inputs["feature_mode"].value) if self.inputs["feature_mode"].value is not None else None,
        }
        self.outputs["dataset"].on_next(ds)

    def _on_save(self):
        if len(self._y) == 0:
            self._set_status("Nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Save dataset", "", "NumPy Zip (*.npz)")
        if not path: return
        try:
            X = np.stack(self._X, axis=0)
            y = np.asarray(self._y, dtype=int)
            bands = list(self._bands_schema) if self._bands_schema else self.inputs["band_labels"].value
            fm = self.inputs["feature_mode"].value
            np.savez(path,
                     X=X, y=y,
                     y_names=np.array(self._y_names[:self._K], dtype=object),
                     bands=np.array(bands, dtype=object) if bands is not None else None,
                     feature_mode=np.array(fm, dtype=object) if fm is not None else None)
            self._set_status(f"Saved: {os.path.basename(path)} (N={len(y)}, F={X.shape[1]}, K={self._K})")
        except Exception as e:
            self._set_status(f"Save error: {e}")

    def _on_clear(self):
        self._X.clear(); self._y.clear(); self._recording_class=None
        self._bands_schema = None; self._F = None
        for b in self._rec_btns:
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        self._emit_dataset()
        self._refresh_counts_ui()
        self._set_status("Dataset cleared.")

    # ---------- runtime ----------
    def execute(self, **kw):
        # 🔸 config entrante
        cfg = kw.get("config_in", None)
        if isinstance(cfg, dict) and cfg:
            self.import_config(cfg)

        feats = kw.get("features", None)
        bands = kw.get("band_labels", None)
        if feats is None or bands is None:
            return {}

        vec = _features_to_vec(feats, bands)
        if vec is None or not np.all(np.isfinite(vec)):
            self._set_status("Bad features vector.")
            return {}

        if self._bands_schema is None:
            self._bands_schema = list(bands); self._F = int(len(vec))
        else:
            if list(bands) != self._bands_schema or int(len(vec)) != int(self._F):
                self._set_status(f"Band schema changed (was {self._bands_schema}, now {list(bands)}). Auto-clear.")
                self._on_clear()
                self._bands_schema = list(bands); self._F = int(len(vec))

        cls = None
        if self._use_markers:
            y_idx = kw.get("y_idx", None)
            try: yi = int(y_idx) if y_idx is not None else None
            except Exception: yi = None
            if yi is not None and 0 <= yi < self._K:
                cls = yi
            else:
                self._set_status("vec ready but waiting y_idx (markers).")
        else:
            if self._recording_class is not None:
                cls = int(self._recording_class)
            else:
                self._set_status("vec ready but not recording (no class selected).")

        if cls is not None:
            self._add_sample(vec, cls)
        return {}