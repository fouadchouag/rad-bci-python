# plugins/eeg_reader_plugin.py

import os
import mne
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel
from core.node_base import BasePlugin


class EEGReaderPlugin(BasePlugin):
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

    name = "EEGReader"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)
        self._status_label = None

    def execute(self, **kwargs):
        return {}

    def build_widget(self):
        self._status_label = QLabel("No file")
        self._status_label.setStyleSheet("color: black;")  # ← black text

        btn = QPushButton("Load EDF File")
        btn.clicked.connect(self._load_file)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.addWidget(self._status_label)   # label ABOVE the button
        lay.addWidget(btn)
        return w

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(
            None, "Select EDF file", "", "EDF Files (*.edf);;All Files (*)"
        )
        if not path:
            return
        try:
            raw = mne.io.read_raw_edf(path, preload=True, verbose=False)
            fname = os.path.basename(path)

            # keep black text; only update content
            if self._status_label:
                self._status_label.setText(fname)
                self._status_label.setToolTip(path)

            self.outputs["raw"].on_next(raw)
            print(f"[EEGReader] EDF loaded: {path}")
        except Exception as e:
            if self._status_label:
                self._status_label.setText("Load failed")  # keep black color
            print(f"[EEGReader] Failed to read file: {e}")