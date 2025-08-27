# -*- coding: utf-8 -*-
"""
MNE Set Montage (robuste)

Applique un montage standard à un Raw, avec renommage tolérant des canaux pour
maximiser la correspondance (supprime ponctuation/suffixes, alias T9→TP9, etc.).
Utile pour EDF/GDF/LSL sans positions.
"""
from typing import Optional
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox
)
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

import re

class MNERawSetMontage(BasePlugin):
    name = "MNE Set Montage"
    language = "Python"
    category = "Transform Nodes"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        self._widget: Optional[QWidget] = None
        self._montage = "standard_1020"
        self._auto = True
        self._latest_raw = None

    def build_widget(self) -> QWidget:
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(6,6,6,6); root.setSpacing(6)
        title = QLabel("MNE Set Montage (robuste)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        row = QHBoxLayout()
        row.addWidget(QLabel("Montage"))
        self._cmb = QComboBox(); self._cmb.addItems(["standard_1020","standard_1005","biosemi64","easycap-M1"]) ; self._cmb.setCurrentText(self._montage)
        self._cmb.currentTextChanged.connect(self._on_mont)
        row.addWidget(self._cmb, 1)
        self._chk_auto = QCheckBox("Auto"); self._chk_auto.setChecked(self._auto); self._chk_auto.toggled.connect(self._on_auto)
        row.addWidget(self._chk_auto)
        self._btn = QPushButton("Appliquer")
        self._btn.clicked.connect(self._apply)
        row.addWidget(self._btn)
        root.addLayout(row)

        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#666")
        root.addWidget(self._lbl)

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    _re_non_alnum = re.compile(r"[^A-Z0-9]+")
    def _canon(self, n: str) -> str:
        s = str(n).upper().strip()
        for pref in ("EEG ", "EEG_", "EEG-"):
            if s.startswith(pref): s = s[len(pref):]
        for suf in ("-REF","-LE","-RE","-A1","-A2"):
            if s.endswith(suf): s = s[: -len(suf)]
        return self._re_non_alnum.sub("", s)
    def _alias(self, c: str) -> str:
        # c est déjà canonique UPPERCASE sans ponctuation
        return {
            # Lobes temporaux / mastoïdes fréquemment notés ainsi dans BNCI
            "T9":  "TP9",
            "T10": "TP10",
            "A1":  "TP9",
            "A2":  "TP10",
            "M1":  "TP9",
            "M2":  "TP10",
            # rien à changer pour ces z-centrales mais on les laisse au cas où
            "FPZ": "FPZ",
            "FZ":  "FZ",
            "CZ":  "CZ",
            "PZ":  "PZ",
            "OZ":  "OZ",
        }.get(c, c)


    def execute(self, *args, **kwargs):
        try:
            inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)
            def _v(x):
                try: return x.value
                except Exception: return x
            raw = _v(inps.get("raw"))
            self._latest_raw = raw
            if self._auto:
                self._apply()
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    def _on_mont(self, name: str):
        self._montage = name
        if self._auto: self._apply()
    def _on_auto(self, on: bool):
        self._auto = bool(on)

    def _apply(self):
        if not HAVE_MNE:
            self._set_status("MNE non dispo"); return
        raw = self._latest_raw
        if raw is None:
            self._set_status("Aucun Raw"); return
        try:
            mont = mne.channels.make_standard_montage(self._montage)
            canon_to_std = {self._alias(self._canon(n)): n for n in mont.ch_names}
            rename = {}; hits = 0
            for nm in raw.ch_names:
                c = self._alias(self._canon(nm))
                std = canon_to_std.get(c)
                if std and std != nm:
                    rename[nm] = std; hits += 1
            if rename:
                raw.rename_channels(rename)
            mpos = mont.get_positions()['ch_pos']
            sub = {nm: mpos[nm] for nm in raw.ch_names if nm in mpos}
            if not sub:
                self._set_status("Aucune position correspondante trouvée."); return
            dig = mne.channels.make_dig_montage(ch_pos=sub, coord_frame='head')
            try:
                raw.set_montage(dig, match_case=False, on_missing='ignore')
            except TypeError:
                raw.set_montage(dig, match_case=False)
            self.outputs["raw"].on_next(raw)
            self._set_status(f"Montage '{self._montage}' appliqué ({len(sub)} canaux positionnés, renommés={hits}).")
        except Exception as e:
            self._set_status(f"Erreur montage: {e}")
