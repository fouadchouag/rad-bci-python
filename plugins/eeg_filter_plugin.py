# plugins/eeg_filter_plugin.py
# -*- coding: utf-8 -*-
"""
EEGSliceFilter : filtrage streaming (HP/LP/Notch) par fenêtres avec état persistant
• Params alignés sur RawFilter : method (fir/iir), fir_taps, HP/LP, Notch (liste), Q, bypass
• SciPy : iirnotch + sosfilt pour Notch et IIR ; firwin + lfilter pour FIR
• Métriques :
    - PARAM_CHANGE pour chaque modif UI
    - FILTER_START / FILTER_DONE / FILTER_FAIL avec:
        dur_s, throughput_sps, rt_factor (= durée réelle tranche / durée CPU),
        n_ch, n (échantillons), fs, method, fir_taps / iir_order, etc.
• Compatibilité ConfigNode : export_config / import_config / config_hints + config_out
• Meta (sfreq, ch_names, info) émise uniquement si changement
"""

import time
import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton, QLineEdit, QComboBox,
    QLayout, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin
from core.metrics_logger import metrics  # HOOKS METRICS

try:
    from scipy.signal import butter, sosfilt, iirnotch, tf2sos, firwin, lfilter
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


class _CollapsibleSection(QWidget):
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._wrap = QWidget(); self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0); self._wrap_l.setSpacing(0)
        self._content = content or QWidget(); self._content.setStyleSheet("background: transparent;")
        self._wrap_l.addWidget(self._content)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(4)
        root.addWidget(self._btn); root.addWidget(self._wrap)
        self._btn.toggled.connect(self._on_toggled); self._btn.setChecked(not collapsed if isinstance(collapsed,bool) else True)
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
            self.setMaximumHeight(16777215); self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            h = self._btn.sizeHint().height() + 6
            self.setMaximumHeight(h); self.setMinimumHeight(h); self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._poke()


class EEGFilterPlugin(BasePlugin):
    help = help = { 'gotchas': [ 'SciPy required (pip install scipy).',
               'Filter state persists across chunks; use "Reset state" or '
               'change params to reset.',
               'FIR notch is applied via IIR cascade before FIR HP/LP.',
               'Mind edge effects on short windows.',
               'HP cutoff must be < LP cutoff and both < Nyquist (sfreq/2).',
               'Bypass mode passes data through unfiltered.',
               'Filters are re-designed when sfreq or ch_names change.'],
  'inputs': { 'segment': '2D float array [ch x samples] — EEG data chunk',
              'info': 'dict — metadata (sfreq, ch_names); optional',
              'sfreq': 'float — sampling rate in Hz (alternative to info)',
              'ch_names': 'list[str] — channel names (alternative to info)'},
  'outputs': {'segment': '2D float array — filtered EEG chunk (same shape)',
              'info': 'dict — metadata passthrough',
              'sfreq': 'float — sampling rate passthrough',
              'ch_names': 'list[str] — channel names passthrough',
              'config_out': 'dict — current filter config snapshot'},
  'parameters': [ { 'default': True,
                    'desc': 'Enable high-pass filter',
                    'name': 'enable_hp',
                    'type': 'bool'},
                  { 'default': 1.0,
                    'desc': 'High-pass cutoff frequency',
                    'name': 'hp',
                    'type': 'float',
                    'unit': 'Hz'},
                  { 'default': True,
                    'desc': 'Enable low-pass filter',
                    'name': 'enable_lp',
                    'type': 'bool'},
                  { 'default': 40.0,
                    'desc': 'Low-pass cutoff frequency',
                    'name': 'lp',
                    'type': 'float',
                    'unit': 'Hz'},
                  { 'default': False,
                    'desc': 'Enable notch filter(s)',
                    'name': 'enable_notch',
                    'type': 'bool'},
                  { 'default': '50, 100',
                    'desc': 'Notch frequencies (comma-separated)',
                    'name': 'notch_freqs',
                    'type': 'str',
                    'unit': 'Hz'},
                  { 'default': 30.0,
                    'desc': 'Notch filter quality factor',
                    'name': 'notch_q',
                    'type': 'float'},
                  { 'default': 'fir',
                    'desc': 'Filter design method',
                    'name': 'method',
                    'type': 'str',
                    'enum': ['fir', 'iir']},
                  { 'default': 401,
                    'desc': 'Number of FIR taps (must be odd)',
                    'name': 'fir_taps',
                    'type': 'int'},
                  { 'default': 4,
                    'desc': 'IIR (Butterworth) filter order',
                    'name': 'iir_order',
                    'type': 'int'},
                  { 'default': False,
                    'desc': 'Bypass all filtering',
                    'name': 'bypass',
                    'type': 'bool'}],
  'summary': 'Streaming windowed filter (HP/LP/Notch) with persistent state (FIR or IIR).',
  'usage': 'Connect after a slicer/inlet to filter streaming EEG chunks. '
           'Tune HP/LP band edges, notch frequencies, and FIR/IIR method.'}

    name = "EEGSliceFilter"
    category = "Processing Nodes"
    language = "Python"

    def setup(self):
        self.inputs = {
            "segment": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }
        self.outputs = {
            "segment": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
            "config_out": BehaviorSubject(None),
        }

        # ---- paramètres (alignés RawFilter) ----
        self._enable_hp = True;  self._hp = 1.0
        self._enable_lp = True;  self._lp = 40.0
        self._enable_notch = False; self._notch_str = "50, 100"; self._notch_q = 30.0
        self._method = "fir"               # "fir" | "iir"
        self._fir_taps = 401               # longueur FIR si method=fir
        self._iir_order = 4                # ordre Butter si method=iir
        self._bypass = False

        # ---- meta cache ----
        self._sfreq = 0.0; self._ch_names = []; self._n_ch = 0; self._last_info = None
        self._sent_sfreq = None; self._sent_ch_names = None; self._sent_info = None

        # ---- filtres (état) ----
        self._sos = None                   # SOS pour Notch + IIR
        self._zi_sos_per_ch = []           # liste par canal: (n_sections, 2)
        self._fir_b = None                 # Coeffs FIR
        self._zi_fir_per_ch = []           # liste par canal: (len(b)-1,)

        # ---- UI refs ----
        self.chk_hp = self.spn_hp = None
        self.chk_lp = self.spn_lp = None
        self.chk_notch = self.ed_notch = self.spn_q = None
        self.cmb_method = self.spn_fir_taps = self.spn_iir_order = None
        self.chk_bypass = None

    # ---------- Config I/O ----------
    def export_config(self) -> dict:
        try:
            notch_list = [float(x) for x in self._notch_str.replace(";", ",").split(",") if x.strip()]
        except Exception:
            notch_list = []
        return {
            "enable_hp": bool(self._enable_hp),
            "hp": float(self._hp),
            "enable_lp": bool(self._enable_lp),
            "lp": float(self._lp),
            "enable_notch": bool(self._enable_notch),
            "notch_freqs": notch_list,
            "notch_q": float(self._notch_q),
            "method": str(self._method),       # "fir" | "iir"
            "fir_taps": int(self._fir_taps),
            "iir_order": int(self._iir_order),
            "bypass": bool(self._bypass),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        def _get(k, typ=None, d=None):
            v = cfg.get(k, d)
            if typ is None or v is None: return v
            try: return typ(v)
            except Exception: return d

        self._enable_hp = bool(_get("enable_hp", bool, self._enable_hp))
        self._hp = float(_get("hp", float, self._hp))
        self._enable_lp = bool(_get("enable_lp", bool, self._enable_lp))
        self._lp = float(_get("lp", float, self._lp))
        self._enable_notch = bool(_get("enable_notch", bool, self._enable_notch))
        self._notch_q = float(_get("notch_q", float, self._notch_q))
        nf = _get("notch_freqs", list, None)
        if nf is not None:
            try:
                vals = [float(x) for x in nf]
                self._notch_str = ", ".join(str(x) for x in vals)
            except Exception:
                pass
        method = _get("method", str, self._method)
        if method in ("fir","iir"): self._method = method
        self._fir_taps = int(_get("fir_taps", int, self._fir_taps))
        self._iir_order = int(_get("iir_order", int, self._iir_order))
        self._bypass = bool(_get("bypass", bool, self._bypass))

        # sync UI
        try:
            if self.chk_hp: self.chk_hp.blockSignals(True); self.chk_hp.setChecked(self._enable_hp); self.chk_hp.blockSignals(False)
            if self.spn_hp: self.spn_hp.blockSignals(True); self.spn_hp.setValue(self._hp); self.spn_hp.blockSignals(False)
            if self.chk_lp: self.chk_lp.blockSignals(True); self.chk_lp.setChecked(self._enable_lp); self.chk_lp.blockSignals(False)
            if self.spn_lp: self.spn_lp.blockSignals(True); self.spn_lp.setValue(self._lp); self.spn_lp.blockSignals(False)
            if self.chk_notch: self.chk_notch.blockSignals(True); self.chk_notch.setChecked(self._enable_notch); self.chk_notch.blockSignals(False)
            if self.ed_notch: self.ed_notch.blockSignals(True); self.ed_notch.setText(self._notch_str); self.ed_notch.blockSignals(False)
            if self.spn_q: self.spn_q.blockSignals(True); self.spn_q.setValue(self._notch_q); self.spn_q.blockSignals(False)
            if self.cmb_method: self.cmb_method.blockSignals(True); self.cmb_method.setCurrentText(self._method); self.cmb_method.blockSignals(False)
            if self.spn_fir_taps:
                self.spn_fir_taps.blockSignals(True); self.spn_fir_taps.setValue(int(self._fir_taps)); self.spn_fir_taps.blockSignals(False)
                self.spn_fir_taps.setEnabled(self._method == "fir")
            if self.spn_iir_order:
                self.spn_iir_order.blockSignals(True); self.spn_iir_order.setValue(int(self._iir_order)); self.spn_iir_order.blockSignals(False)
                self.spn_iir_order.setEnabled(self._method == "iir")
            if self.chk_bypass: self.chk_bypass.blockSignals(True); self.chk_bypass.setChecked(self._bypass); self.chk_bypass.blockSignals(False)
        except Exception:
            pass

        # redesign
        self._design_all(reset_state=True)
        self._emit_config()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "bypass": {"type": "bool", "label": "Bypass"},
                "method": {"type": "enum", "enum": ["fir","iir"], "label": "Method"},
                "fir_taps": {"type": "int", "min": 21, "max": 20001, "step": 2, "label": "FIR taps"},
                "iir_order": {"type": "int", "min": 1, "max": 10, "step": 1, "label": "IIR order (Butter)"},
                "enable_hp": {"type": "bool", "label": "HP on"},
                "hp": {"type": "float", "min": 0.01, "max": 300.0, "step": 0.1, "label": "HP (Hz)"},
                "enable_lp": {"type": "bool", "label": "LP on"},
                "lp": {"type": "float", "min": 0.5, "max": 1000.0, "step": 0.5, "label": "LP (Hz)"},
                "enable_notch": {"type": "bool", "label": "Notch on"},
                "notch_freqs": {"type": "list", "help": "Fréquences notch (CSV)", "label": "Notch freqs"},
                "notch_q": {"type": "float", "min": 1.0, "max": 200.0, "step": 1.0, "label": "Notch Q"},
            },
            "_order": ["bypass","method","fir_taps","iir_order",
                       "enable_hp","hp","enable_lp","lp",
                       "enable_notch","notch_freqs","notch_q"],
        }

    def build_widget(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        if not SCIPY_OK:
            v.addWidget(QLabel("❌ SciPy manquant. Installe :  pip install scipy"))
            return w

        panel = QWidget(); pv = QVBoxLayout(panel); pv.setContentsMargins(8, 8, 8, 8)

        # Row 0: Bypass + Method + taps/order
        r0 = QHBoxLayout()
        self.chk_bypass = QCheckBox("Bypass"); self.chk_bypass.setChecked(self._bypass); self.chk_bypass.stateChanged.connect(self._on_params_changed); r0.addWidget(self.chk_bypass)
        r0.addSpacing(10)
        r0.addWidget(QLabel("Method:"))
        self.cmb_method = QComboBox(); self.cmb_method.addItems(["fir","iir"]); self.cmb_method.setCurrentText(self._method)
        self.cmb_method.currentTextChanged.connect(self._on_params_changed); r0.addWidget(self.cmb_method)
        r0.addSpacing(10)
        r0.addWidget(QLabel("FIR taps:"))
        self.spn_fir_taps = QSpinBox(); self.spn_fir_taps.setRange(21, 20001); self.spn_fir_taps.setSingleStep(2); self.spn_fir_taps.setValue(int(self._fir_taps))
        self.spn_fir_taps.setEnabled(self._method == "fir"); self.spn_fir_taps.valueChanged.connect(self._on_params_changed); r0.addWidget(self.spn_fir_taps)
        r0.addSpacing(10)
        r0.addWidget(QLabel("IIR order:"))
        self.spn_iir_order = QSpinBox(); self.spn_iir_order.setRange(1, 10); self.spn_iir_order.setSingleStep(1); self.spn_iir_order.setValue(int(self._iir_order))
        self.spn_iir_order.setEnabled(self._method == "iir"); self.spn_iir_order.valueChanged.connect(self._on_params_changed); r0.addWidget(self.spn_iir_order)
        r0.addStretch(1)
        pv.addLayout(r0)

        # Row 1: HP/LP
        r1 = QHBoxLayout()
        self.chk_hp = QCheckBox("HP"); self.chk_hp.setChecked(self._enable_hp); self.chk_hp.stateChanged.connect(self._on_params_changed); r1.addWidget(self.chk_hp)
        r1.addWidget(QLabel("HP (Hz):")); self.spn_hp = QDoubleSpinBox(); self.spn_hp.setRange(0.01, 300.0); self.spn_hp.setSingleStep(0.1); self.spn_hp.setValue(self._hp); self.spn_hp.valueChanged.connect(self._on_params_changed); r1.addWidget(self.spn_hp)
        self.chk_lp = QCheckBox("LP"); self.chk_lp.setChecked(self._enable_lp); self.chk_lp.stateChanged.connect(self._on_params_changed); r1.addWidget(self.chk_lp)
        r1.addWidget(QLabel("LP (Hz):")); self.spn_lp = QDoubleSpinBox(); self.spn_lp.setRange(0.5, 1000.0); self.spn_lp.setSingleStep(0.5); self.spn_lp.setValue(self._lp); self.spn_lp.valueChanged.connect(self._on_params_changed); r1.addWidget(self.spn_lp)
        pv.addLayout(r1)

        # Row 2: Notch
        r2 = QHBoxLayout()
        self.chk_notch = QCheckBox("Notch"); self.chk_notch.setChecked(self._enable_notch); self.chk_notch.stateChanged.connect(self._on_params_changed); r2.addWidget(self.chk_notch)
        r2.addWidget(QLabel("f0 list (Hz):")); self.ed_notch = QLineEdit(self._notch_str); self.ed_notch.setPlaceholderText("ex: 50, 100"); self.ed_notch.textChanged.connect(self._on_params_changed); r2.addWidget(self.ed_notch)
        r2.addWidget(QLabel("Q:")); self.spn_q = QDoubleSpinBox(); self.spn_q.setRange(1.0, 200.0); self.spn_q.setSingleStep(1.0); self.spn_q.setValue(self._notch_q); self.spn_q.valueChanged.connect(self._on_params_changed); r2.addWidget(self.spn_q)
        btn_reset = QPushButton("Reset state"); btn_reset.clicked.connect(self._reset_state); r2.addWidget(btn_reset)
        r2.addStretch(1)
        pv.addLayout(r2)

        pv.addWidget(QLabel("Astuce: Notch multiples via CSV. En mode FIR, les Notch sont appliqués en IIR (cascade notch) puis le FIR HP/LP."))

        v.addWidget(_CollapsibleSection("Paramètres", panel, collapsed=True))
        self._emit_config()
        return w

    # ---------- helpers ----------
    def _log_param(self, name, val):
        try:
            metrics().param_change(name=str(name), new=val)
        except Exception:
            pass

    def _on_params_changed(self, *args):
        prev = (
            self._bypass, self._method, self._fir_taps, self._iir_order,
            self._enable_hp, self._hp, self._enable_lp, self._lp,
            self._enable_notch, self._notch_str, self._notch_q
        )
        # lire UI
        self._bypass = self.chk_bypass.isChecked() if self.chk_bypass else self._bypass
        self._method = self.cmb_method.currentText() if self.cmb_method else self._method
        self._fir_taps = int(self.spn_fir_taps.value()) if self.spn_fir_taps else self._fir_taps
        self._iir_order = int(self.spn_iir_order.value()) if self.spn_iir_order else self._iir_order
        self._enable_hp = self.chk_hp.isChecked() if self.chk_hp else self._enable_hp
        self._hp = float(self.spn_hp.value()) if self.spn_hp else self._hp
        self._enable_lp = self.chk_lp.isChecked() if self.chk_lp else self._enable_lp
        self._lp = float(self.spn_lp.value()) if self.spn_lp else self._lp
        self._enable_notch = self.chk_notch.isChecked() if self.chk_notch else self._enable_notch
        self._notch_str = self.ed_notch.text().strip() if self.ed_notch else self._notch_str
        self._notch_q = float(self.spn_q.value()) if self.spn_q else self._notch_q

        # enable/disable champs
        if self.spn_fir_taps: self.spn_fir_taps.setEnabled(self._method == "fir")
        if self.spn_iir_order: self.spn_iir_order.setEnabled(self._method == "iir")

        # logs fins
        now = (
            self._bypass, self._method, self._fir_taps, self._iir_order,
            self._enable_hp, self._hp, self._enable_lp, self._lp,
            self._enable_notch, self._notch_str, self._notch_q
        )
        names = ["bypass","method","fir_taps","iir_order","enable_hp","hp","enable_lp","lp","enable_notch","notch_freqs","notch_q"]
        for k, (o, n) in zip(names, zip(prev, now)):
            if o != n: self._log_param(k, n)

        self._design_all(reset_state=True)
        self._emit_config()

    def _reset_state(self):
        # réinitialise uniquement les états (garde les coeffs)
        if self._n_ch <= 0:
            self._zi_sos_per_ch = []; self._zi_fir_per_ch = []; return
        if self._sos is not None:
            n_sections = self._sos.shape[0]
            self._zi_sos_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(self._n_ch)]
        else:
            self._zi_sos_per_ch = []
        if self._fir_b is not None and len(self._fir_b) > 1:
            L = len(self._fir_b) - 1
            self._zi_fir_per_ch = [np.zeros(L, dtype=np.float64) for _ in range(self._n_ch)]
        else:
            self._zi_fir_per_ch = []

    def _design_all(self, reset_state=True):
        """(Re)conçoit les filtres (SOS notch+iir, FIR b) en fonction des params et de fs."""
        if not SCIPY_OK or self._sfreq <= 0 or self._n_ch <= 0:
            self._sos = None; self._fir_b = None; self._zi_sos_per_ch = []; self._zi_fir_per_ch = []; return

        # --- Notch SOS cascade ---
        sos_list = []
        if self._enable_notch:
            try:
                freqs = [float(x) for x in self._notch_str.replace(";", ",").split(",") if str(x).strip()]
            except Exception:
                freqs = []
            for f0 in freqs:
                if 0 < f0 < (self._sfreq/2.0):
                    b, a = iirnotch(w0=float(f0), Q=max(1.0, float(self._notch_q)), fs=float(self._sfreq))
                    sos_list.append(tf2sos(b, a))

        # --- HP/LP selon method ---
        fir_b = None
        if self._method == "fir":
            # FIR via firwin : lowpass / highpass / bandpass
            taps = max(21, int(self._fir_taps) | 1)  # force impair
            hp_on, lp_on = bool(self._enable_hp), bool(self._enable_lp)
            hp, lp = float(self._hp), float(self._lp)
            nyq = self._sfreq / 2.0
            if hp_on and lp_on and 0 < hp < lp < nyq:
                fir_b = firwin(taps, [hp, lp], pass_zero=False, fs=self._sfreq)
            elif hp_on and 0 < hp < nyq:
                fir_b = firwin(taps, hp, pass_zero=False, fs=self._sfreq)
            elif lp_on and 0 < lp < nyq:
                fir_b = firwin(taps, lp, pass_zero=True, fs=self._sfreq)
            # sinon, pas de FIR
        else:
            # IIR Butter en SOS
            hp_on, lp_on = bool(self._enable_hp), bool(self._enable_lp)
            hp, lp = float(self._hp), float(self._lp)
            ord_ = max(1, int(self._iir_order))
            if hp_on and 0 < hp < (self._sfreq/2.0):
                sos_list.append(butter(ord_, hp, btype="highpass", fs=self._sfreq, output="sos"))
            if lp_on and 0 < lp < (self._sfreq/2.0):
                sos_list.append(butter(ord_, lp, btype="lowpass", fs=self._sfreq, output="sos"))

        # assemble SOS
        self._sos = np.vstack(sos_list) if len(sos_list) > 0 else None
        self._fir_b = np.asarray(fir_b, dtype=np.float64) if fir_b is not None else None

        if reset_state:
            self._reset_state()

    def _emit_meta_if_changed(self, info=None):
        if self._sfreq > 0 and self._sfreq != self._sent_sfreq:
            self.outputs["sfreq"].on_next(self._sfreq); self._sent_sfreq = self._sfreq
        if self._n_ch > 0 and self._ch_names:
            if self._sent_ch_names is None or self._sent_ch_names != self._ch_names:
                self.outputs["ch_names"].on_next(self._ch_names); self._sent_ch_names = list(self._ch_names)
        meta = info if isinstance(info, dict) else self._last_info
        if isinstance(meta, dict) and meta != self._sent_info:
            self.outputs["info"].on_next(meta); self._sent_info = dict(meta)

    # ---------- exécution ----------
    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict): args.update(inputs)
        args.update(kwargs)

        # ---- meta in ----
        info = args.get("info", None)
        sf_kw = args.get("sfreq", None)
        ch_kw = args.get("ch_names", None)

        sf = float(sf_kw) if isinstance(sf_kw, (int, float)) else None
        chn = list(ch_kw) if isinstance(ch_kw, (list, tuple)) else None

        if isinstance(info, dict):
            self._last_info = info
            if sf is None and isinstance(info.get("sfreq", None), (int, float)): sf = float(info["sfreq"])
            if chn is None and isinstance(info.get("ch_names", None), (list, tuple)): chn = list(info["ch_names"])

        changed = False
        if isinstance(sf, (int, float)) and sf > 0 and sf != self._sfreq:
            self._sfreq = sf; changed = True
        if isinstance(chn, list) and chn:
            if len(chn) != self._n_ch or chn != self._ch_names:
                self._ch_names = chn; self._n_ch = len(chn); changed = True
        if changed:
            self._design_all(reset_state=True)

        self._emit_meta_if_changed(info=info)

        # ---- signal ----
        seg = args.get("segment", None)
        if seg is None:
            return {}

        # orientation robuste
        arr = np.asarray(seg)
        if arr.ndim == 1: arr = arr[None, :]
        exp_n_ch = None
        if self._ch_names and len(self._ch_names) > 0: exp_n_ch = len(self._ch_names)
        elif isinstance(ch_kw, (list, tuple)) and len(ch_kw) > 0: exp_n_ch = len(ch_kw)
        if exp_n_ch is not None:
            if arr.shape[0] == exp_n_ch:
                pass
            elif arr.shape[1] == exp_n_ch:
                arr = arr.T
        arr = np.asarray(arr, dtype=np.float32, order="C")

        # init après orientation
        if self._n_ch <= 0:
            self._n_ch = int(arr.shape[0])
            if not self._ch_names or len(self._ch_names) != self._n_ch:
                if isinstance(ch_kw, (list, tuple)) and len(ch_kw) > 0:
                    ch_tmp = list(ch_kw)
                    self._ch_names = ch_tmp[:self._n_ch] if len(ch_tmp) >= self._n_ch else ch_tmp + [f"ch{i+1}" for i in range(len(ch_tmp), self._n_ch)]
                else:
                    self._ch_names = [f"ch{idx+1}" for idx in range(self._n_ch)]
            self._design_all(reset_state=True)
            self._emit_meta_if_changed()

        # --- Filtrage & métriques ---
        do_filter = (not self._bypass) and (self._sfreq > 0) and (self._sos is not None or self._fir_b is not None)
        # FILTER_START
        if do_filter:
            try:
                metrics().event(
                    "FILTER_START",
                    method=self._method,
                    fir_taps=(int(self._fir_taps) if self._method=="fir" else 0),
                    iir_order=(int(self._iir_order) if self._method=="iir" else 0),
                    enable_hp=int(self._enable_hp), hp=float(self._hp),
                    enable_lp=int(self._enable_lp), lp=float(self._lp),
                    enable_notch=int(self._enable_notch),
                    notch_q=float(self._notch_q),
                    notch_freqs=self._notch_str.replace(",", ";")
                )
            except Exception:
                pass

        t0 = time.perf_counter()
        try:
            if not do_filter:
                self.outputs["segment"].on_next(arr)
                self._emit_meta_if_changed()
                return {}

            x = arr.astype(np.float64, copy=False)
            y = x

            n_ch, n = y.shape

            # 1) Notch + IIR (SOS) si dispo
            if self._sos is not None:
                if len(self._zi_sos_per_ch) != n_ch or (len(self._zi_sos_per_ch)>0 and self._zi_sos_per_ch[0].shape[0] != self._sos.shape[0]):
                    # réinit états si dimension change
                    n_sections = self._sos.shape[0]
                    self._zi_sos_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(n_ch)]
                y2 = np.empty_like(y)
                for ch in range(n_ch):
                    y2[ch, :], self._zi_sos_per_ch[ch] = sosfilt(self._sos, y[ch, :], zi=self._zi_sos_per_ch[ch])
                y = y2

            # 2) FIR si dispo
            if self._fir_b is not None and len(self._fir_b) > 1:
                L = len(self._fir_b) - 1
                if len(self._zi_fir_per_ch) != n_ch or (len(self._zi_fir_per_ch)>0 and self._zi_fir_per_ch[0].shape[0] != L):
                    self._zi_fir_per_ch = [np.zeros(L, dtype=np.float64) for _ in range(n_ch)]
                y2 = np.empty_like(y)
                for ch in range(n_ch):
                    y2[ch, :], self._zi_fir_per_ch[ch] = lfilter(self._fir_b, [1.0], y[ch, :], zi=self._zi_fir_per_ch[ch])
                y = y2

            y = y.astype(arr.dtype, copy=False)

            # métriques fin
            dt = max(1e-12, time.perf_counter() - t0)
            fs = float(self._sfreq)
            seg_real_s = (float(y.shape[1]) / fs) if (fs > 0) else 0.0
            throughput_sps = float(self._n_ch * y.shape[1]) / dt
            rt_factor = (seg_real_s / dt) if dt > 0 else 0.0
            try:
                metrics().event(
                    "FILTER_DONE",
                    method=self._method,
                    fir_taps=(int(self._fir_taps) if self._method=="fir" else 0),
                    iir_order=(int(self._iir_order) if self._method=="iir" else 0),
                    dur_s=dt,
                    throughput_sps=throughput_sps,
                    rt_factor=rt_factor,
                    n_ch=int(self._n_ch),
                    n=int(y.shape[1]),
                    fs=fs
                )
            except Exception:
                pass

            self.outputs["segment"].on_next(y)
            self._emit_meta_if_changed()
            return {}

        except Exception as e:
            # FAIL
            try:
                metrics().event("FILTER_FAIL", error=str(e).replace(",", ";"))
            except Exception:
                pass
            # propage le signal d'entrée pour rester robuste
            self.outputs["segment"].on_next(arr)
            self._emit_meta_if_changed()
            return {}
