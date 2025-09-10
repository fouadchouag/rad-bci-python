# plugins/mne_set_montage_plugin.py
# -*- coding: utf-8 -*-
"""
MNE Set Montage (robuste) — avec section Paramètres pliable (fermée par défaut)

Applique un montage standard à un Raw, avec renommage tolérant des canaux pour
maximiser la correspondance (supprime ponctuation/suffixes, alias T9→TP9, etc.).
Utile pour EDF/GDF/LSL sans positions.
"""
from typing import Optional
import re

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSizePolicy, QLayout, QFrame
)
from PyQt5.QtCore import QTimer
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


# ---------------------- Section pliable (anti “cadre gris”) ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Reflow en cascade pour éviter toute zone grise.
    """
    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # démarrage fermé
        self._btn.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding:6px 8px; font-weight:600;"
            " border:1px solid #ccc; border-radius:6px; background:#f7f7f7;"
            "}"
        )
        self._btn.toggled.connect(self._on_toggled)
        root.addWidget(self._btn)

        self._content = QWidget()
        self._content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(10, 8, 10, 8)
        self._lay.setSpacing(6)
        self._lay.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.set_collapsed(True)  # fermé par défaut

    def content_layout(self):
        return self._lay

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)
        self._apply(collapsed)
        self._update_title()
        self._reflow()

    def _on_toggled(self, checked: bool):
        self._apply(collapsed=not checked)
        self._update_title()
        self._reflow()

    def _apply(self, collapsed: bool):
        if collapsed:
            self._content.setMaximumHeight(0)
            self._content.setMinimumHeight(0)
            self._content.setVisible(False)
            self._line.setVisible(False)
        else:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            self._content.setMinimumHeight(0)
            self._line.setVisible(True)

    def _update_title(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._title[2:] if self._title[:2] in ("▼ ", "▶ ") else self._title
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry(); self.updateGeometry()
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._bubble_adjust)

    def _bubble_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout(): w.layout().activate()
                w.adjustSize(); w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


# ---------------------------------- Plugin ---------------------------------- #
class MNERawSetMontage(BasePlugin):
    help = {
        'gotchas': [],
        'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
        'outputs': {'segment': 'processed array'},
        'parameters': [],
        'summary': 'MNE Set Montage (robuste)',
        'usage': 'Wire upstream data and route downstream.'
    }

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

    # -------------------- UI --------------------
    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("MNE Set Montage (robuste)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        # --- Section Paramètres (fermée par défaut) ---
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        # Ligne d’options (dans la section)
        row = QHBoxLayout()
        row.addWidget(QLabel("Montage"))
        self._cmb = QComboBox()
        self._cmb.addItems(["standard_1020", "standard_1005", "biosemi64", "easycap-M1"])
        self._cmb.setCurrentText(self._montage)
        self._cmb.currentTextChanged.connect(self._on_mont)
        row.addWidget(self._cmb, 1)

        self._chk_auto = QCheckBox("Auto")
        self._chk_auto.setChecked(self._auto)
        self._chk_auto.toggled.connect(self._on_auto)
        row.addWidget(self._chk_auto)

        self._btn = QPushButton("Appliquer")
        self._btn.clicked.connect(self._apply)
        row.addWidget(self._btn)

        box = QWidget()
        box_l = QVBoxLayout(box)
        box_l.setContentsMargins(0, 0, 0, 0)
        box_l.setSpacing(6)
        box_l.addLayout(row)
        sec.content_layout().addWidget(box)

        # Statut (toujours visible, hors section)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl)

        # Contraintes anti “cadre gris”
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        self._widget = w
        return w

    # -------------------- Helpers --------------------
    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    _re_non_alnum = re.compile(r"[^A-Z0-9]+")
    def _canon(self, n: str) -> str:
        s = str(n).upper().strip()
        for pref in ("EEG ", "EEG_", "EEG-"):
            if s.startswith(pref):
                s = s[len(pref):]
        for suf in ("-REF", "-LE", "-RE", "-A1", "-A2"):
            if s.endswith(suf):
                s = s[: -len(suf)]
        return self._re_non_alnum.sub("", s)

    def _alias(self, c: str) -> str:
        # c est déjà canonique UPPERCASE sans ponctuation
        return {
            "T9":  "TP9",
            "T10": "TP10",
            "A1":  "TP9",
            "A2":  "TP10",
            "M1":  "TP9",
            "M2":  "TP10",
            "FPZ": "FPZ",
            "FZ":  "FZ",
            "CZ":  "CZ",
            "PZ":  "PZ",
            "OZ":  "OZ",
        }.get(c, c)

    # -------------------- Reactive --------------------
    def execute(self, *args, **kwargs):
        try:
            inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)
            def _v(x):
                try:
                    return x.value
                except Exception:
                    return x
            raw = _v(inps.get("raw"))
            self._latest_raw = raw
            if self._auto:
                self._apply()
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    def _on_mont(self, name: str):
        self._montage = name
        if self._auto:
            self._apply()

    def _on_auto(self, on: bool):
        self._auto = bool(on)

    # -------------------- Core --------------------
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
