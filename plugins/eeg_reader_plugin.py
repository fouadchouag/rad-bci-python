from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QFileDialog, QLabel
from plugins.base import BasePlugin
import mne

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

        return widget

    def load_edf_file(self):
        path, _ = QFileDialog.getOpenFileName(None, "Open EDF File", "", "EDF Files (*.edf)")
        if path:
            try:
                self.raw = mne.io.read_raw_edf(path, preload=True, verbose=False)
                filename = path.split("/")[-1]
                self.label.setText(f"Loaded: {filename}")
                print(f"[EEG Reader] File loaded: {path}")
                self.propagate_outputs({"raw": self.raw})
            except Exception as e:
                self.label.setText("Error loading EDF")
                print(f"[EEG Reader] Error: {e}")

    def execute(self, inputs):
        return {"raw": self.raw}
