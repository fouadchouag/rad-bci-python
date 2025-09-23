# plugins/bci_preproc_node.py
# -*- coding: utf-8 -*-

import numpy as np, os
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QGroupBox, QSizePolicy,
    QStyle
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin

from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


# ---- optional SciPy for better filters/resample ----
try:
    from scipy.signal import butter, lfilter, filtfilt, iirnotch, sosfilt, sosfiltfilt, zpk2sos
    from scipy.signal import resample_poly
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False

# ---- sip guard (Qt) ----
try:
    import sip
    def _alive(w):
        try: return (w is not None) and (not sip.isdeleted(w))
        except Exception: return w is not None
except Exception:
    def _alive(w): return w is not None


def _to_ns_nc(x):
    """Ensure shape (n_samples, n_channels), return (arr, transposed_flag)."""
    arr = np.asarray(x)
    if arr.ndim == 1:
        arr = arr[:, None]
        return arr, False
    # Heuristic: more samples than channels -> (n_samples, n_channels)
    if arr.shape[0] >= arr.shape[1]:
        return arr, False
    else:
        return arr.T, True

def _from_ns_nc(arr, was_T):
    return arr.T if was_T else arr


def _design_fir_bandpass(fs, f_lo, f_hi, numtaps=257):
    """Simple FIR windowed-sinc bandpass (fallback when SciPy not available)."""
    # clamp freqs
    f_lo = max(0.0, f_lo)
    f_hi = min(0.499 * fs, f_hi)
    if f_hi <= f_lo:
        # just pass-through (DC remove will be done by z-score if checked)
        h = np.zeros(numtaps); h[numtaps//2] = 1.0
        return h
    # ideal low/high-pass using sinc, then bandpass by spectral inversion
    def _sinc(x):  # avoid division by zero
        return np.sinc(x/np.pi)
    n = np.arange(numtaps) - (numtaps-1)/2.0
    h_low  = 2*f_hi/fs * _sinc(2*np.pi*(f_hi/fs)*n)
    h_high = 2*f_lo/fs * _sinc(2*np.pi*(f_lo/fs)*n)
    h = h_low - h_high
    # Hamming window
    w = np.hamming(numtaps)
    h = h * w
    # normalize
    h = h / np.sum(h)
    return h


class BCIPreprocNode(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'Pré-traitement générique (causal) pour EEG:',
  'usage': 'Wire upstream data and route downstream.'}

    """
    Pré-traitement générique (causal) pour EEG:
      - Band-pass, Notch (50/60Hz + harmoniques), CAR
      - Régression EOG (multicanal)
      - Rééchantillonnage (optionnel)
      - Z-score par canal
    Inputs :
      - segment : ndarray (n_samples x n_channels) ou (n_channels x n_samples)
      - sfreq   : float
      - ch_names: list[str] (optionnel, utile pour auto EOG)
      - config_in     : dict (générique)
      - preproc_conf  : dict (spécifique préproc)
    Outputs :
      - segment, sfreq, ch_names (prétraités)
      - config_out     : dict (état courant – pour “Collect”)
    """
    name = "BCI_Preproc"
    language = "Python"
    category = "Preprocessing"

    # ---------- lifecycle ----------
    def setup(self):
        # inputs
        self.inputs["segment"]   = BehaviorSubject(None)
        self.inputs["sfreq"]     = BehaviorSubject(None)
        self.inputs["ch_names"]  = BehaviorSubject(None)

        # --- PINS DE CONFIG (compat BCI_Config) ---
        self.inputs["config_in"]     = BehaviorSubject(None)   # générique
        self.inputs["preproc_conf"]  = BehaviorSubject(None)   # dédié

        # outputs
        self.outputs["segment"]  = BehaviorSubject(None)
        self.outputs["sfreq"]    = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)

        # --- SORTIE CONFIG POUR COLLECT ---
        self.outputs["config_out"] = BehaviorSubject(None)

        # state (params)
        self._fs = None
        self._bp_lo = 8.0
        self._bp_hi = 30.0
        self._bp_order = 4
        self._causal = True

        self._notch_base = "None"   # "None", "50", "60"
        self._notch_harm = 0        # 0..3

        self._reref_mode = "NONE"   # "NONE", "CAR"

        self._eog_idx_text = ""     # e.g. "22,23,24"
        self._eog_idx = []          # list[int]
        self._auto_eog = True

        self._target_fs = 0.0       # 0 = keep
        self._zscore = False

        # ui refs
        self._lbl_status = None
        self._ed_eog = None

        # widgets (pour sync UI)
        self._sp_low = None
        self._sp_high = None
        self._sp_ord = None
        self._cb_notch = None
        self._sp_notch_harm = None
        self._ck_causal = None
        self._cb_ref = None
        self._ck_auto = None
        self._sp_fs = None
        self._ck_z = None

        # émettre la config initiale
        self._emit_config()

    def build_widget(self):
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        UiKit.apply_node_style(w)  # ← applique ton thème

        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        # --- FILTERS ---
        gb_f = QWidget(); fl = QVBoxLayout(gb_f); fl.setContentsMargins(8,8,8,8); fl.setSpacing(6)
        # row band-pass
        r_bp = QHBoxLayout()
        r_bp.addWidget(QLabel("Band-pass [Hz]:"))
        self._sp_low = QDoubleSpinBox(); self._sp_low.setRange(0.0, 200.0); self._sp_low.setDecimals(2); self._sp_low.setValue(self._bp_lo)
        self._sp_high = QDoubleSpinBox(); self._sp_high.setRange(0.0, 200.0); self._sp_high.setDecimals(2); self._sp_high.setValue(self._bp_hi)
        self._sp_ord = QSpinBox();       self._sp_ord.setRange(1, 10);      self._sp_ord.setValue(self._bp_order)
        self._sp_low.valueChanged.connect(lambda v: setattr(self, "_bp_lo", float(v)) or self._emit_config())
        self._sp_high.valueChanged.connect(lambda v: setattr(self, "_bp_hi", float(v)) or self._emit_config())
        self._sp_ord.valueChanged.connect(lambda v: setattr(self, "_bp_order", int(v)) or self._emit_config())
        r_bp.addWidget(self._sp_low); r_bp.addWidget(QLabel("–")); r_bp.addWidget(self._sp_high); r_bp.addSpacing(8)
        r_bp.addWidget(QLabel("order")); r_bp.addWidget(self._sp_ord); fl.addLayout(r_bp)

        # row notch + causal
        r_notch = QHBoxLayout()
        r_notch.addWidget(QLabel("Notch:"))
        self._cb_notch = QComboBox(); self._cb_notch.addItems(["None","50","60"])
        self._cb_notch.setCurrentText(self._notch_base)
        self._cb_notch.currentIndexChanged.connect(lambda i: setattr(self, "_notch_base", self._cb_notch.itemText(i)) or self._emit_config())
        r_notch.addWidget(self._cb_notch); r_notch.addSpacing(8)
        r_notch.addWidget(QLabel("harmonics:"))
        self._sp_notch_harm = QSpinBox(); self._sp_notch_harm.setRange(0,3); self._sp_notch_harm.setValue(self._notch_harm)
        self._sp_notch_harm.valueChanged.connect(lambda v: setattr(self, "_notch_harm", int(v)) or self._emit_config())
        r_notch.addWidget(self._sp_notch_harm); r_notch.addSpacing(16)
        self._ck_causal = QCheckBox("Causal filtering"); self._ck_causal.setChecked(self._causal)
        self._ck_causal.toggled.connect(lambda s: setattr(self, "_causal", bool(s)) or self._emit_config())
        r_notch.addWidget(self._ck_causal); r_notch.addStretch(1)
        fl.addLayout(r_notch)

        # --- CHANNELS ---
        gb_c = QWidget(); cl = QVBoxLayout(gb_c); cl.setContentsMargins(8,8,8,8); cl.setSpacing(6)
        r_ref = QHBoxLayout()
        r_ref.addWidget(QLabel("Re-ref:"))
        self._cb_ref = QComboBox(); self._cb_ref.addItems(["NONE","CAR"])
        self._cb_ref.setCurrentText(self._reref_mode)
        self._cb_ref.currentIndexChanged.connect(lambda i: setattr(self, "_reref_mode", self._cb_ref.itemText(i)) or self._emit_config())
        r_ref.addWidget(self._cb_ref); r_ref.addStretch(1); cl.addLayout(r_ref)

        r_eog = QHBoxLayout()
        r_eog.addWidget(QLabel("EOG idx (comma):"))
        self._ed_eog = QLineEdit(self._eog_idx_text); r_eog.addWidget(self._ed_eog, 1)
        self._ck_auto = QCheckBox("auto-detect by name"); self._ck_auto.setChecked(self._auto_eog)
        self._ck_auto.toggled.connect(lambda s: setattr(self, "_auto_eog", bool(s)) or self._emit_config())
        r_eog.addWidget(self._ck_auto)
        btn_apply_eog = UiKit.make_btn("Apply EOG idx", role="primary", icon_sp=QStyle.SP_DialogApplyButton)
        btn_apply_eog.clicked.connect(self._apply_eog_idx)
        r_eog.addWidget(btn_apply_eog)
        cl.addLayout(r_eog)

        # --- RESAMPLE & NORM ---
        gb_r = QWidget(); rl = QVBoxLayout(gb_r); rl.setContentsMargins(8,8,8,8); rl.setSpacing(6)
        r_rs = QHBoxLayout()
        r_rs.addWidget(QLabel("Target fs [Hz] (0 = keep):"))
        self._sp_fs = QDoubleSpinBox(); self._sp_fs.setRange(0.0, 2000.0); self._sp_fs.setDecimals(2); self._sp_fs.setValue(self._target_fs)
        self._sp_fs.valueChanged.connect(lambda v: setattr(self, "_target_fs", float(v)) or self._emit_config())
        r_rs.addWidget(self._sp_fs)
        self._ck_z = QCheckBox("Z-score per channel"); self._ck_z.setChecked(self._zscore)
        self._ck_z.toggled.connect(lambda s: setattr(self, "_zscore", bool(s)) or self._emit_config())
        r_rs.addWidget(self._ck_z); r_rs.addStretch(1)
        rl.addLayout(r_rs)

        self._lbl_status = QLabel("SciPy: " + ("OK" if SCIPY_OK else "missing (fallbacks)"))

        # --- Collapsibles ---
        root.addWidget(CollapsibleSection("Filters", gb_f, collapsed=False))
        root.addWidget(CollapsibleSection("Channels & referencing", gb_c, collapsed=True))
        root.addWidget(CollapsibleSection("Resample & Normalization", gb_r, collapsed=True))
        root.addWidget(self._lbl_status)

        return w


    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        """Configuration lisible/écrivable par BCI_Config (et fichiers)."""
        try:
            notch = None if str(self._notch_base).lower().startswith("none") else float(self._notch_base)
        except Exception:
            notch = None
        return {
            "bandpass": [float(self._bp_lo), float(self._bp_hi)],
            "order": int(self._bp_order),
            "causal": bool(self._causal),
            "notch": notch,                          # 50.0 / 60.0 / None
            "notch_harmonics": int(self._notch_harm),
            "reref": str(self._reref_mode).upper(), # "CAR" | "NONE"
            "eog_idx": list(self._eog_idx) if self._eog_idx else [],
            "auto_eog": bool(self._auto_eog),
            "target_fs": float(self._target_fs),
            "zscore": bool(self._zscore),
        }

    def import_config(self, cfg: dict):
        """Applique la configuration (tolérance aux clés)."""
        if not isinstance(cfg, dict):
            return

        # bandpass
        bp = cfg.get("bandpass") or cfg.get("bp") or cfg.get("band_pass")
        if isinstance(bp, (list, tuple)) and len(bp) == 2:
            self._bp_lo, self._bp_hi = float(bp[0]), float(bp[1])

        # order / causal
        if "order" in cfg: self._bp_order = int(cfg.get("order", self._bp_order))
        if "causal" in cfg: self._causal = bool(cfg.get("causal", self._causal))

        # notch
        notch = cfg.get("notch") or cfg.get("notch_hz")
        if notch is None or notch == 0 or str(notch).lower().startswith("none"):
            self._notch_base = "None"
        else:
            val = float(notch)
            self._notch_base = "50" if abs(val-50.0) < 5 else "60"
        if "notch_harmonics" in cfg or "harmonics" in cfg:
            self._notch_harm = int(cfg.get("notch_harmonics", cfg.get("harmonics", self._notch_harm)))

        # reref
        rr = cfg.get("reref") or cfg.get("reference") or cfg.get("ref")
        if rr is not None:
            rr = str(rr).upper()
            if rr in ("CAR","NONE"):
                self._reref_mode = rr
            elif rr in ("AVG","AVERAGE"):
                # pas implémenté dans ce node → map sur CAR par défaut
                self._reref_mode = "CAR"
            else:
                self._reref_mode = "NONE"

        # eog idx / auto
        eog_idx = cfg.get("eog_idx") or cfg.get("eog_indices") or cfg.get("eog")
        if isinstance(eog_idx, (list, tuple)):
            try:
                self._eog_idx = [int(i) for i in eog_idx]
                self._eog_idx_text = ",".join(str(i) for i in self._eog_idx)
            except Exception:
                pass
        if "auto_eog" in cfg:
            self._auto_eog = bool(cfg.get("auto_eog"))

        # resample + zscore
        if "target_fs" in cfg: self._target_fs = float(cfg.get("target_fs"))
        if "zscore" in cfg: self._zscore = bool(cfg.get("zscore"))

        # sync UI + notify
        self._refresh_ui()
        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def _refresh_ui(self):
        """Réaligne les widgets si présents."""
        if _alive(self._sp_low):  self._sp_low.setValue(self._bp_lo)
        if _alive(self._sp_high): self._sp_high.setValue(self._bp_hi)
        if _alive(self._sp_ord):  self._sp_ord.setValue(self._bp_order)
        if _alive(self._cb_notch):
            self._cb_notch.setCurrentText(self._notch_base)
        if _alive(self._sp_notch_harm):
            self._sp_notch_harm.setValue(self._notch_harm)
        if _alive(self._ck_causal):
            self._ck_causal.setChecked(self._causal)
        if _alive(self._cb_ref):
            self._cb_ref.setCurrentText(self._reref_mode)
        if _alive(self._ed_eog):
            self._ed_eog.setText(self._eog_idx_text or "")
        if _alive(self._ck_auto):
            self._ck_auto.setChecked(self._auto_eog)
        if _alive(self._sp_fs):
            self._sp_fs.setValue(self._target_fs)
        if _alive(self._ck_z):
            self._ck_z.setChecked(self._zscore)

    # ---------- runtime ----------
    def execute(self, **kw):
        # --- APPLIQUER CONFIG REÇUE (avec ou sans câbles) ---
        merged_cfg = {}
        if isinstance(kw.get("config_in"), dict):
            merged_cfg.update(kw["config_in"])
        if isinstance(kw.get("preproc_conf"), dict):
            merged_cfg.update(kw["preproc_conf"])
        if merged_cfg:
            self.import_config(merged_cfg)

        seg = kw.get("segment", None)
        fs  = kw.get("sfreq", None)
        chn = kw.get("ch_names", None)

        if seg is None or fs is None:
            self._set_status("Waiting for segment + sfreq")
            return {}

        self._fs = float(fs)
        arr, was_T = _to_ns_nc(seg)  # shape (n_samp, n_ch)
        n_samp, n_ch = arr.shape

        # --- split EEG/EOG if indices are known/detected ---
        eog_idx = self._detect_eog_idx(chn)  # list of indices
        eeg_idx = [i for i in range(n_ch) if i not in eog_idx]
        X = arr[:, eeg_idx] if eeg_idx else arr
        E = arr[:, eog_idx] if eog_idx else None

        # --- filtering band-pass ---
        X = self._apply_bandpass(X, self._fs)

        # --- notch(s) ---
        X = self._apply_notch_cascade(X, self._fs)

        # --- reref ---
        if self._reref_mode == "CAR" and X.shape[1] > 1:
            X = X - np.mean(X, axis=1, keepdims=True)

        # --- EOG regression ---
        if E is not None and E.shape[1] > 0 and X.shape[0] > 10:
            try:
                # W = (E^T E)^-1 E^T X
                W = np.linalg.pinv(E).dot(X)
                X = X - E.dot(W)
            except Exception as e:
                self._set_status(f"EOG regression error: {e}")

        # --- z-score ---
        if self._zscore:
            mu = np.mean(X, axis=0, keepdims=True)
            sd = np.std(X, axis=0, ddof=1, keepdims=True)
            sd[sd < 1e-12] = 1.0
            X = (X - mu) / sd

        # place back EEG + (optionally untouched) non-EEG
        out = np.zeros_like(arr)
        if eeg_idx:
            out[:, eeg_idx] = X
        else:
            out = X
        if eog_idx:
            out[:, eog_idx] = arr[:, eog_idx]  # keep raw EOG in output by default

        # --- resample if requested ---
        out_fs = self._fs
        if self._target_fs and self._target_fs > 0.0 and abs(self._target_fs - self._fs) > 1e-6:
            if SCIPY_OK:
                g = np.gcd(int(round(self._target_fs)), int(round(self._fs)))
                up = int(round(self._target_fs / g))
                down = int(round(self._fs / g))
                try:
                    out = resample_poly(out, up, down, axis=0)
                    out_fs = float(self._target_fs)
                except Exception as e:
                    self._set_status(f"Resample error: {e}")
            else:
                self._set_status("Resample skipped (SciPy missing)")

        # restore original orientation
        out = _from_ns_nc(out, was_T)
        # outputs
        self.outputs["segment"].on_next(out)
        self.outputs["sfreq"].on_next(out_fs)
        self.outputs["ch_names"].on_next(chn)
        self._set_status(f"OK | n_ch={out.shape[0] if was_T else out.shape[1]} fs={out_fs:.2f}Hz")
        return {}

    # ---------- filtering helpers ----------
    def _apply_bandpass(self, X, fs):
        f_lo, f_hi = float(self._bp_lo), float(self._bp_hi)
        if (f_lo <= 0.0 and f_hi <= 0.0) or (f_hi <= f_lo):
            return X  # no-op
        if SCIPY_OK:
            ny = 0.5 * fs
            lo = max(0.0001, f_lo/ny)
            hi = min(0.9999, f_hi/ny)
            btype = 'band'
            try:
                # use SOS for stability
                from scipy.signal import butter, sosfilt, sosfiltfilt
                sos = butter(self._bp_order, [lo, hi], btype=btype, output='sos')
                if self._causal:
                    return sosfilt(sos, X, axis=0)
                else:
                    return sosfiltfilt(sos, X, axis=0)
            except Exception as e:
                self._set_status(f"BPF error: {e} (fallback FIR)")
        # fallback FIR (linear-phase, not strictly causal)
        h = _design_fir_bandpass(fs, f_lo, f_hi, numtaps=257)
        return np.apply_along_axis(lambda x: np.convolve(x, h, mode='same'), axis=0, arr=X)

    def _apply_notch_cascade(self, X, fs):
        base = self._notch_base
        n_h = int(self._notch_harm)
        if base == "None" or n_h <= 0:
            return X
        if not SCIPY_OK:
            self._set_status("Notch skipped (SciPy missing)")
            return X
        try:
            from scipy.signal import iirnotch, sosfilt, sosfiltfilt, zpk2sos, tf2zpk
            y = X
            f0 = 50.0 if base == "50" else 60.0
            Q = 35.0  # typical
            for k in range(1, n_h+1):
                f = f0 * k
                if f >= 0.49*fs:  # ignore beyond Nyquist
                    continue
                w0 = f / (fs/2.0)
                b, a = iirnotch(w0, Q)
                z, p, g = tf2zpk(b, a)
                sos = zpk2sos(z, p, g)
                if self._causal:
                    y = sosfilt(sos, y, axis=0)
                else:
                    y = sosfiltfilt(sos, y, axis=0)
            return y
        except Exception as e:
            self._set_status(f"Notch error: {e}")
            return X

    # ---------- EOG idx helpers ----------
    def _apply_eog_idx(self):
        txt = self._ed_eog.text().strip() if _alive(self._ed_eog) else ""
        self._eog_idx_text = txt
        self._eog_idx = []
        if txt:
            try:
                self._eog_idx = [int(t.strip()) for t in txt.split(",") if t.strip()!=""]
            except Exception:
                self._set_status("EOG idx parse error (use: 22,23,24)")
        self._emit_config()  # refléter la modif de config

    def _detect_eog_idx(self, ch_names):
        # priority: manual indices
        if self._eog_idx:
            return [i for i in self._eog_idx if isinstance(i, int)]
        if not self._auto_eog or not ch_names:
            return []
        idx=[]
        for i, name in enumerate(ch_names):
            s=str(name).upper()
            if ("EOG" in s) or ("EYE" in s) or ("EOGL" in s) or ("EOGR" in s) or ("VEOG" in s) or ("HEOG" in s):
                idx.append(i)
        return idx

    # ---------- misc ----------
    def _set_status(self, msg):
        if _alive(self._lbl_status): self._lbl_status.setText(f"{msg} | SciPy={'OK' if SCIPY_OK else 'no'}")