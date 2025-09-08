# -*- coding: utf-8 -*-
"""
BandPowerExtractor
- Agrège la PSD (Welch) en bandes (delta/theta/alpha/beta/gamma).
- Pins MINIMALES, UI pliable, compatible export/import_config.
- Supporte PSD linéaire OU en dB (conversion inverse automatique si psd_is_db=True).
- Peut renvoyer puissances ABSOLUTES ou RELATIVES (somme=1 par canal).

Entrées:
    psd        : np.ndarray (n_ch, n_freq)   [requis]
    freqs      : np.ndarray (n_freq,)        [requis]
    ch_names   : list[str]                   [optionnel]
    psd_is_db  : bool                        [def: False]  -> cocher si PSDWelch(as_db=True)
    relative   : bool                        [def: True]   -> normaliser par la puissance totale par canal

Sorties:
    bandpowers : np.ndarray float32 (n_ch, n_bands)
    band_labels: list[str]
    ch_names   : list[str]
    info       : dict ({"relative":bool, "psd_is_db":bool, "bands":[(lo,hi),...]} )

UI:
    - Checkbox "PSD en dB (10*log10)" et "Puissance relative"
    - Plage editable des 5 bandes canoniques (Hz)
    - Bouton "Agrandir" dans le viewer seulement (pas ici)
"""

from typing import Optional, Tuple, List
import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QDoubleSpinBox,
    QCheckBox, QLabel, QLayout, QSizePolicy
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
try:
    from core.collapsible import CollapsibleSection
except Exception:
    # Fallback minimal si pas dispo
    class CollapsibleSection(QWidget):
        help = help = { 'gotchas': ['Use adequate window length for low frequencies.'],
  'inputs': {'segment': '2D float [ch x samples] or epochs', 'sfreq': 'float (Hz)'},
  'outputs': { 'features': 'array/dict',
               'freqs': 'optional freqs',
               'psd': 'optional PSD'},
  'parameters': [ { 'default': 1.0,
                    'desc': 'Lower frequency',
                    'name': 'fmin',
                    'type': 'float',
                    'unit': 'Hz'},
                  { 'default': 40.0,
                    'desc': 'Upper frequency',
                    'name': 'fmax',
                    'type': 'float',
                    'unit': 'Hz'}],
  'summary': 'BandPowerExtractor',
  'usage': 'Connect windowed or epoched data; feed features to ML nodes.'}

        def __init__(self, title, content, collapsed=True, parent=None):
            super().__init__(parent)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0,0,0,0)
            lay.addWidget(content)

class BandPowerExtractor(BasePlugin):
    name = "BandPowerExtractor"
    language = "Python"
    category = "Features"
    supports_collapse = True

    # ---- lifecycle ----
    def setup(self):
        # Inputs (réactifs)
        self.inputs["psd"] = BehaviorSubject(None)
        self.inputs["freqs"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["psd_is_db"] = BehaviorSubject(False)
        self.inputs["relative"] = BehaviorSubject(True)

        # Sorties
        self.outputs["bandpowers"] = BehaviorSubject(None)
        self.outputs["band_labels"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["info"] = BehaviorSubject(None)

        # State/UI
        self._widget = None
        # bandes canoniques par défaut
        self._bands = [
            ("delta", 1.0, 4.0),
            ("theta", 4.0, 8.0),
            ("alpha", 8.0, 13.0),
            ("beta", 13.0, 30.0),
            ("gamma", 30.0, 45.0),
        ]
        self._psd_is_db = False
        self._relative = True

        # Spin refs
        self._spins: List[Tuple[QDoubleSpinBox, QDoubleSpinBox]] = []

    # ---- UI ----
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        w = QWidget()
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8,8,8,8)
        pv.setSpacing(6)

        # Options
        opts = QHBoxLayout()
        chk_db = QCheckBox("PSD en dB (10·log10)")
        chk_db.setChecked(self._psd_is_db)
        chk_db.stateChanged.connect(lambda s: self._on_psd_is_db(bool(s == Qt.Checked)))
        opts.addWidget(chk_db)

        chk_rel = QCheckBox("Puissance relative (somme=1)")
        chk_rel.setChecked(self._relative)
        chk_rel.stateChanged.connect(lambda s: self._on_relative(bool(s == Qt.Checked)))
        opts.addWidget(chk_rel)
        opts.addStretch(1)
        pv.addLayout(opts)

        # Bandes éditables
        form = QFormLayout()
        self._spins.clear()
        for (label, lo, hi) in self._bands:
            r = QHBoxLayout()
            sp_lo = QDoubleSpinBox(); sp_lo.setDecimals(2); sp_lo.setRange(0.0, 2000.0); sp_lo.setValue(lo)
            sp_hi = QDoubleSpinBox(); sp_hi.setDecimals(2); sp_hi.setRange(0.0, 2000.0); sp_hi.setValue(hi)
            sp_lo.valueChanged.connect(self._on_band_changed)
            sp_hi.valueChanged.connect(self._on_band_changed)
            r.addWidget(QLabel("lo")); r.addWidget(sp_lo)
            r.addSpacing(8)
            r.addWidget(QLabel("hi")); r.addWidget(sp_hi)
            r.addStretch(1)
            form.addRow(f"{label}", r)
            self._spins.append((sp_lo, sp_hi))
        pv.addLayout(form)

        root.addWidget(CollapsibleSection("BandPower — paramètres", panel, collapsed=True))
        self._widget = w
        return w

    # ---- config I/O ----
    def export_config(self) -> dict:
        return {
            "psd_is_db": bool(self._psd_is_db),
            "relative": bool(self._relative),
            "bands": [(lbl, float(lo), float(hi)) for (lbl, lo, hi) in self._bands],
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self._psd_is_db = bool(cfg.get("psd_is_db", self._psd_is_db))
        self._relative = bool(cfg.get("relative", self._relative))
        bands = cfg.get("bands", None)
        if isinstance(bands, list) and all(isinstance(t, (list, tuple)) and len(t) == 3 for t in bands):
            cleaned = []
            for lbl, lo, hi in bands:
                try:
                    cleaned.append((str(lbl), float(lo), float(hi)))
                except Exception:
                    pass
            if cleaned:
                self._bands = cleaned

        # sync UI si présente
        if self._widget is not None and self._spins:
            for i, (lbl, lo, hi) in enumerate(self._bands[:len(self._spins)]):
                sp_lo, sp_hi = self._spins[i]
                sp_lo.blockSignals(True); sp_hi.blockSignals(True)
                sp_lo.setValue(lo); sp_hi.setValue(hi)
                sp_lo.blockSignals(False); sp_hi.blockSignals(False)

    def config_hints(self) -> dict:
        return {
            "fields": {
                "psd_is_db": {"type": "bool", "label": "PSD en dB (10·log10)"},
                "relative": {"type": "bool", "label": "Puissance relative"},
                "bands": {"type": "list[tuple]", "help": "[(label, f_lo, f_hi), ...]"},
            }
        }

    # ---- UI callbacks ----
    def _on_psd_is_db(self, b: bool):
        self._psd_is_db = bool(b)
        self.execute(**getattr(self, "_last_inputs", {}))

    def _on_relative(self, b: bool):
        self._relative = bool(b)
        self.execute(**getattr(self, "_last_inputs", {}))

    def _on_band_changed(self, *_):
        # lire UI -> self._bands
        new_bands = []
        labels = [lbl for (lbl, _, _) in self._bands]
        for i, (sp_lo, sp_hi) in enumerate(self._spins):
            lo = float(sp_lo.value()); hi = float(sp_hi.value())
            if hi > lo:
                new_bands.append((labels[i], lo, hi))
            else:
                new_bands.append((labels[i], hi, lo))
        self._bands = new_bands
        self.execute(**getattr(self, "_last_inputs", {}))

    # ---- main ----
    def execute(self, in_data=None, **kwargs):
        # tolérant aux 2 styles (comme les autres nœuds)
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        self._last_inputs = dict(in_data)

        psd = in_data.get("psd", None)
        freqs = in_data.get("freqs", None)
        ch_names = in_data.get("ch_names", None)
        psd_is_db = bool(in_data.get("psd_is_db", self._psd_is_db))
        relative = bool(in_data.get("relative", self._relative))

        if psd is None or freqs is None:
            # couper les sorties
            self.outputs["bandpowers"].on_next(None)
            self.outputs["band_labels"].on_next(None)
            self.outputs["ch_names"].on_next(ch_names if isinstance(ch_names, list) else None)
            self.outputs["info"].on_next(None)
            return {}

        arr = np.asarray(psd)
        f = np.asarray(freqs).ravel()
        if arr.ndim != 2 or f.ndim != 1 or arr.shape[1] != f.shape[0]:
            # dimensions invalides
            self.outputs["bandpowers"].on_next(None)
            self.outputs["band_labels"].on_next(None)
            self.outputs["ch_names"].on_next(ch_names if isinstance(ch_names, list) else None)
            self.outputs["info"].on_next(None)
            return {}

        # Si PSD est en dB, revenir en linéaire pour l'intégration
        # (sinon la somme en dB n'a pas de sens physique)
        if psd_is_db:
            arr_lin = 10.0 ** (arr / 10.0)
        else:
            arr_lin = arr

        # Intégration en bande par somme des bins (pas de trapz ici: Welch déjà moyenne)
        labels = [lbl for (lbl, _, _) in self._bands]
        band_mat = np.zeros((arr.shape[0], len(self._bands)), dtype=np.float64)

        for j, (_, flo, fhi) in enumerate(self._bands):
            mask = (f >= float(flo)) & (f <= float(fhi))
            if not np.any(mask):
                band_mat[:, j] = 0.0
            else:
                band_mat[:, j] = np.sum(arr_lin[:, mask], axis=1)

        if relative:
            total = np.sum(arr_lin, axis=1, keepdims=True)  # puissance totale par canal
            total[total <= 0] = 1.0
            band_mat = band_mat / total

        band_mat = band_mat.astype(np.float32, copy=False)
        out_names = list(ch_names) if isinstance(ch_names, list) else [f"ch{i+1}" for i in range(arr.shape[0])]

        info = {
            "relative": bool(relative),
            "psd_is_db": bool(psd_is_db),
            "bands": [(lbl, float(lo), float(hi)) for (lbl, lo, hi) in self._bands],
        }

        self.outputs["bandpowers"].on_next(band_mat)
        self.outputs["band_labels"].on_next(labels)
        self.outputs["ch_names"].on_next(out_names)
        self.outputs["info"].on_next(info)
        return {}