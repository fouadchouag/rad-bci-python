# plugins/gdf_reader_plugin.py

import os
import mne
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel
from core.node_base import BasePlugin


class GDFReaderPlugin(BasePlugin):
    help = help = { 'gotchas': ['Uses mne.io.read_raw_gdf — GDF format only.',
               'Large files are fully preloaded into memory.',
               'Check montage and units after loading.'],
  'inputs': {},
  'outputs': { 'raw': 'mne.io.Raw — loaded GDF recording (preloaded)'},
  'parameters': [ { 'default': '',
                    'desc': 'GDF file path (set via Load button)',
                    'name': 'filepath',
                    'type': 'path'}],
  'summary': 'Read GDF EEG files using MNE-Python; emits an MNE Raw object.',
  'usage': 'Place at pipeline start; connect `raw` output to slicer or MNE-compatible nodes.'}

    name = "GDFReader"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)
        self._status_label = None

    def execute(self, **kwargs):
        # Rien à faire ici (lecture via bouton)
        return {}

    def build_widget(self):
        self._status_label = QLabel("No file")
        self._status_label.setStyleSheet("color: black;")  # texte noir

        btn = QPushButton("Load GDF File")
        btn.clicked.connect(self._load_file)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(self._status_label)  # label au-dessus
        lay.addWidget(btn)
        return w

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select GDF file", "", "GDF Files (*.gdf);;All Files (*)"
        )
        if not path:
            return
        try:
            raw = mne.io.read_raw_gdf(path, preload=True, verbose=False)
            fname = os.path.basename(path)

            if self._status_label:
                self._status_label.setText(fname)     # nom court
                self._status_label.setToolTip(path)   # chemin complet (optionnel)

            self.outputs["raw"].on_next(raw)
            print(f"[GDFReader] GDF loaded: {path}")
        except Exception as e:
            if self._status_label:
                self._status_label.setText("Load failed")  # on garde le noir
            print(f"[GDFReader] Failed to read file: {e}")