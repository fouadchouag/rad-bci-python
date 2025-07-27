# plugins/eeg_reader_plugin.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel
from plugins.base import BasePlugin
import mne
import datetime

class EEGReaderPlugin(BasePlugin):
    name = "EEG Reader"
    inputs = []
    outputs = ["raw"]
    language = "Python"

    def __init__(self):
        super().__init__()
        self.raw = None
        self.label = None
        self.button = None

    def build_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)

        self.label = QLabel("No file loaded")
        layout.addWidget(self.label)

        self.button = QPushButton("Load EDF File")
        self.button.clicked.connect(self.load_edf_file)
        layout.addWidget(self.button)

        self.raw = None  # Important pour éviter le bug après suppression/recréation
        return widget

    def load_edf_file(self):
        path, _ = QFileDialog.getOpenFileName(None, "Open EDF File", "", "EDF Files (*.edf)")
        if path:
            try:
                raw = mne.io.read_raw_edf(path, preload=True, verbose=False)

                # 🔧 Corriger les dates non supportées (évite le bug datetime.date)
                if "subject_info" in raw.info and raw.info["subject_info"]:
                    subj_info = raw.info["subject_info"]
                    if isinstance(subj_info.get("birthday", None), datetime.date):
                        raw.info["subject_info"]["birthday"] = None

                self.raw = raw
                filename = path.split("/")[-1]
                self.label.setText(f"Loaded: {filename}")
                print(f"[EEG Reader] File loaded: {path}")
                self.propagate_outputs({"raw": self.raw})
            except Exception as e:
                self.raw = None
                self.label.setText("Error loading EDF")
                print(f"[EEG Reader] Error: {e}")

    def execute(self, inputs):
        # ✅ Empêche d’utiliser un ancien signal si rien n’a été chargé
        if self.label and "No file loaded" in self.label.text():
            self.raw = None
        return {"raw": self.raw}
