# plugins/gdf_reader_plugin.py

import os
import mne
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel
from core.node_base import BasePlugin


class GDFReaderPlugin(BasePlugin):
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
  'summary': 'Read EEG files/datasets with MNE-Python; emits Raw or window windows.',
  'usage': 'Place at pipeline start; connect `raw` to MNE ops or `segment` to '
           'streaming ops.'}

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