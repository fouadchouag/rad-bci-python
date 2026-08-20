# -*- coding: utf-8 -*-
"""
PSDBandFeaturesLite
- Calcule la puissance par bandes (delta/theta/alpha/beta/gamma) à partir (freqs, psd).
- Sort un tableau Python (list[dict]) utilisable par un node "Features" / table.

Entrées:
    freqs : np.ndarray, shape (n_f,)
    psd   : np.ndarray, shape (n_ch, n_f) ou (n_ep, n_ch, n_f)
    ch_names : list[str] (optionnel)
    use_relative : bool (UI) -> ajoute *_rel

Sorties:
    features : list[dict] par canal, ex:
      {"ch":"Fz","delta":...,"theta":...,"alpha":...,"beta":...,"gamma":...,"alpha_rel":...}
"""

from typing import Optional, List, Tuple
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QCheckBox, QLabel, QLayout, QSizePolicy, QDoubleSpinBox
)
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


class PSDBandFeaturesLite(BasePlugin):
    help = {
        'summary': 'Compute per-band power features from precomputed frequency arrays and PSD matrix.',
        'inputs': {
            'freqs': '1D float ndarray — frequency axis in Hz (from upstream PSD node)',
            'psd': '2D float [channels x freqs] or 3D [epochs x channels x freqs] — power spectral density',
            'ch_names': 'list[str] — optional channel names (auto-generated as ch1, ch2, ... if missing)',
        },
        'outputs': {
            'features': 'list[dict] — per-channel band power dict, each with keys: ch, delta, theta, alpha, beta, gamma (and *_rel if relative mode is on)',
            'config_out': 'dict — current configuration {"use_relative": bool, "bands": list}',
        },
        'parameters': [
            {'name': 'use_relative', 'type': 'bool', 'default': True,
             'desc': 'If True, adds *_rel keys to output (each band power divided by total integrated power). Toggle from UI checkbox.'},
        ],
        'gotchas': [
            'This node does NOT compute PSD — it expects precomputed freqs and psd from an upstream PSD node.',
            'If psd is 3D (epochs), it is averaged across the epoch axis before computing band powers.',
            'Band definitions are hardcoded: delta [0.5–4], theta [4–8], alpha [8–13], beta [13–30], gamma [30–45] Hz.',
            'Relative power divides by total integrated power (trapz over full spectrum); if total is 0, relative values are 0.',
            'The output features list has one dict per channel, each containing the band name as a key.',
            'Bands are editable via ConfigNode (import_config/export_config), not directly in the UI.',
            'Frequency axis and PSD matrix dimensions must be compatible (n_freqs must match).',
        ],
        'usage': 'Connect a freqs array and PSD matrix from an upstream PSD computation node (e.g., a Welch or FFT node). Outputs per-channel band power features as a list of dicts.',
    }

    name = "PSDBandFeaturesLite"
    language = "Python"
    category = "Features"
    supports_collapse = True

    def setup(self):
        self.inputs["freqs"] = BehaviorSubject(None)
        self.inputs["psd"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        self.outputs["features"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # Bands (Hz)
        self._bands: List[Tuple[str, float, float]] = [
            ("delta", 0.5, 4.0),
            ("theta", 4.0, 8.0),
            ("alpha", 8.0, 13.0),
            ("beta", 13.0, 30.0),
            ("gamma", 30.0, 45.0),
        ]
        self._use_relative = True

        # UI
        self._chk_rel = None

    # config
    def export_config(self) -> dict:
        return {
            "use_relative": bool(self._use_relative),
            "bands": [(n, float(a), float(b)) for (n,a,b) in self._bands],
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self._use_relative = bool(cfg.get("use_relative", self._use_relative))
        bands = cfg.get("bands", None)
        if isinstance(bands, (list, tuple)) and bands:
            cleaned = []
            for it in bands:
                try:
                    n, a, b = it
                    cleaned.append((str(n), float(a), float(b)))
                except Exception:
                    pass
            if cleaned:
                self._bands = cleaned
        if self._chk_rel:
            self._chk_rel.blockSignals(True); self._chk_rel.setChecked(self._use_relative); self._chk_rel.blockSignals(False)
        self._emit_config()
        # relancer si data dispo
        self.execute(freqs=self.inputs["freqs"].value, psd=self.inputs["psd"].value, ch_names=self.inputs["ch_names"].value)

    def config_hints(self) -> dict:
        return {
            "fields": {
                "use_relative": {"type": "bool", "label": "Puissances relatives"},
                # bandes éditables via config node si besoin
            },
            "_order": ["use_relative"],
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # UI
    def build_widget(self):
        root = QWidget()
        UiKit.apply_node_style(root)
        v = QVBoxLayout(root)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        pv = QVBoxLayout(panel)

        r1 = QHBoxLayout()
        self._chk_rel = QCheckBox("Puissances relatives")
        self._chk_rel.setChecked(self._use_relative)
        self._chk_rel.stateChanged.connect(lambda _: self._on_rel_toggled())
        r1.addWidget(self._chk_rel)
        r1.addStretch(1)
        pv.addLayout(r1)

        pv.addWidget(QLabel("Bandes (éditables via ConfigNode): "
                            + ", ".join([f"{n}[{a}-{b}]" for n,a,b in self._bands])))
        v.addWidget(CollapsibleSection("Band Features (PSD)", panel, collapsed=True))
        self._emit_config()
        return root

    def _on_rel_toggled(self):
        self._use_relative = bool(self._chk_rel.isChecked())
        self._emit_config()
        self.execute(freqs=self.inputs["freqs"].value, psd=self.inputs["psd"].value, ch_names=self.inputs["ch_names"].value)

    # core
    def _band_power(self, f, P, f0, f1):
        m = (f >= f0) & (f < f1)
        if not np.any(m):
            return 0.0
        # intégrale trapézoïdale
        return float(np.trapz(P[m], f[m]))

    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        freqs = in_data.get("freqs", None) or in_data.get("f", None)
        psd = in_data.get("psd", None) or in_data.get("Pxx", None)
        chn = in_data.get("ch_names", None)

        if freqs is None or psd is None:
            self.outputs["features"].on_next(None)
            return {}

        f = np.asarray(freqs).astype(float).ravel()
        A = np.asarray(psd)
        if A.ndim == 3:
            A = A.mean(axis=0)
        if A.ndim == 2 and A.shape[1] == f.shape[0]:
            pass
        elif A.ndim == 2 and A.shape[0] == f.shape[0]:
            A = A.T
        else:
            self.outputs["features"].on_next(None)
            return {}

        names = list(chn) if isinstance(chn, (list, tuple)) and len(chn) == A.shape[0] else [f"ch{i+1}" for i in range(A.shape[0])]

        rows = []
        for ci in range(A.shape[0]):
            row = {"ch": names[ci]}
            total = float(np.trapz(A[ci, :], f))
            for (bn, a, b) in self._bands:
                val = self._band_power(f, A[ci, :], a, b)
                row[bn] = val
            if self._use_relative and total > 0:
                for (bn, _, _) in self._bands:
                    row[f"{bn}_rel"] = row[bn] / total
            rows.append(row)

        self.outputs["features"].on_next(rows)
        return {}