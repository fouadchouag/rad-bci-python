# plugins/bci_features_node.py
# -*- coding: utf-8 -*-

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit, QDoubleSpinBox,
    QSpinBox, QCheckBox, QSizePolicy
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    from scipy.signal import welch as sp_welch
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


def _safe_mean(x, axis=None):
    x = np.asarray(x, float)
    if x.size == 0:
        return 0.0
    m = np.nanmean(x, axis=axis)
    if np.isscalar(m):
        return float(0.0 if not np.isfinite(m) else m)
    return np.nan_to_num(m, nan=0.0, posinf=0.0, neginf=0.0)


def _bands_from_text(text: str, preset: str):
    if (not text) or text.strip() == "":
        if preset == "MI":
            return [("alpha", 8.0, 12.0), ("beta", 13.0, 30.0)]
        elif preset == "SSVEP":
            return [("theta", 4.0, 8.0), ("alpha", 8.0, 12.0), ("beta", 13.0, 30.0)]
        elif preset == "P300":
            return [("delta", 1.0, 4.0), ("theta", 4.0, 8.0), ("alpha", 8.0, 12.0)]
        else:
            return [("delta", 1.0, 4.0), ("theta", 4.0, 8.0), ("alpha", 8.0, 12.0), ("beta", 13.0, 30.0)]
    bands = []
    for tok in text.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok and "-" in tok:
            name, fr = tok.split(":", 1)
            name = name.strip()
            try:
                a, b = fr.split("-", 1)
                f0 = float(a.strip()); f1 = float(b.strip())
                if f1 > f0:
                    bands.append((name, f0, f1))
            except Exception:
                pass
    if not bands:
        return _bands_from_text("", preset)
    return bands


def _welch_psd(x, fs, nperseg=256):
    x = np.asarray(x, float)
    if x.ndim == 1:
        x = x[None, :]
    C, T = x.shape
    if T <= 0:
        return np.zeros(0, dtype=float), np.zeros((C, 0), dtype=float)

    nperseg = int(min(max(16, nperseg), T))
    noverlap = nperseg // 2

    psd_list = []
    if SCIPY_OK:
        f = None
        for c in range(C):
            f_, pxx = sp_welch(x[c], fs=float(fs), nperseg=nperseg, noverlap=noverlap)
            if f is None:
                f = f_
            psd_list.append(pxx.astype(float, copy=False))
        P = np.vstack(psd_list)
        return f, P

    win = np.hanning(nperseg)
    hop = max(1, nperseg // 2)
    nfft = int(2 ** int(np.ceil(np.log2(nperseg))))
    f = np.fft.rfftfreq(nfft, d=1.0 / float(fs))
    denom = np.sum(win ** 2)

    for c in range(C):
        acc = np.zeros(len(f), dtype=float)
        nwin = 0
        start = 0
        while start + nperseg <= T:
            seg = x[c, start:start + nperseg] * win
            F = np.fft.rfft(seg, n=nfft)
            acc += (np.abs(F) ** 2) / denom
            nwin += 1
            start += hop
        if nwin == 0:
            w2 = np.hanning(T)
            F = np.fft.rfft(x[c] * w2, n=int(2 ** int(np.ceil(np.log2(T)))))
            f = np.fft.rfftfreq(F.size * 2 - 2, d=1.0 / float(fs))
            acc = (np.abs(F) ** 2) / np.sum(w2 ** 2)
            nwin = 1
        psd_list.append(acc / float(nwin))
    P = np.vstack(psd_list)
    return f, P


def _time_windows_from_text(text: str):
    wins = []
    for tok in (text or "").split(";"):
        tok = tok.strip()
        if not tok or ":" not in tok or "-" not in tok:
            continue
        name, rg = tok.split(":", 1)
        try:
            a, b = rg.split("-", 1)
            t0 = float(a.strip()) / 1000.0
            t1 = float(b.strip()) / 1000.0
            if t1 > t0:
                wins.append((name.strip(), t0, t1))
        except Exception:
            pass
    if not wins:
        wins = [("P3", 0.300, 0.450)]
    return wins


class BCI_Features(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'Processing step for EEG streams.',
  'usage': 'Wire upstream data and route downstream.'}

    name = "BCI_Features"
    language = "Python"
    category = "ML"

    def setup(self):
        # data
        self.inputs["X"]        = BehaviorSubject(None)
        self.inputs["sfreq"]    = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        # 🔌 config pins
        self.inputs["config_in"]     = BehaviorSubject(None)
        self.inputs["features_conf"] = BehaviorSubject(None)

        # sorties
        self.outputs["features"]     = BehaviorSubject(None)
        self.outputs["band_labels"]  = BehaviorSubject(None)
        self.outputs["feature_mode"] = BehaviorSubject(None)

        # 🔌 sortie config
        self.outputs["config_out"]   = BehaviorSubject(None)

        # state / UI
        self._mode = "PSD (bands)"      # "ERP mean windows" | "TimeStats"
        self._preset = "MI"             # "MI" | "P300" | "SSVEP" | "Full"
        self._bands_text = ""           # si vide → preset
        self._relative = True
        self._nperseg = 256
        self._erp_wins_text = "P3:300-450"  # ms
        self._erp_t0 = 0.0  # s, origine (0=stim)
        self._lbl = None

        # UI refs for sync
        self._cmb_mode = None
        self._cb_preset = None
        self._ed_bands = None
        self._ck_rel = None
        self._sp_nperseg = None
        self._ed_erp = None
        self._sp_t0 = None

        self._emit_config()

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        # --- Mode ---
        gbM = QWidget(); ml = QVBoxLayout(gbM); ml.setContentsMargins(8,8,8,8); ml.setSpacing(6)
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Feature mode:"))
        self._cmb_mode = QComboBox(); self._cmb_mode.addItems(["PSD (bands)","ERP mean windows","TimeStats"])
        self._cmb_mode.setCurrentText(self._mode)
        self._cmb_mode.currentIndexChanged.connect(lambda i: setattr(self, "_mode", self._cmb_mode.itemText(i)) | self._emit_config())
        r0.addWidget(self._cmb_mode); r0.addStretch(1); ml.addLayout(r0)

        # --- PSD params ---
        gbP = QWidget(); pl = QVBoxLayout(gbP); pl.setContentsMargins(8,8,8,8); pl.setSpacing(6)
        rp = QHBoxLayout()
        rp.addWidget(QLabel("Preset:"))
        self._cb_preset = QComboBox(); self._cb_preset.addItems(["MI","P300","SSVEP","Full"])
        self._cb_preset.setCurrentText(self._preset)
        self._cb_preset.currentIndexChanged.connect(lambda i: setattr(self, "_preset", self._cb_preset.itemText(i)) or self._emit_config())
        rp.addWidget(self._cb_preset); rp.addSpacing(12)
        rp.addWidget(QLabel("Bands (name:f0-f1; ...):"))
        self._ed_bands = QLineEdit(self._bands_text); self._ed_bands.setPlaceholderText("alpha:8-12; beta:13-30")
        self._ed_bands.textChanged.connect(lambda t: setattr(self, "_bands_text", t) or self._emit_config())
        rp.addWidget(self._ed_bands, 1)
        pl.addLayout(rp)
        rp2 = QHBoxLayout()
        self._ck_rel = QCheckBox("relative"); self._ck_rel.setChecked(self._relative)
        self._ck_rel.toggled.connect(lambda s: setattr(self, "_relative", bool(s)) or self._emit_config())
        rp2.addWidget(self._ck_rel); rp2.addSpacing(12)
        rp2.addWidget(QLabel("Welch nperseg:"))
        self._sp_nperseg = QSpinBox(); self._sp_nperseg.setRange(16, 4096); self._sp_nperseg.setValue(self._nperseg)
        self._sp_nperseg.valueChanged.connect(lambda v: setattr(self, "_nperseg", int(v)) or self._emit_config())
        rp2.addWidget(self._sp_nperseg); rp2.addStretch(1)
        pl.addLayout(rp2)

        # --- ERP params ---
        gbE = QWidget(); el = QVBoxLayout(gbE); el.setContentsMargins(8,8,8,8); el.setSpacing(6)
        re = QHBoxLayout()
        re.addWidget(QLabel("Windows (ms):"))
        self._ed_erp = QLineEdit(self._erp_wins_text); self._ed_erp.setPlaceholderText("N1:-100-0; P3:300-450")
        self._ed_erp.textChanged.connect(lambda t: setattr(self, "_erp_wins_text", t) or self._emit_config())
        re.addWidget(self._ed_erp, 1); el.addLayout(re)
        re2 = QHBoxLayout()
        re2.addWidget(QLabel("Epoch t0 offset [s] (0 = event at start):"))
        self._sp_t0 = QDoubleSpinBox(); self._sp_t0.setRange(-2.0, 2.0); self._sp_t0.setDecimals(3); self._sp_t0.setValue(self._erp_t0)
        self._sp_t0.valueChanged.connect(lambda v: setattr(self, "_erp_t0", float(v)) or self._emit_config())
        re2.addWidget(self._sp_t0); re2.addStretch(1); el.addLayout(re2)

        self._lbl = QLabel("SciPy: " + ("OK" if SCIPY_OK else "missing (FFT fallback)"))
        root.addWidget(CollapsibleSection("Mode", gbM, collapsed=False))
        root.addWidget(CollapsibleSection("PSD parameters", gbP, collapsed=False))
        root.addWidget(CollapsibleSection("ERP parameters", gbE, collapsed=True))
        root.addWidget(self._lbl)
        return w

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        """Bloc 'features' pour BCI_Config."""
        if self._mode.startswith("PSD"):
            return {
                "type": "psd",
                "preset": self._preset,
                "relative": bool(self._relative),
                "nperseg": int(self._nperseg),
                "bands_text": self._bands_text or ""
            }
        if self._mode.startswith("ERP"):
            return {
                "type": "erp_windows",
                "windows_text": self._erp_wins_text or "P3:300-450",
                "t0": float(self._erp_t0)
            }
        return {"type": "timestats"}

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        typ = str(cfg.get("type", "")).lower()
        if typ in ("psd", "psd_bands", "bands"):
            self._mode = "PSD (bands)"
            if "preset" in cfg: self._preset = str(cfg.get("preset") or self._preset)
            if "relative" in cfg: self._relative = bool(cfg.get("relative"))
            if "nperseg" in cfg: self._nperseg = int(cfg.get("nperseg"))
            if "bands_text" in cfg: self._bands_text = str(cfg.get("bands_text") or "")
        elif typ in ("erp", "erp_windows", "erpmean"):
            self._mode = "ERP mean windows"
            if "windows_text" in cfg: self._erp_wins_text = str(cfg.get("windows_text") or "P3:300-450")
            if "t0" in cfg: self._erp_t0 = float(cfg.get("t0"))
        elif typ in ("timestats", "time", "stats"):
            self._mode = "TimeStats"
        # sync UI
        if self._cmb_mode: self._cmb_mode.setCurrentText(self._mode)
        if self._cb_preset: self._cb_preset.setCurrentText(self._preset)
        if self._ed_bands is not None: self._ed_bands.setText(self._bands_text or "")
        if self._ck_rel is not None: self._ck_rel.setChecked(self._relative)
        if self._sp_nperseg is not None: self._sp_nperseg.setValue(self._nperseg)
        if self._ed_erp is not None: self._ed_erp.setText(self._erp_wins_text or "")
        if self._sp_t0 is not None: self._sp_t0.setValue(self._erp_t0)
        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ------------- runtime -------------
    def execute(self, **kw):
        # 🔸 appliquer config entrante
        merged = {}
        if isinstance(kw.get("config_in"), dict): merged.update(kw["config_in"])
        if isinstance(kw.get("features_conf"), dict): merged.update(kw["features_conf"])
        if merged: self.import_config(merged)

        X = kw.get("X", None)
        if X is None: X = kw.get("segment", None)
        if X is None: X = kw.get("data", None)
        fs = kw.get("sfreq", None)
        ch = kw.get("ch_names", None)

        if X is None or fs is None:
            self._push(None, None)
            if self._lbl: self._lbl.setText("Waiting signal+sfreq…")
            return {}

        X = np.asarray(X, float)
        if X.ndim == 3:
            X = X[-1]
        elif X.ndim != 2:
            self._push(None, None)
            if self._lbl: self._lbl.setText("X must be (C,T) or (N,C,T).")
            return {}

        C, T = X.shape
        if ch is None or len(ch) != C:
            ch = [f"ch{i+1}" for i in range(C)]

        mode = self._mode

        if mode.startswith("PSD"):
            bands = _bands_from_text(self._bands_text, self._preset)
            f, P = _welch_psd(X, fs=float(fs), nperseg=self._nperseg)
            if P.size == 0:
                self._push(None, None)
                if self._lbl: self._lbl.setText("PSD failed (empty).")
                return {}

            idx_norm = (f >= 1.0) & (f <= 40.0)
            denom = np.maximum(1e-20, np.sum(P[:, idx_norm], axis=1)) if self._relative else 1.0

            feats = {}; band_labels = []
            for nm, f0, f1 in bands:
                idx = (f >= f0) & (f <= f1)
                val = np.sum(P[:, idx], axis=1)
                if self._relative: val = val / denom
                band_labels.append(nm)
                for ci, cname in enumerate(ch):
                    feats.setdefault(cname, {})[nm] = float(val[ci])

            g = {bnm: float(_safe_mean([feats[c][bnm] for c in ch])) for bnm in band_labels}
            feats["GLOBAL"] = g

            self.outputs["band_labels"].on_next(band_labels)
            self.outputs["feature_mode"].on_next("PSD_bands_rel" if self._relative else "PSD_bands_abs")
            self.outputs["features"].on_next(feats)
            if self._lbl:
                self._lbl.setText(f"PSD ok | F={len(band_labels)} | C={C} | GLOBAL:{', '.join([f'{k}={g[k]:.3f}' for k in band_labels])}")
            return {}

        if mode.startswith("ERP"):
            wins = _time_windows_from_text(self._erp_wins_text)
            feats = {}
            for (nm, t0, t1) in wins:
                i0 = max(0, min(T - 1, int(round((t0 - self._erp_t0) * float(fs)))))
                i1 = max(0, min(T,     int(round((t1 - self._erp_t0) * float(fs)))))
                if i1 <= i0: m = np.zeros(C, float)
                else:
                    seg = X[:, i0:i1]; m = np.nanmean(seg, axis=1)
                for ci, cname in enumerate(ch):
                    feats.setdefault(cname, {})[nm] = float(np.nan_to_num(m[ci], nan=0.0))
            g = {nm: float(_safe_mean([feats[c][nm] for c in ch])) for (nm,_,_) in wins}
            feats["GLOBAL"] = g

            self.outputs["band_labels"].on_next([w[0] for w in wins])
            self.outputs["feature_mode"].on_next("ERP_mean_windows")
            self.outputs["features"].on_next(feats)
            if self._lbl:
                self._lbl.setText(f"ERP ok | W={len(wins)} | C={C} | GLOBAL:{g}")
            return {}

        # TimeStats
        feats = {}
        var_arr = np.var(X, axis=1)
        rms_arr = np.sqrt(np.mean(X*X, axis=1) + 1e-20)
        diff1 = np.diff(X, axis=1)
        diff2 = np.diff(diff1, axis=1)
        var1 = np.var(diff1, axis=1) + 1e-20
        var2 = np.var(diff2, axis=1) + 1e-20
        hj_mob = np.sqrt(var1 / (var_arr + 1e-20))
        hj_comp = np.sqrt((var2/var1) / (var1/(var_arr + 1e-20) + 1e-20))

        for ci, cname in enumerate(ch):
            feats[cname] = {
                "var": float(var_arr[ci]),
                "rms": float(rms_arr[ci]),
                "hj_mob": float(hj_mob[ci]),
                "hj_comp": float(hj_comp[ci]),
            }
        g = {
            "var": float(_safe_mean(var_arr)),
            "rms": float(_safe_mean(rms_arr)),
            "hj_mob": float(_safe_mean(hj_mob)),
            "hj_comp": float(_safe_mean(hj_comp)),
        }
        feats["GLOBAL"] = g

        self.outputs["band_labels"].on_next(["var", "rms", "hj_mob", "hj_comp"])
        self.outputs["feature_mode"].on_next("TimeStats")
        self.outputs["features"].on_next(feats)
        if self._lbl:
            self._lbl.setText(f"TimeStats ok | C={C} | GLOBAL:{g}")
        return {}

    # helpers
    def _push(self, feats, bands):
        try:
            self.outputs["features"].on_next(feats)
            self.outputs["band_labels"].on_next(bands)
            self.outputs["feature_mode"].on_next(self._mode)
        except Exception:
            pass