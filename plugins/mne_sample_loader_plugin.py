# -*- coding: utf-8 -*-
"""
MNESampleLoader — charge le dataset d'exemple MNE (sample_audvis_raw.fif)

Objectif : fournir un Raw **100% compatible** avec MNE Viewer 2D.

Sorties
  - raw   : mne.io.Raw (FIF)
  - status: str

UI
  - Durée à garder (s) — par défaut 60 s
  - Précharger en mémoire (preload)
  - Bouton "Charger"

Notes
  - Aucune sous-boucle Qt, aucune fenêtre bloquante.
  - Télécharge automatiquement le dataset si absent (via mne.datasets.sample.data_path()).
"""
from typing import Optional
import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QCheckBox
)
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class MNESampleLoader(BasePlugin):
    help = help = { 'gotchas': ['Large files: prefer windowed output.', 'Check montage and units.'],
  'inputs': {},
  'outputs': { 'ch_names': 'List[str]',
               'events': 'array/list',
               'raw': 'mne.Raw',
               'segment': '2D float [ch x samples]',
               'sfreq': 'float (Hz)'},
  'parameters': [ { 'default': '',
                    'desc': 'EDF/BDF/GDF/FIF/... file to load',
                    'name': 'filepath',
                    'type': 'path'},
                  { 'default': None,
                    'desc': 'Channels selection',
                    'name': 'picks',
                    'type': 'list|None'},
                  { 'default': 1.0,
                    'desc': 'Window length for streaming output',
                    'name': 'segment_len',
                    'type': 'float',
                    'unit': 's'}],
  'summary': "MNESampleLoader — charge le dataset d'exemple MNE "
             '(sample_audvis_raw.fif)',
  'usage': 'Place at pipeline start; connect `raw` to MNE ops or `segment` to '
           'streaming ops.'}

    name = "MNESampleLoader"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        self._widget: Optional[QWidget] = None
        self._dur_s = 60.0
        self._preload = True

    def build_widget(self) -> QWidget:
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(6,6,6,6); root.setSpacing(6)

        title = QLabel("MNE Sample Loader (FIF)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        if not HAVE_MNE:
            warn = QLabel("MNE n'est pas installé. Faites `pip install mne`. ")
            warn.setStyleSheet("color:#b00"); warn.setWordWrap(True)
            root.addWidget(warn)
            self._widget = w
            return w

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Durée gardée (s)"))
        self._sp_dur = QDoubleSpinBox(); self._sp_dur.setRange(0.0, 600.0); self._sp_dur.setDecimals(1); self._sp_dur.setSingleStep(1.0); self._sp_dur.setValue(self._dur_s)
        row1.addWidget(self._sp_dur)
        self._chk_preload = QCheckBox("Précharger"); self._chk_preload.setChecked(self._preload)
        row1.addWidget(self._chk_preload)
        root.addLayout(row1)

        row_btn = QHBoxLayout()
        self._btn = QPushButton("Charger")
        self._btn.clicked.connect(self._on_load)
        row_btn.addWidget(self._btn)
        root.addLayout(row_btn)

        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#666")
        root.addWidget(self._lbl)

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def _on_load(self):
        if not HAVE_MNE:
            self._set_status("MNE non dispo"); return
        try:
            self._dur_s = float(self._sp_dur.value())
            self._preload = bool(self._chk_preload.isChecked())

            # 1) chemin du dataset sample
            data_dir = mne.datasets.sample.data_path()
            fif_path = os.path.join(data_dir, "MEG", "sample", "sample_audvis_raw.fif")
            if not os.path.exists(fif_path):
                raise FileNotFoundError("Fichier FIF introuvable après data_path().")

            # 2) lire le Raw FIF (compatible MNE Viewer 2D)
            raw = mne.io.read_raw_fif(fif_path, preload=self._preload, verbose=False)

            # 3) Crop si demandé
            if self._dur_s and self._dur_s > 0:
                try:
                    raw.crop(tmin=0.0, tmax=self._dur_s)
                except TypeError:
                    raw.crop(tmax=self._dur_s)
            # s'assurer que les données sont chargées si le navigateur en a besoin
            if self._preload is False:
                try:
                    raw.load_data()
                except Exception:
                    pass

            # 4) sortie
            self.outputs["raw"].on_next(raw)
            nchan = len(raw.ch_names); sf = float(raw.info.get('sfreq', 0.0))
            dur = raw.n_times / sf if sf else float('nan')
            self._set_status(f"Chargé: {os.path.basename(fif_path)} | Canaux: {nchan} | sf: {sf:.2f} Hz | durée: {dur:.1f} s")
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    # reactive no-op
    def execute(self, *args, **kwargs):
        try:
            if getattr(self, "_lbl", None) is not None and self._lbl.text() == "":
                self._set_status("Prêt. Cliquez ‘Charger’.")
        except Exception:
            pass