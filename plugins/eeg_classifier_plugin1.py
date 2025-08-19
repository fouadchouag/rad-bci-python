# plugins/eeg_classifier_plugin.py
# -*- coding: utf-8 -*-

import os, pickle, numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFileDialog,
    QComboBox, QSpinBox, QSizePolicy, QGroupBox
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin

# ---- sip guard
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


class EEGClassifierPlugin(BasePlugin):
    """
    Classif EEG multi-classe avec enregistrement par classe puis entraînement.

    Entrées :
      - features + band_labels (reco)   OU   segment + sfreq + ch_names (fallback)
    Sorties :
      - pred_label, pred_conf, pred_idx, proba, dataset
    """
    name = "EEGClassifier_1"
    language = "Python"
    category = "ML"

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

        # État
        self._bands = None
        self._feature_mode = "mean_all"     # "mean_all" | "c3c4_ab"
        self._clf = None
        self._X, self._y = [], []
        self._K = 2
        self._y_names = ["Left","Right"]
        self._recording_class = None
        self._min_per_class = 4

        # UI refs
        self._lbl_status = None
        self._combo_mode = None
        self._spn_k = None
        self._spn_min = None
        self._name_edits = []
        self._rec_btns = []
        self._classes_container = None
        self._classes_box = None
        self._btn_train = None

    # ---------------- UI ----------------
    def build_widget(self):
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        w.setMinimumWidth(380)                  # force un peu de place
        w.setMinimumHeight(260)

        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        # Paramètres
        params_box = QGroupBox("Paramètres", w)
        params_box.setMinimumHeight(110)
        pv = QVBoxLayout(params_box); pv.setContentsMargins(8,8,8,8); pv.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Features:", parent=params_box))
        self._combo_mode = QComboBox(parent=params_box)
        self._combo_mode.addItems(["MeanAll","C3/C4 alpha+beta"])
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        r0.addWidget(self._combo_mode); r0.addStretch(1); pv.addLayout(r0)

        rK = QHBoxLayout()
        rK.addWidget(QLabel("Classes:", parent=params_box))
        self._spn_k = QSpinBox(parent=params_box); self._spn_k.setRange(2, 6); self._spn_k.setValue(self._K)
        self._spn_k.valueChanged.connect(self._rebuild_classes_ui)
        rK.addWidget(self._spn_k); rK.addSpacing(12)
        rK.addWidget(QLabel("Min/Classe:", parent=params_box))
        self._spn_min = QSpinBox(parent=params_box); self._spn_min.setRange(1, 50); self._spn_min.setValue(self._min_per_class)
        self._spn_min.valueChanged.connect(lambda v: (setattr(self, "_min_per_class", int(v)), self._refresh_train_button()))
        rK.addWidget(self._spn_min); rK.addStretch(1); pv.addLayout(rK)

        root.addWidget(params_box)

        # Enregistrement
        rec_box = QGroupBox("Enregistrement", w)
        rec_box.setMinimumHeight(220)          # garantit de la place pour les lignes
        rv = QVBoxLayout(rec_box); rv.setContentsMargins(8,8,8,8); rv.setSpacing(6)

        self._classes_container = QWidget(rec_box)
        self._classes_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._classes_container.setMinimumHeight(120)
        self._classes_box = QVBoxLayout(self._classes_container); self._classes_box.setContentsMargins(0,0,0,0); self._classes_box.setSpacing(4)
        rv.addWidget(self._classes_container)

        rml = QHBoxLayout()
        self._btn_train = QPushButton("Train", parent=rec_box)
        self._btn_train.clicked.connect(self._on_train)
        btn_save  = QPushButton("Save Model", parent=rec_box); btn_save.clicked.connect(self._on_save)
        btn_load  = QPushButton("Load Model", parent=rec_box); btn_load.clicked.connect(self._on_load)
        btn_clear = QPushButton("Clear dataset", parent=rec_box); btn_clear.clicked.connect(self._on_clear)
        rml.addWidget(self._btn_train); rml.addWidget(btn_save); rml.addWidget(btn_load); rml.addWidget(btn_clear); rml.addStretch(1)
        rv.addLayout(rml)

        self._lbl_status = QLabel("No data | sklearn: " + ("OK" if SKLEARN_OK else "missing"), parent=rec_box)
        rv.addWidget(self._lbl_status)

        root.addWidget(rec_box)

        # Init
        self._rebuild_classes_ui(self._K)
        self._refresh_train_button()
        self._poke_layout()
        return w

    # ---------------- RUNTIME ----------------
    def execute(self, **kw):
        features = kw.get("features", None)
        bands = kw.get("band_labels", None)

        # Fallback: calcule features depuis segment
        if features is None:
            seg = kw.get("segment", None)
            sf = kw.get("sfreq", None); ch = kw.get("ch_names", None)
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
        self._update_recording(vec)

        if self._clf is not None:
            try:
                proba = self._clf.predict_proba([vec])[0]
                pred_idx = int(np.argmax(proba))
                pred_name = self._y_names[pred_idx] if pred_idx < len(self._y_names) else f"Class{pred_idx}"
                self.outputs["pred_label"].on_next(pred_name)
                self.outputs["pred_conf"].on_next(float(np.max(proba)))
                self.outputs["pred_idx"].on_next(pred_idx)
                self.outputs["proba"].on_next({self._y_names[i] if i<len(self._y_names) else f"Class{i}": float(p) for i,p in enumerate(proba)})
                self._set_status(f"Pred: {pred_name} ({np.max(proba):.2f}) | N={len(self._y)} | min/cls={self._min_per_class} | mode={self._feature_mode}")
            except Exception as e:
                self._set_status(f"Predict error: {e}")
        else:
            self._set_status(f"Collecting… N={len(self._y)} | min/cls={self._min_per_class} | mode={self._feature_mode}")
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

    def _toggle_rec(self, idx, checked):
        for i,ed in enumerate(self._name_edits):
            if i < len(self._y_names):
                self._y_names[i] = ed.text().strip() or self._y_names[i]
        if checked:
            for j,b in enumerate(self._rec_btns):
                if j!=idx and _alive(b) and b.isChecked():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            self._recording_class = int(idx)
        else:
            if self._recording_class == idx:
                self._recording_class = None
        self._refresh_counts_ui()

    def _counts(self):
        if not self._y: return [0]*self._K
        cnt=[0]*self._K
        for yi in self._y:
            if 0<=yi<self._K: cnt[yi]+=1
        return cnt

    def _refresh_counts_ui(self):
        cnt = self._counts()
        for i,btn in enumerate(self._rec_btns):
            if _alive(btn):
                on = (self._recording_class == i)
                try: btn.setText(f"Record {i} ({'ON' if on else 'idle'}) — N={cnt[i]}")
                except Exception: pass
        self._refresh_train_button()
        self._poke_layout()

    def _refresh_train_button(self):
        if not _alive(self._btn_train): return
        cnt = self._counts()
        ok = (len(cnt)==self._K) and all(c>=self._min_per_class for c in cnt) and (len(set(self._y))>=2)
        try: self._btn_train.setEnabled(ok)
        except Exception: pass

    def _update_recording(self, vec):
        if self._recording_class is None: return
        try:
            self._X.append(np.asarray(vec, float).copy())
            self._y.append(int(self._recording_class))
            self._emit_dataset()
            self._refresh_counts_ui()
        except Exception:
            pass

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
            self._set_status(f"Need ≥{self._min_per_class} samples in each class (counts={cnt})."); return
        try:
            X = np.stack(self._X, axis=0); y = np.array(self._y, dtype=int)
            self._clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, multi_class="auto"))
            self._clf.fit(X,y)
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
            self._rebuild_classes_ui(K)
            if _alive(self._combo_mode):
                self._combo_mode.setCurrentIndex(1 if self._feature_mode=="c3c4_ab" else 0)
            self._set_status(f"Model loaded: {os.path.basename(path)} | K={K} | mode={self._feature_mode}")
        except Exception as e:
            self._set_status(f"Load error: {e}")

    def _on_clear(self):
        self._X.clear(); self._y.clear(); self._clf=None; self._recording_class=None
        for b in list(self._rec_btns):
            if _alive(b):
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        self.outputs["pred_label"].on_next(None); self.outputs["pred_conf"].on_next(0.0)
        self.outputs["pred_idx"].on_next(None); self.outputs["proba"].on_next(None)
        self.outputs["dataset"].on_next(None)
        self._emit_dataset()
        self._refresh_counts_ui()
        self._set_status("Dataset cleared.")

    # ---------------- UI dynamiques ----------------
    def _rebuild_classes_ui(self, K):
        print(f"[EEGClassifier] rebuild classes K={K}")
        try: K = int(K)
        except Exception: K = 2
        self._K = max(2, min(6, K))

        # vider la zone dynamique
        if self._classes_box:
            while self._classes_box.count():
                item = self._classes_box.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None); w.deleteLater()
        self._name_edits.clear(); self._rec_btns.clear()

        # noms par défaut / trimming
        if len(self._y_names) < self._K:
            self._y_names += [f"Class{i+1}" for i in range(len(self._y_names), self._K)]
        else:
            self._y_names = self._y_names[:self._K]

        # créer les lignes visibles
        parent = self._classes_container if _alive(self._classes_container) else None
        for i in range(self._K):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"Class {i}:", parent=parent))
            ed = QLineEdit(self._y_names[i], parent=parent); self._name_edits.append(ed); row.addWidget(ed, 1)
            btn = QPushButton(f"Record {i} (idle) — N=0", parent=parent); btn.setCheckable(True)
            btn.clicked.connect(lambda checked, idx=i: self._toggle_rec(idx, checked))
            self._rec_btns.append(btn); row.addWidget(btn); row.addStretch(1)
            wrap = QWidget(parent=parent)
            lw = QVBoxLayout(wrap); lw.setContentsMargins(0,0,0,0); lw.setSpacing(0); lw.addLayout(row)
            if self._classes_box: self._classes_box.addWidget(wrap)
            print(f"[EEGClassifier] row added for class {i}")

        self._refresh_counts_ui()
        self._refresh_train_button()
        self._poke_layout()

    def _poke_layout(self):
        # force le recalcul des tailles → utile sous QGraphicsProxyWidget
        try:
            w = self._classes_container
            while w is not None:
                if w.layout(): w.layout().invalidate()
                w.adjustSize(); w.updateGeometry()
                w = w.parentWidget()
        except Exception:
            pass

    def _set_status(self, msg):
        try:
            if _alive(self._lbl_status): self._lbl_status.setText(msg)
        except Exception:
            pass
