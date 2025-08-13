# plugins/eeg_filter_plugin.py
# EEGSliceFilter : filtrage streaming (HP/LP/Notch) par fenêtres, avec état persistant
# + UI repliable "Paramètres" (zéro espace résiduel quand fermé)

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton,
    QLayout, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt
from core.node_base import BasePlugin

try:
    from scipy.signal import butter, sosfilt, iirnotch, tf2sos
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


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
            if w.layout():
                w.layout().invalidate()
            w.adjustSize()
            w.updateGeometry()
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


class EEGFilterPlugin(BasePlugin):
    """
    Entrées:
      - segment : np.ndarray (n_ch, n_samples) OU (n_samples, n_ch)
      - info    : dict {'sfreq': float, 'ch_names': list[str]}  (optionnel)
      - sfreq   : float (optionnel)
      - ch_names: list[str] (optionnel)

    Sorties:
      - segment   : np.ndarray filtré (n_ch, n_samples)
      - info      : pass-through (dict)
      - sfreq     : float
      - ch_names  : list[str]
    """
    name = "EEGSliceFilter"
    category = "Processing Nodes"

    # --------------- Setup ---------------
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
        }

        # Params défaut
        self._enable_hp = True
        self._hp = 1.0         # Hz
        self._enable_lp = True
        self._lp = 40.0        # Hz
        self._order = 4

        self._enable_notch = False
        self._notch_f = 50.0   # Hz
        self._notch_q = 30.0

        self._bypass = False

        # Meta (cache)
        self._sfreq = 0.0
        self._ch_names = []
        self._n_ch = 0
        self._last_info = None

        # Filtre courant
        self._sos = None
        self._zi_per_ch = []

        # UI refs
        self.chk_hp = self.spn_hp = None
        self.chk_lp = self.spn_lp = self.spn_order = None
        self.chk_notch = self.spn_notch = self.spn_q = None
        self.chk_bypass = None

    # --------------- UI ---------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if not SCIPY_OK:
            v.addWidget(QLabel("❌ SciPy manquant. Installe :  pip install scipy"))
            return w

        # contenu paramètres
        panel = QWidget()
        pv = QVBoxLayout(panel); pv.setContentsMargins(8, 8, 8, 8)

        row1 = QHBoxLayout()
        self.chk_hp = QCheckBox("HP"); self.chk_hp.setChecked(self._enable_hp); self.chk_hp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_hp)

        row1.addWidget(QLabel("HP (Hz):"))
        self.spn_hp = QDoubleSpinBox(); self.spn_hp.setRange(0.01, 100.0); self.spn_hp.setSingleStep(0.1); self.spn_hp.setValue(self._hp)
        self.spn_hp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_hp)

        self.chk_lp = QCheckBox("LP"); self.chk_lp.setChecked(self._enable_lp); self.chk_lp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_lp)

        row1.addWidget(QLabel("LP (Hz):"))
        self.spn_lp = QDoubleSpinBox(); self.spn_lp.setRange(1.0, 200.0); self.spn_lp.setSingleStep(1.0); self.spn_lp.setValue(self._lp)
        self.spn_lp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_lp)

        row1.addWidget(QLabel("Order:"))
        self.spn_order = QSpinBox(); self.spn_order.setRange(1, 10); self.spn_order.setValue(self._order); self.spn_order.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_order)
        pv.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_notch = QCheckBox("Notch"); self.chk_notch.setChecked(self._enable_notch); self.chk_notch.stateChanged.connect(self._on_params_changed)
        row2.addWidget(self.chk_notch)

        row2.addWidget(QLabel("f0 (Hz):"))
        self.spn_notch = QDoubleSpinBox(); self.spn_notch.setRange(1.0, 200.0); self.spn_notch.setSingleStep(1.0); self.spn_notch.setValue(self._notch_f)
        self.spn_notch.valueChanged.connect(self._on_params_changed)
        row2.addWidget(self.spn_notch)

        row2.addWidget(QLabel("Q:"))
        self.spn_q = QDoubleSpinBox(); self.spn_q.setRange(1.0, 100.0); self.spn_q.setSingleStep(1.0); self.spn_q.setValue(self._notch_q)
        self.spn_q.valueChanged.connect(self._on_params_changed)
        row2.addWidget(self.spn_q)

        self.chk_bypass = QCheckBox("Bypass"); self.chk_bypass.setChecked(self._bypass); self.chk_bypass.stateChanged.connect(self._on_params_changed)
        row2.addWidget(self.chk_bypass)

        btn_reset = QPushButton("Reset state"); btn_reset.clicked.connect(self._reset_state)
        row2.addWidget(btn_reset)
        row2.addStretch(1)
        pv.addLayout(row2)

        pv.addWidget(QLabel("Astuce: LP=15 Hz coupe la composante 20 Hz du simulateur; Notch=10 Hz annule l'alpha 10 Hz."))

        # section repliable
        section = _CollapsibleSection("Paramètres", panel, collapsed=True)
        v.addWidget(section)

        return w

    # --------------- Logic ---------------
    def _on_params_changed(self, *args):
        self._enable_hp = self.chk_hp.isChecked()
        self._hp = float(self.spn_hp.value())
        self._enable_lp = self.chk_lp.isChecked()
        self._lp = float(self.spn_lp.value())
        self._order = int(self.spn_order.value())
        self._enable_notch = self.chk_notch.isChecked()
        self._notch_f = float(self.spn_notch.value())
        self._notch_q = float(self.spn_q.value())
        self._bypass = self.chk_bypass.isChecked()
        self._sos = None
        self._zi_per_ch = []

    def _reset_state(self):
        if self._sos is None or self._n_ch <= 0:
            self._zi_per_ch = []
            return
        n_sections = self._sos.shape[0]
        self._zi_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(self._n_ch)]

    def _normalize(self, seg):
        arr = np.asarray(seg)
        if arr.ndim == 1:
            arr = arr[None, :]
        if arr.shape[0] > arr.shape[1]:
            arr = arr.T
        return arr

    def _design_if_needed(self):
        if not SCIPY_OK or self._sfreq <= 0 or self._n_ch <= 0:
            self._sos = None
            self._zi_per_ch = []
            return

        sos_list = []
        if self._enable_notch and 0 < self._notch_f < (self._sfreq / 2):
            b, a = iirnotch(w0=self._notch_f, Q=max(1.0, self._notch_q), fs=self._sfreq)
            sos_list.append(tf2sos(b, a))
        if self._enable_hp and 0 < self._hp < (self._sfreq / 2):
            sos_list.append(butter(self._order, self._hp, btype='highpass', fs=self._sfreq, output='sos'))
        if self._enable_lp and 0 < self._lp < (self._sfreq / 2):
            sos_list.append(butter(self._order, self._lp, btype='lowpass', fs=self._sfreq, output='sos'))

        if not sos_list:
            self._sos = None
            self._zi_per_ch = []
            return

        self._sos = np.vstack(sos_list)
        n_sections = self._sos.shape[0]
        self._zi_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(self._n_ch)]

    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        # ---- meta ----
        info = args.get("info", None)
        sf_kw = args.get("sfreq", None)
        ch_kw = args.get("ch_names", None)

        sf = float(sf_kw) if isinstance(sf_kw, (int, float)) else None
        chn = list(ch_kw) if isinstance(ch_kw, (list, tuple)) else None

        if isinstance(info, dict):
            self._last_info = info
            if sf is None and isinstance(info.get("sfreq", None), (int, float)):
                sf = float(info["sfreq"])
            if chn is None and isinstance(info.get("ch_names", None), (list, tuple)):
                chn = list(info["ch_names"])

        changed = False
        if isinstance(sf, (int, float)) and sf > 0 and sf != self._sfreq:
            self._sfreq = sf; changed = True
        if isinstance(chn, list) and chn:
            if len(chn) != self._n_ch or chn != self._ch_names:
                self._ch_names = chn; self._n_ch = len(chn); changed = True
        if changed:
            self._sos = None

        self._design_if_needed()

        if self._sfreq > 0:
            self.outputs["sfreq"].on_next(self._sfreq)
        if self._n_ch > 0 and self._ch_names:
            self.outputs["ch_names"].on_next(self._ch_names)
        if isinstance(info, dict):
            self.outputs["info"].on_next(info)
        elif isinstance(self._last_info, dict):
            self.outputs["info"].on_next(self._last_info)

        # ---- signal ----
        seg = args.get("segment", None)
        if seg is None:
            return {}

        arr = self._normalize(seg)

        if self._n_ch <= 0:
            self._n_ch = int(arr.shape[0])
            if not self._ch_names or len(self._ch_names) != self._n_ch:
                self._ch_names = [f"ch{idx+1}" for idx in range(self._n_ch)]
                self.outputs["ch_names"].on_next(self._ch_names)
            self._sos = None
            self._design_if_needed()

        if self._bypass or self._sos is None or self._sfreq <= 0:
            self.outputs["segment"].on_next(arr.astype(np.float32, copy=False))
            if self._sfreq > 0:
                self.outputs["sfreq"].on_next(self._sfreq)
            if self._ch_names:
                self.outputs["ch_names"].on_next(self._ch_names)
            if isinstance(self._last_info, dict):
                self.outputs["info"].on_next(self._last_info)
            return {}

        n_ch, _ = arr.shape
        if n_ch != self._n_ch or len(self._zi_per_ch) != n_ch:
            self._n_ch = n_ch
            self._sos = None
            self._design_if_needed()

        y = np.empty_like(arr, dtype=np.float64)
        for ch in range(n_ch):
            x = arr[ch, :].astype(np.float64, copy=False)
            zi = self._zi_per_ch[ch]
            y_ch, zi_new = sosfilt(self._sos, x, zi=zi)
            self._zi_per_ch[ch] = zi_new
            y[ch, :] = y_ch
        y = y.astype(arr.dtype, copy=False)

        self.outputs["segment"].on_next(y)
        if self._sfreq > 0:
            self.outputs["sfreq"].on_next(self._sfreq)
        if self._ch_names:
            self.outputs["ch_names"].on_next(self._ch_names)
        if isinstance(self._last_info, dict):
            self.outputs["info"].on_next(self._last_info)

        return {}
