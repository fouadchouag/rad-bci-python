# plugins/eeg_filter_plugin.py

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import Qt
import mne


class EEGFilterPlugin(BasePlugin):
    name = "EEG Filter"
    language = "Python"
    category = "Processing Nodes"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.outputs["filtered_raw"] = BehaviorSubject(None)
        self.low_freq = 1.0
        self.high_freq = 40.0

    def build_widget(self):
        self.label = QLabel("Filter: 1–40 Hz")

        self.low_input = QLineEdit("1.0")
        self.low_input.setAlignment(Qt.AlignCenter)

        self.high_input = QLineEdit("40.0")
        self.high_input.setAlignment(Qt.AlignCenter)

        self.button = QPushButton("Apply Filter")
        self.button.clicked.connect(self._apply_filter)

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.low_input)
        layout.addWidget(self.high_input)
        layout.addWidget(self.button)

        container = QWidget()
        container.setLayout(layout)
        return container

    def _apply_filter(self):
        try:
            self.low_freq = float(self.low_input.text())
            self.high_freq = float(self.high_input.text())
        except ValueError:
            self.label.setText("Invalid filter values")
            print("[EEG Filter] Invalid input")
            return

        # Redéclenche l’exécution avec les valeurs actuelles
        current_raw = self._values.get("raw")
        self.set_input("raw", current_raw)

    def execute(self, **kwargs):
        raw = kwargs.get("raw", None)

        if raw is not None:
            try:
                raw_filtered = raw.copy().filter(
                    l_freq=self.low_freq,
                    h_freq=self.high_freq,
                    verbose=False
                )
                self.label.setText(f"Filtered: {self.low_freq}-{self.high_freq} Hz")
                print(f"[EEG Filter] Applied filter: {self.low_freq}-{self.high_freq} Hz")
                return {"filtered_raw": raw_filtered}
            except Exception as e:
                print(f"[EEG Filter] Error: {e}")

        return {"filtered_raw": None}
