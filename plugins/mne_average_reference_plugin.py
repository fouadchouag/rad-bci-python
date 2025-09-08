# plugins/mne_average_reference.py
# -*- coding: utf-8 -*-
"""
MNEAverageReference
- Référence moyenne EEG pour Raw / Epochs (MNE).
- UI pliable + config compatible.
- Entrées / sorties minimales: raw -> raw

Paramètres:
    as_projection: bool   [def: False]
      False  => applique immédiatement la réf. moyenne dans les données
      True   => ajoute un projecteur moyenne-EEG (sans appliquer)
"""

from typing import Any, Dict, Optional, Tuple
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

import mne
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QCheckBox, QFormLayout, QLayout, QSizePolicy
)
from core.collapsible import CollapsibleSection


class MNEAverageReferencePlugin(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'MNEAverageReference',
  'usage': 'Wire upstream data and route downstream.'}

    name = "MNEAverageReference"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True

    # --------------- lifecycle ---------------
    def setup(self):
        # I/O minimal
        self.inputs["raw"] = BehaviorSubject(None)
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # état / config
        self._as_projection: bool = False

        # cache
        self._last_in_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None

        # UI refs
        self._widget: Optional[QWidget] = None
        self._chk_proj: Optional[QCheckBox] = None

        self._emit_config()

    # --------------- config I/O ---------------
    def export_config(self) -> dict:
        return {"as_projection": bool(self._as_projection)}

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        try:
            ap = cfg.get("as_projection", self._as_projection)
            self._as_projection = bool(ap)
        except Exception:
            pass

        # sync UI si ouverte
        try:
            if self._chk_proj is not None:
                self._chk_proj.blockSignals(True)
                self._chk_proj.setChecked(self._as_projection)
                self._chk_proj.blockSignals(False)
        except Exception:
            pass

        self._emit_config()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "as_projection": {"type": "bool", "label": "As projection (do not apply)"},
            },
            "_order": ["as_projection"],
        }

    # --------------- UI ---------------
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        form = QFormLayout(panel)

        self._chk_proj = QCheckBox("As projection (do not apply)")
        self._chk_proj.setChecked(self._as_projection)
        self._chk_proj.stateChanged.connect(self._on_ui_changed)
        form.addRow("", self._chk_proj)

        outer.addWidget(CollapsibleSection("Average reference", panel, collapsed=True))
        self._widget = root
        self._emit_config()
        return root

    def _on_ui_changed(self, _state):
        self._as_projection = bool(self._chk_proj.isChecked()) if self._chk_proj else False
        self._emit_config()
        # relance si une entrée existe déjà
        try:
            r = self.inputs["raw"].value
            if r is not None:
                self.execute(raw=r)
        except Exception:
            pass

    # --------------- helpers ---------------
    def _is_same_request(self, raw_obj: Any, params: Tuple) -> bool:
        return (id(raw_obj) == self._last_in_id) and (params == self._last_params)

    @staticmethod
    def _has_eeg(inst) -> bool:
        try:
            chs = [c for c in inst.info.get("chs", [])]
            return any((getattr(c, "kind", None) == mne.io.constants.FIFF.FIFFV_EEG_CH) for c in chs)
        except Exception:
            # fallback : via pick_types
            try:
                picks = mne.pick_types(inst.info, eeg=True, meg=False)
                return len(picks) > 0
            except Exception:
                return False

    def _apply_avg_ref(self, inst, as_proj: bool):
        """Retourne une copie avec référence moyenne définie."""
        out = inst.copy()
        # API robuste: méthode d'instance si dispo, sinon fonction mne.set_eeg_reference()
        try:
            # Raw / Epochs ont la méthode set_eeg_reference
            out.set_eeg_reference(ref_channels='average', projection=as_proj, verbose=False)
            return out
        except TypeError:
            # ancienne signature -> passer par la fonction
            res = mne.set_eeg_reference(out, ref_channels='average', projection=as_proj, verbose=False)
            # certaines versions renvoient (inst, ref_data)
            if isinstance(res, tuple):
                out = res[0]
            else:
                out = res
            return out

    # --------------- execute ---------------
    def execute(self, in_data: Optional[Dict[str, Any]] = None, **kwargs) -> dict:
        """
        Supporte:
          - execute(in_data={"raw":..., "as_projection": ...})
          - execute(raw=..., as_projection=...)
        Retourne toujours {}.
        """
        try:
            if in_data is None or not isinstance(in_data, dict):
                in_data = {}
            if kwargs:
                in_data.update(kwargs)

            raw = in_data.get("raw", None)
            if raw is None:
                self.outputs["raw"].on_next(None)
                return {}

            as_proj = bool(in_data.get("as_projection", self._as_projection))
            params = (as_proj,)

            if self._is_same_request(raw, params):
                return {}

            # si pas de canaux EEG → pass-through
            try:
                if not self._has_eeg(raw):
                    self._last_in_id = id(raw)
                    self._last_params = ("no_eeg",)
                    self.outputs["raw"].on_next(raw.copy())
                    return {}
            except Exception:
                pass

            out = self._apply_avg_ref(raw, as_proj)

            self._last_in_id = id(raw)
            self._last_params = params
            self.outputs["raw"].on_next(out)
        except Exception as e:
            try:
                print(f"[MNEAverageReference] Error: {e}")
            except Exception:
                pass
            # pass-through en cas d'échec
            self.outputs["raw"].on_next(in_data.get("raw", None))
        return {}