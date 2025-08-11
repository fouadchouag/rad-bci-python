# plugins/eeg_filter_plugin.py
# EEGFilterPlugin : filtre streaming (HP/LP/Notch) avec état persistant par canal.
# Dépendances : pip install scipy

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton
)
from core.node_base import BasePlugin

try:
    from scipy.signal import butter, sosfilt, iirnotch, tf2sos
    SCIPY_OK = True
except Exception:
    SCIPY_OK = False


class EEGFilterPlugin(BasePlugin):
    """
    Entrées:
      - segment : np.ndarray (n_ch, n_samples) OU (n_samples, n_ch) (Volts)
      - info    : dict {'sfreq': float, 'ch_names': list[str]}  (optionnel)
      - sfreq   : float (optionnel, alternative à info)
      - ch_names: list[str] (optionnel, alternative à info)

    Sorties:
      - segment   : np.ndarray filtré (orientation (n_ch, n_samples))
      - info      : pass-through (dict)
      - sfreq     : float (toujours émis quand connu)
      - ch_names  : list[str] (toujours émis quand connu)

    Notes:
      - État (zi) persistant par canal → pas de "réinitialisation" à chaque chunk.
      - Re-design auto si Fs change, nb de canaux change, ou paramètres UI changent.
    """
    name = "EEGSliceFilter"
    category = "Processing Nodes"

    # --------------- Setup ---------------
    def setup(self):
        self.inputs = {
            "segment": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            # facultatifs si un pipeline envoie ces champs séparément
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
        self._notch_f = 50.0   # Hz (ou 60.0 selon secteur)
        self._notch_q = 30.0

        self._bypass = False

        # Meta (cache)
        self._sfreq = 0.0
        self._ch_names = []
        self._n_ch = 0
        self._last_info = None

        # Filtre courant
        self._sos = None                 # np.ndarray (n_sections, 6)
        self._zi_per_ch = []             # list[np.ndarray (n_sections, 2)]

    # --------------- UI ---------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        if not SCIPY_OK:
            v.addWidget(QLabel("❌ SciPy manquant. Installe :  pip install scipy"))
            return w

        # HP/LP ligne
        row1 = QHBoxLayout()
        self.chk_hp = QCheckBox("HP")
        self.chk_hp.setChecked(self._enable_hp)
        self.chk_hp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_hp)

        row1.addWidget(QLabel("HP (Hz):"))
        self.spn_hp = QDoubleSpinBox()
        self.spn_hp.setRange(0.01, 100.0)
        self.spn_hp.setSingleStep(0.1)
        self.spn_hp.setValue(self._hp)
        self.spn_hp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_hp)

        self.chk_lp = QCheckBox("LP")
        self.chk_lp.setChecked(self._enable_lp)
        self.chk_lp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_lp)

        row1.addWidget(QLabel("LP (Hz):"))
        self.spn_lp = QDoubleSpinBox()
        self.spn_lp.setRange(1.0, 200.0)
        self.spn_lp.setSingleStep(1.0)
        self.spn_lp.setValue(self._lp)
        self.spn_lp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_lp)

        row1.addWidget(QLabel("Order:"))
        self.spn_order = QSpinBox()
        self.spn_order.setRange(1, 10)
        self.spn_order.setValue(self._order)
        self.spn_order.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_order)
        v.addLayout(row1)

        # Notch ligne
        row2 = QHBoxLayout()
        self.chk_notch = QCheckBox("Notch")
        self.chk_notch.setChecked(self._enable_notch)
        self.chk_notch.stateChanged.connect(self._on_params_changed)
        row2.addWidget(self.chk_notch)

        row2.addWidget(QLabel("f0 (Hz):"))
        self.spn_notch = QDoubleSpinBox()
        self.spn_notch.setRange(1.0, 200.0)
        self.spn_notch.setSingleStep(1.0)
        self.spn_notch.setValue(self._notch_f)
        self.spn_notch.valueChanged.connect(self._on_params_changed)
        row2.addWidget(self.spn_notch)

        row2.addWidget(QLabel("Q:"))
        self.spn_q = QDoubleSpinBox()
        self.spn_q.setRange(1.0, 100.0)
        self.spn_q.setSingleStep(1.0)
        self.spn_q.setValue(self._notch_q)
        self.spn_q.valueChanged.connect(self._on_params_changed)
        row2.addWidget(self.spn_q)

        self.chk_bypass = QCheckBox("Bypass")
        self.chk_bypass.setChecked(self._bypass)
        self.chk_bypass.stateChanged.connect(self._on_params_changed)
        row2.addWidget(self.chk_bypass)

        btn_reset = QPushButton("Reset state")
        btn_reset.clicked.connect(self._reset_state)
        row2.addWidget(btn_reset)

        row2.addStretch(1)
        v.addLayout(row2)

        v.addWidget(QLabel(
            "Astuce: LP=15 Hz coupe la composante 20 Hz du simulateur; Notch=10 Hz annule l'alpha 10 Hz."
        ))
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

        # Forcer redesign au prochain segment
        self._sos = None
        self._zi_per_ch = []

    def _reset_state(self):
        # Conserve le même filtre mais remet l'état à zéro
        if self._sos is None or self._n_ch <= 0:
            self._zi_per_ch = []
            return
        n_sections = self._sos.shape[0]
        self._zi_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(self._n_ch)]

    def _normalize(self, seg):
        """Retourne np.ndarray en (n_ch, n_samples)."""
        arr = np.asarray(seg)
        if arr.ndim == 1:
            arr = arr[None, :]
        # canaux en 1ère dimension
        if arr.shape[0] > arr.shape[1]:
            arr = arr.T
        return arr

    def _design_if_needed(self):
        """(Re)construit la cascade SOS et réinitialise l'état par canal si nécessaire."""
        if not SCIPY_OK or self._sfreq <= 0 or self._n_ch <= 0:
            self._sos = None
            self._zi_per_ch = []
            return

        sos_list = []

        # Notch (optionnel)
        if self._enable_notch and 0 < self._notch_f < (self._sfreq / 2):
            b, a = iirnotch(w0=self._notch_f, Q=max(1.0, self._notch_q), fs=self._sfreq)
            sos_list.append(tf2sos(b, a))

        # High-pass (optionnel)
        if self._enable_hp and 0 < self._hp < (self._sfreq / 2):
            sos_list.append(butter(self._order, self._hp, btype='highpass',
                                   fs=self._sfreq, output='sos'))

        # Low-pass (optionnel)
        if self._enable_lp and 0 < self._lp < (self._sfreq / 2):
            sos_list.append(butter(self._order, self._lp, btype='lowpass',
                                   fs=self._sfreq, output='sos'))

        if len(sos_list) == 0:
            self._sos = None
            self._zi_per_ch = []
            return

        self._sos = np.vstack(sos_list)  # (n_sections, 6)

        # (ré)initialise l'état par canal
        n_sections = self._sos.shape[0]
        self._zi_per_ch = [np.zeros((n_sections, 2), dtype=np.float64) for _ in range(self._n_ch)]

    # >>> API du moteur : accepte dict inputs ET **kwargs
    def execute(self, inputs=None, **kwargs):
        """
        Accepte soit un dict 'inputs', soit des kwargs (segment=..., info=..., sfreq=..., ch_names=...).
        """
        # Fusionne inputs (dict) + kwargs
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        # ---- Récupération / mise à jour des métadonnées ----
        info = args.get("info", None)
        sf_kw = args.get("sfreq", None)
        ch_kw = args.get("ch_names", None)

        # Priorité aux kwargs directs si fournis; sinon via info
        sf = None
        chn = None
        if isinstance(sf_kw, (int, float)):
            sf = float(sf_kw)
        if isinstance(ch_kw, (list, tuple)):
            chn = list(ch_kw)

        if isinstance(info, dict):
            self._last_info = info
            if sf is None and isinstance(info.get("sfreq", None), (int, float)):
                sf = float(info["sfreq"])
            if chn is None and isinstance(info.get("ch_names", None), (list, tuple)):
                chn = list(info["ch_names"])

        # MàJ internes si on a des valeurs
        changed = False
        if isinstance(sf, (int, float)) and sf > 0:
            if sf != self._sfreq:
                self._sfreq = sf
                changed = True
        if isinstance(chn, list) and len(chn) > 0:
            if len(chn) != self._n_ch or chn != self._ch_names:
                self._ch_names = chn
                self._n_ch = len(chn)
                changed = True

        if changed:
            self._sos = None  # force redesign

        # (re)design si nécessaire
        self._design_if_needed()

        # Émettre méta connues (vers sorties dédiées + info pass-through)
        if self._sfreq > 0:
            self.outputs["sfreq"].on_next(self._sfreq)
        if self._n_ch > 0 and self._ch_names:
            self.outputs["ch_names"].on_next(self._ch_names)
        # info : s'il y a info nouveau → push, sinon si on a du cache
        if isinstance(info, dict):
            self.outputs["info"].on_next(info)
        elif isinstance(self._last_info, dict):
            self.outputs["info"].on_next(self._last_info)

        # ---- Signal ----
        seg = args.get("segment", None)
        if seg is None:
            return {}

        arr = self._normalize(seg)  # (n_ch, n_samples)

        # Si nb de canaux non connu, devine-le & (re)design
        if self._n_ch <= 0:
            self._n_ch = int(arr.shape[0])
            if not self._ch_names or len(self._ch_names) != self._n_ch:
                self._ch_names = [f"ch{idx+1}" for idx in range(self._n_ch)]
                self.outputs["ch_names"].on_next(self._ch_names)
            self._sos = None
            self._design_if_needed()

        # Si bypass ou filtre non prêt → passthrough
        if self._bypass or self._sos is None or self._sfreq <= 0:
            self.outputs["segment"].on_next(arr.astype(np.float32, copy=False))
            # ré-émets les méta pour faciliter les pipes segment-only
            if self._sfreq > 0:
                self.outputs["sfreq"].on_next(self._sfreq)
            if self._ch_names:
                self.outputs["ch_names"].on_next(self._ch_names)
            if isinstance(self._last_info, dict):
                self.outputs["info"].on_next(self._last_info)
            return {}

        # Sync état si n_ch change
        n_ch, _ = arr.shape
        if n_ch != self._n_ch or len(self._zi_per_ch) != n_ch:
            self._n_ch = n_ch
            self._sos = None
            self._design_if_needed()

        # Filtrage canal-par-canal avec état persistant
        y = np.empty_like(arr, dtype=np.float64)
        for ch in range(n_ch):
            x = arr[ch, :].astype(np.float64, copy=False)
            zi = self._zi_per_ch[ch]
            y_ch, zi_new = sosfilt(self._sos, x, zi=zi)
            self._zi_per_ch[ch] = zi_new
            y[ch, :] = y_ch

        y = y.astype(arr.dtype, copy=False)
        self.outputs["segment"].on_next(y)

        # ré-émets méta à chaque chunk (robuste pour les nœuds en aval)
        if self._sfreq > 0:
            self.outputs["sfreq"].on_next(self._sfreq)
        if self._ch_names:
            self.outputs["ch_names"].on_next(self._ch_names)
        if isinstance(self._last_info, dict):
            self.outputs["info"].on_next(self._last_info)

        return {}
