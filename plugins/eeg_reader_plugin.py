# plugins/eeg_reader_plugin.py

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QPushButton, QWidget, QVBoxLayout, QFileDialog
import mne

class EEGReaderPlugin(BasePlugin):
    name = "EEGReader"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)

    def execute(self, **kwargs):
        # Ne rien faire ici, l'exécution est déclenchée manuellement via le bouton
        return {}

    def build_widget(self):
        btn = QPushButton("Load EDF File")
        btn.clicked.connect(self._load_file)

        widget = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(btn)
        widget.setLayout(layout)
        return widget

    def _load_file(self):
        path, _ = QFileDialog.getOpenFileName(None, "Select EDF file", "", "EDF Files (*.edf)")
        if path:
            try:
                raw = mne.io.read_raw_edf(path, preload=True, verbose=False)
                print(f"[EEGReader] EDF loaded: {path}")
                self.outputs["raw"].on_next(raw)
            except Exception as e:
                print(f"[EEGReader] Failed to read file: {e}")
