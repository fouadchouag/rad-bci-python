# plugins/eeg_classifier_2.py
# -*- coding: utf-8 -*-

import os, pickle, numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFileDialog,
    QComboBox, QSpinBox, QSizePolicy, QGroupBox, QTabWidget, QCheckBox
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin

# ---- sip guard: éviter "wrapped C/C++ object ... deleted"
try:
    import sip
    def _alive(w):
        try: return (w is not None) and (not sip.isdeleted(w))
        except Exception: return w is not None
except Exception:
    def _alive(w): return w is not None

# --- scikit-learn (optionnel)
try:
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    SKLEARN_OK = True
except Exception:
    SKLEARN_OK = False


# ---------- mini bandpower (fallback) ----------
def _bands_preset(preset="MI"):
    if "Full" in preset:
        return [("delta",1,4),("theta",4,8),("alpha",8,12),("beta",13,30)]
    return [("alpha",8,12),("beta",13,30)]

def _bandpower_vec(segment, ch_names, sfreq, preset="MI", relative=True, nperseg=256, feature_mode="mean_all"):
    arr = np.asarray(segment)
    if arr.ndim == 1: arr = arr[None,:]
    if arr.shape[0] > arr.shape[1]: arr = arr.T
    n_ch, n_s = arr.shape
    win_len = max(16, min(nperseg, n_s))
    hop = max(1, win_len//2); win = np.hanning(win_len)
    nfft = int(2**int(np.ceil(np.log2(win_len))))
    freqs = np.fft.rfftfreq(nfft, d=1.0/float(sfreq))
    idx_1_40 = np.where((freqs>=1.0)&(freqs<=40.0))[0]

    psd = np.zeros((n_ch, len(freqs)), dtype=np.float64); n_win=0; start=0
    while start+win_len<=n_s:
        xw = arr[:,start:start+win_len]*win[None,:]
        F = np.fft.rfft(xw, n=nfft, axis=1)
        P = (np.abs(F)**2)/np.sum(win**2); psd += P; n_win += 1; start += hop
    if n_win==0:
        F=np.fft.rfft(arr*np.hanning(n_s)[None,:], n=nfft, axis=1)
        psd=(np.abs(F)**2)/np.sum(np.hanning(n_s)**2); n_win=1
    psd/=float(n_win)

    bands=_bands_preset("Full" if "Full" in (preset or "") else "MI")
    bp = []
    denom = np.maximum(1e-20, np.sum(psd[:,idx_1_40], axis=1)) if relative else 1.0
    for _,f0,f1 in bands:
        idx=np.where((freqs>=f0)&(freqs<=f1))[0]
        val=np.sum(psd[:,idx], axis=1)
        if relative: val=val/denom
        bp.append(val)
    bp = np.stack(bp, axis=1)
    bands_names=[b[0] for b in bands]

    if feature_mode=="c3c4_ab":
        def find(pattern):
            pu=pattern.upper()
            for i,ch in enumerate(ch_names or []):
                if pu in str(ch).upper(): return i
            return None
        iC3=find("C3"); iC4=find("C4")
        if iC3 is None or iC4 is None:
            vec = np.nanmean(bp, axis=0)
            return np.nan_to_num(vec, nan=0.0), bands_names
        def idx_of(name):
            for i,n in enumerate(bands_names):
                if n==name: return i
            return 0
        ia=idx_of("alpha"); ib=idx_of("beta")
        aC3=bp[iC3,ia]; bC3=bp[iC3,ib]; aC4=bp[iC4,ia]; bC4=bp[iC4,ib]
        def sdiv(a,b):
            a=0.0 if not np.isfinite(a) else a
            b=1e-12 if (not np.isfinite(b) or abs(b)<1e-12) else b
            return a/b
        vec=np.array([aC3,bC3,aC4,bC4,aC3-aC4,bC3-bC4,sdiv(aC3,aC4),sdiv(bC3,bC4)], float)
        return np.nan_to_num(vec, nan=0.0), ["aC3","bC3","aC4","bC4","aC3-aC4","bC3-bC4","aC3/aC4","bC3/bC4"]
    else:
        vec = np.nanmean(bp, axis=0)
        return np.nan_to_num(vec, nan=0.0), bands_names


class EEGClassifier2(BasePlugin):
    """
    BCI trainer compact : collecte multi-classe, CV, entraînement et prédiction.

    Entrées :
      - features + band_labels (reco)  OU  segment + sfreq + ch_names (fallback)
    Sorties :
      - pred_label (str), pred_conf (float), pred_idx (int), proba (dict), dataset (dict)
    """
    name = "EEGClassifier_2"
    language = "Python"
    category = "ML"

    # ---------------- LIFECYCLE ----------------
    def setup(self):
        # Inputs
        self.inputs["features"]    = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)
        self.inputs["segment"]     = BehaviorSubject(None)
        self.inputs["sfreq"]       = BehaviorSubject(None)
        self.inputs["ch_names"]    = BehaviorSubject(None)

        # Outputs
        self.outputs["pred_label"] = BehaviorSubject(None)
        self.outputs["pred_conf"]  = BehaviorSubject(None)
        self.outputs["pred_idx"]   = BehaviorSubject(None)
        self.outputs["proba"]      = BehaviorSubject(None)
        self.outputs["dataset"]    = BehaviorSubject(None)

        # État interne
        self._bands = None
        self._feature_mode = "mean_all"  # "mean_all" | "c3c4_ab"
        self._clf = None
        self._X, self._y = [], []
        self._K = 2
        self._y_names = ["Left","Right"]
        self._recording_class = None      # collecte continue
        self._snap_class = None           # collecte “1 shot”
        self._min_per_class = 4
        self._cv_folds = 5
        self._class_weight_balanced = True

        # UI refs
        self._tabs = None
        self._lbl_status = None
        self._combo_mode = None
        self._spn_k = None
        self._spn_min = None
        self._spn_cv = None
        self._chk_balanced = None
        self._name_edits = []
        self._rec_btns = []
        self._snap_btns = []
        self._counts_labels = []
        self._collect_box = None
        self._btn_train = None
        self._lbl_pred = None
        self._lbl_conf = None
        self._lbl_cv = None

    # ---------------- UI ----------------
    def build_widget(self):
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        self._tabs = QTabWidget(w); root.addWidget(self._tabs)

        # ---- TAB Collect ----
        tab_collect = QWidget(); cl = QVBoxLayout(tab_collect); cl.setContentsMargins(8,8,8,8); cl.setSpacing(6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Features:"))
        self._combo_mode = QComboBox(); self._combo_mode.addItems(["MeanAll","C3/C4 alpha+beta"])
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        top.addWidget(self._combo_mode)
        top.addSpacing(12)
        top.addWidget(QLabel("Classes:"))
        self._spn_k = QSpinBox(); self._spn_k.setRange(2, 8); self._spn_k.setValue(self._K)
        self._spn_k.valueChanged.connect(self._set_num_classes)
        top.addWidget(self._spn_k)
        top.addStretch(1)
        cl.addLayout(top)

        gb = QGroupBox("Enregistrement"); cl.addWidget(gb)
        gbl = QVBoxLayout(gb); gbl.setContentsMargins(8,8,8,8); gbl.setSpacing(4)

        self._collect_box = QVBoxLayout(); self._collect_box.setContentsMargins(0,0,0,0); self._collect_box.setSpacing(4)
        gbl.addLayout(self._collect_box)

        row_btns = QHBoxLayout()
        btn_export = QPushButton("Export .npz"); btn_export.clicked.connect(self._on_export_npz); row_btns.addWidget(btn_export)
        btn_import = QPushButton("Import .npz"); btn_import.clicked.connect(self._on_import_npz); row_btns.addWidget(btn_import)
        btn_clear  = QPushButton("Clear dataset"); btn_clear.clicked.connect(self._on_clear); row_btns.addWidget(btn_clear)
        row_btns.addStretch(1)
        gbl.addLayout(row_btns)

        self._lbl_status = QLabel("Collect: idle | sklearn: " + ("OK" if SKLEARN_OK else "missing"))
        cl.addWidget(self._lbl_status)

        # ---- TAB Train ----
        tab_train = QWidget(); tl = QVBoxLayout(tab_train); tl.setContentsMargins(8,8,8,8); tl.setSpacing(6)

        row_t = QHBoxLayout()
        row_t.addWidget(QLabel("Min/Classe:"))
        self._spn_min = QSpinBox(); self._spn_min.setRange(1, 200); self._spn_min.setValue(self._min_per_class)
        self._spn_min.valueChanged.connect(lambda v: (setattr(self, "_min_per_class", int(v)), self._refresh_train_button()))
        row_t.addWidget(self._spn_min)
        row_t.addSpacing(12)
        row_t.addWidget(QLabel("CV folds:"))
        self._spn_cv = QSpinBox(); self._spn_cv.setRange(2, 12); self._spn_cv.setValue(self._cv_folds)
        self._spn_cv.valueChanged.connect(lambda v: setattr(self, "_cv_folds", int(v)))
        row_t.addWidget(self._spn_cv)
        row_t.addSpacing(12)
        self._chk_balanced = QCheckBox("class_weight='balanced'"); self._chk_balanced.setChecked(self._class_weight_balanced)
        self._chk_balanced.toggled.connect(lambda s: setattr(self, "_class_weight_balanced", bool(s)))
        row_t.addWidget(self._chk_balanced)
        row_t.addStretch(1)
        tl.addLayout(row_t)

        row_train_btns = QHBoxLayout()
        self._btn_train = QPushButton("Train"); self._btn_train.clicked.connect(self._on_train); row_train_btns.addWidget(self._btn_train)
        btn_save = QPushButton("Save Model"); btn_save.clicked.connect(self._on_save); row_train_btns.addWidget(btn_save)
        btn_load = QPushButton("Load Model"); btn_load.clicked.connect(self._on_load); row_train_btns.addWidget(btn_load)
        row_train_btns.addStretch(1)
        tl.addLayout(row_train_btns)

        self._lbl_cv = QLabel("CV: n/a"); tl.addWidget(self._lbl_cv)

        # ---- TAB Predict ----
        tab_pred = QWidget(); pl = QVBoxLayout(tab_pred); pl.setContentsMargins(8,8,8,8); pl.setSpacing(6)
        self._lbl_pred = QLabel("Pred: —"); pl.addWidget(self._lbl_pred)
        self._lbl_conf = QLabel("Conf: —"); pl.addWidget(self._lbl_conf)

        # Tabs
        self._tabs.addTab(tab_collect, "Collect")
        self._tabs.addTab(tab_train, "Train")
        self._tabs.addTab(tab_pred, "Predict")

        # Init
        self._set_num_classes(self._K)
        self._refresh_train_button()
        return w

    # ------- Collect rows (K classes) -------
    def _set_num_classes(self, K):
        try: K = int(K)
        except Exception: K = 2
        K = max(2, min(8, K))
        self._K = K

        # resize y_names
        if len(self._y_names) < K:
            self._y_names += [f"Class{i+1}" for i in range(len(self._y_names), K)]
        else:
            self._y_names = self._y_names[:K]

        # clear UI list
        if self._collect_box:
            while self._collect_box.count():
                item = self._collect_box.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None); w.deleteLater()

        self._name_edits.clear(); self._rec_btns.clear(); self._snap_btns.clear(); self._counts_labels.clear()

        # build rows
        for i in range(K):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Class {i}"))
            ed = QLineEdit(self._y_names[i]); self._name_edits.append(ed); row.addWidget(ed, 1)

            lbl_cnt = QLabel("N=0"); self._counts_labels.append(lbl_cnt); row.addWidget(lbl_cnt)

            btn_rec = QPushButton(f"Record {i}"); btn_rec.setCheckable(True)
            btn_rec.clicked.connect(lambda checked, idx=i: self._toggle_record(idx, checked))
            self._rec_btns.append(btn_rec); row.addWidget(btn_rec)

            btn_snap = QPushButton(f"Snap {i}")
            btn_snap.clicked.connect(lambda _=False, idx=i: self._queue_snap(idx))
            self._snap_btns.append(btn_snap); row.addWidget(btn_snap)

            row.addStretch(1)
            wrap = QWidget(); lw = QVBoxLayout(wrap); lw.setContentsMargins(0,0,0,0); lw.setSpacing(0); lw.addLayout(row)
            if self._collect_box: self._collect_box.addWidget(wrap)

        self._refresh_counts_ui()
        self._refresh_train_button()
        if self._lbl_status: self._lbl_status.setText(f"Collect: ready | classes={self._K}")

    # ---------------- RUNTIME ----------------
    def execute(self, **kw):
        features = kw.get("features", None)
        bands = kw.get("band_labels", None)

        # Fallback: calcul features si segment brut
        if features is None:
            seg = kw.get("segment", None); sf = kw.get("sfreq", None); ch = kw.get("ch_names", None)
            if seg is not None and (sf is not None) and (ch is not None):
                try:
                    sf = float(sf)
                    vec, vec_names = _bandpower_vec(seg, ch, sf, preset="MI", relative=True, nperseg=256, feature_mode=self._feature_mode)
                    features = {"GLOBAL": {name: float(val) for name,val in zip(vec_names, vec)}}
                    bands = list(vec_names)
                except Exception as e:
                    self._set_status(f"Auto-features error: {e}")
                    features = None

        if bands is not None: self._bands = list(bands)
        if features is None or self._bands is None:
            self._set_status("Waiting for features/bands"); return {}

        vec = self._vector_from_features(features, self._bands)

        # collecte "snap" prioritaire (1 shot)
        if self._snap_class is not None:
            self._append_sample(vec, int(self._snap_class))
            self._snap_class = None

        # collecte continue
        if self._recording_class is not None:
            self._append_sample(vec, int(self._recording_class))

        # prédiction si modèle dispo
        if self._clf is not None:
            try:
                proba = self._clf.predict_proba([vec])[0]
                pred_idx = int(np.argmax(proba))
                pred_name = self._y_names[pred_idx] if pred_idx < len(self._y_names) else f"Class{pred_idx}"
                self.outputs["pred_label"].on_next(pred_name)
                self.outputs["pred_conf"].on_next(float(np.max(proba)))
                self.outputs["pred_idx"].on_next(pred_idx)
                self.outputs["proba"].on_next({
                    self._y_names[i] if i < len(self._y_names) else f"Class{i}": float(p)
                    for i,p in enumerate(proba)
                })
                if _alive(self._lbl_pred): self._lbl_pred.setText(f"Pred: {pred_name}")
                if _alive(self._lbl_conf): self._lbl_conf.setText(f"Conf: {np.max(proba):.2f}")
                self._set_status(f"Pred {pred_name} ({np.max(proba):.2f})")
            except Exception as e:
                self._set_status(f"Predict error: {e}")
        else:
            self._set_status(f"Collecting... N={len(self._y)} | min/cls={self._min_per_class} | mode={self._feature_mode}")

        return {}

    # ---------------- Helpers ----------------
    def _on_mode_changed(self, idx: int):
        try:
            label = self._combo_mode.itemText(idx).lower() if _alive(self._combo_mode) else ""
        except Exception:
            label = ""
        self._feature_mode = "c3c4_ab" if "c3" in label else "mean_all"
        self._emit_dataset()
        self._set_status(f"Feature mode: {self._feature_mode}")

    def _vector_from_features(self, features_dict, bands):
        if self._feature_mode == "c3c4_ab":
            return self._vec_c3c4(features_dict, bands)
        vals=[]; chs=list(features_dict.keys())
        for b in bands:
            per_ch=[features_dict.get(ch,{}).get(b, np.nan) for ch in chs]
            vals.append(np.nanmean(per_ch))
        arr=np.array(vals, float)
        return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    def _vec_c3c4(self, features_dict, bands):
        def find(pattern):
            pu=pattern.upper()
            for ch in features_dict.keys():
                if pu in str(ch).upper(): return ch
            return None
        chC3=find("C3"); chC4=find("C4")
        if chC3 is None or chC4 is None:
            vals=[]; chs=list(features_dict.keys())
            for b in bands:
                per_ch=[features_dict.get(ch,{}).get(b, np.nan) for ch in chs]
                vals.append(np.nanmean(per_ch))
            arr=np.array(vals, float)
            return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        def get(ch,b): return float(features_dict.get(ch,{}).get(b, np.nan))
        b_alpha = "alpha" if "alpha" in bands else bands[0]
        b_beta  = "beta"  if "beta"  in bands else (bands[1] if len(bands)>1 else bands[0])
        aC3=get(chC3,b_alpha); bC3=get(chC3,b_beta); aC4=get(chC4,b_alpha); bC4=get(chC4,b_beta)
        def sdiv(a,b):
            a=0.0 if not np.isfinite(a) else a
            b=1e-12 if (not np.isfinite(b) or abs(b)<1e-12) else b
            return a/b
        vec=np.array([aC3,bC3,aC4,bC4,aC3-aC4,bC3-bC4,sdiv(aC3,aC4),sdiv(bC3,bC4)], float)
        return np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

    def _toggle_record(self, idx, checked):
        # sync noms
        for i,ed in enumerate(self._name_edits):
            self._y_names[i] = ed.text().strip() or self._y_names[i]
        if checked:
            # un seul enregistrement à la fois
            for j,btn in enumerate(self._rec_btns):
                if j!=idx and _alive(btn) and btn.isChecked():
                    btn.blockSignals(True); btn.setChecked(False); btn.blockSignals(False)
            self._recording_class = int(idx)
            self._set_status(f"Recording class {idx} ({self._y_names[idx]})")
        else:
            if self._recording_class == idx:
                self._recording_class = None
                self._set_status("Recording OFF")
        self._refresh_counts_ui()
        self._refresh_train_button()

    def _queue_snap(self, idx):
        for i,ed in enumerate(self._name_edits):
            self._y_names[i] = ed.text().strip() or self._y_names[i]
        self._snap_class = int(idx)
        self._set_status(f"Snap queued for class {idx} ({self._y_names[idx]})")

    def _append_sample(self, vec, cls_idx):
        try:
            self._X.append(np.asarray(vec, float).copy())
            self._y.append(int(cls_idx))
            self._emit_dataset()
            self._refresh_counts_ui()
        except Exception as e:
            self._set_status(f"Append error: {e}")

    def _counts(self):
        if not self._y: return [0]*self._K
        cnt=[0]*self._K
        for yi in self._y:
            if 0<=yi<self._K: cnt[yi]+=1
        return cnt

    def _refresh_counts_ui(self):
        cnt = self._counts()
        for i,lbl in enumerate(self._counts_labels):
            try:
                lbl.setText(f"N={cnt[i] if i < len(cnt) else 0}")
            except Exception:
                pass

    def _refresh_train_button(self):
        if not _alive(self._btn_train): return
        cnt = self._counts()
        ok = (len(cnt)==self._K) and all(c>=self._min_per_class for c in cnt) and (len(set(self._y))>=2)
        try: self._btn_train.setEnabled(ok)
        except Exception: pass

    def _emit_dataset(self):
        try:
            X = np.stack(self._X, axis=0) if len(self._X)>0 else None
            y = np.array(self._y, dtype=int) if len(self._y)>0 else None
        except Exception:
            X, y = None, None
        payload = {
            "X": X, "y": y,
            "y_names": list(self._y_names[:self._K]),
            "feature_mode": self._feature_mode,
            "bands": list(self._bands) if self._bands is not None else None,
        }
        self.outputs["dataset"].on_next(payload)

    # ---------------- ML ----------------
    def _on_train(self):
        if not SKLEARN_OK:
            self._set_status("scikit-learn not installed. `pip install scikit-learn`"); return
        cnt = self._counts()
        if (len(cnt)<self._K) or (not all(c>=self._min_per_class for c in cnt)) or (len(set(self._y))<2):
            self._set_status(f"Need ≥{self._min_per_class}/class (counts={cnt})."); return
        try:
            X = np.stack(self._X, axis=0); y = np.array(self._y, dtype=int)
            class_weight = 'balanced' if self._class_weight_balanced else None
            pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, multi_class="auto", class_weight=class_weight))

            # CV rapide
            k = min(self._cv_folds, np.min([np.sum(y==i) for i in np.unique(y)]))
            k = max(2, k)  # au moins 2 folds si possible
            cv = StratifiedKFold(n_splits=k, shuffle=True, random_state=42)
            try:
                scores = cross_val_score(pipe, X, y, cv=cv, n_jobs=None)
                if _alive(self._lbl_cv): self._lbl_cv.setText(f"CV ({k}-fold): acc={np.mean(scores):.2f} ± {np.std(scores):.2f}")
            except Exception:
                if _alive(self._lbl_cv): self._lbl_cv.setText("CV: skipped")

            self._clf = pipe.fit(X, y)
            self._set_status(f"Model trained | N={len(y)} | counts={cnt} | mode={self._feature_mode}")
        except Exception as e:
            self._set_status(f"Train error: {e}")

    def _on_save(self):
        if self._clf is None: self._set_status("No model to save."); return
        path,_ = QFileDialog.getSaveFileName(None,"Save model","","Pickle (*.pkl)")
        if not path: return
        try:
            with open(path,"wb") as f:
                pickle.dump({
                    "clf": self._clf,
                    "y_names": self._y_names[:self._K],
                    "bands": self._bands,
                    "feature_mode": self._feature_mode,
                    "K": self._K,
                    "min_per_class": self._min_per_class
                }, f)
            self._set_status(f"Model saved: {os.path.basename(path)}")
        except Exception as e:
            self._set_status(f"Save error: {e}")

    def _on_load(self):
        path,_ = QFileDialog.getOpenFileName(None,"Load model","","Pickle (*.pkl)")
        if not path: return
        try:
            with open(path,"rb") as f: obj = pickle.load(f)
            self._clf = obj.get("clf", None)
            self._y_names = obj.get("y_names", self._y_names)
            self._bands = obj.get("bands", self._bands)
            self._feature_mode = obj.get("feature_mode", self._feature_mode)
            K = int(obj.get("K", len(self._y_names)))
            self._min_per_class = int(obj.get("min_per_class", self._min_per_class))
            if _alive(self._spn_min): self._spn_min.setValue(self._min_per_class)
            if _alive(self._combo_mode): self._combo_mode.setCurrentIndex(1 if self._feature_mode=="c3c4_ab" else 0)
            # important : reconstruire les lignes selon K et y_names
            if _alive(self._spn_k): self._spn_k.setValue(K)
            else: self._set_num_classes(K)
            self._set_status(f"Model loaded: {os.path.basename(path)} | K={K} | mode={self._feature_mode}")
        except Exception as e:
            self._set_status(f"Load error: {e}")

    # ---------------- Dataset I/O ----------------
    def _on_export_npz(self):
        path,_ = QFileDialog.getSaveFileName(None,"Export dataset",".","NumPy Zip (*.npz)")
        if not path: return
        try:
            X = np.stack(self._X, axis=0) if len(self._X)>0 else np.empty((0,0))
            y = np.array(self._y, dtype=int) if len(self._y)>0 else np.empty((0,), dtype=int)
            np.savez(path, X=X, y=y, y_names=np.array(self._y_names[:self._K], dtype=object),
                     bands=np.array(self._bands if self._bands is not None else [], dtype=object),
                     feature_mode=self._feature_mode)
            self._set_status(f"Dataset exported: {os.path.basename(path)} (N={len(y)})")
        except Exception as e:
            self._set_status(f"Export error: {e}")

    def _on_import_npz(self):
        path,_ = QFileDialog.getOpenFileName(None,"Import dataset",".","NumPy Zip (*.npz)")
        if not path: return
        try:
            data = np.load(path, allow_pickle=True)
            X = data.get("X", np.empty((0,0))); y = data.get("y", np.empty((0,),dtype=int))
            y_names = list(map(str, data.get("y_names", []))) if "y_names" in data.files else None
            bands = list(map(str, data.get("bands", []))) if "bands" in data.files else None
            feature_mode = str(data.get("feature_mode", self._feature_mode))

            self._X = [row.copy() for row in (X if X.size>0 else np.empty((0,)))]
            self._y = [int(v) for v in (y.tolist() if y.size>0 else [])]
            if y_names:
                self._y_names = list(y_names)
                newK = len(self._y_names)
                if _alive(self._spn_k): self._spn_k.setValue(newK)
                else: self._set_num_classes(newK)
            if bands: self._bands = list(bands)
            self._feature_mode = feature_mode
            if _alive(self._combo_mode): self._combo_mode.setCurrentIndex(1 if self._feature_mode=="c3c4_ab" else 0)

            self._emit_dataset(); self._refresh_counts_ui(); self._refresh_train_button()
            self._set_status(f"Dataset imported: {os.path.basename(path)} (N={len(self._y)})")
        except Exception as e:
            self._set_status(f"Import error: {e}")

    def _on_clear(self):
        self._X.clear(); self._y.clear(); self._clf=None; self._recording_class=None; self._snap_class=None
        for btn in list(self._rec_btns):
            if _alive(btn):
                btn.blockSignals(True); btn.setChecked(False); btn.blockSignals(False)
        self._emit_dataset(); self._refresh_counts_ui(); self._refresh_train_button()
        self._set_status("Dataset cleared.")

    # ---------------- UI status ----------------
    def _set_status(self, msg):
        if self._lbl_status and _alive(self._lbl_status):
            self._lbl_status.setText(msg)
