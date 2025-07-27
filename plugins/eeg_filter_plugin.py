# plugins/eeg_filter_plugin.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import Qt
from plugins.base import BasePlugin
import mne

class EEGFilterPlugin(BasePlugin):
    name = "EEG Filter"
    inputs = ["raw"]
    outputs = ["filtered_raw"]
    language = "Python"

    def __init__(self):
        super().__init__()
        self.filtered_raw = None
        self.low_freq = 1.0
        self.high_freq = 40.0

    def build_widget(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(5, 5, 5, 5)

        self.label = QLabel("Filter: 1–40 Hz")
        layout.addWidget(self.label)

        self.low_input = QLineEdit("1.0")
        self.low_input.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.low_input)

        self.high_input = QLineEdit("40.0")
        self.high_input.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.high_input)

        self.button = QPushButton("Apply Filter")
        self.button.clicked.connect(self.apply_filter)
        layout.addWidget(self.button)

        return widget

    def apply_filter(self):
        try:
            self.low_freq = float(self.low_input.text())
            self.high_freq = float(self.high_input.text())
        except ValueError:
            self.label.setText("Invalid filter values")
            print("[EEG Filter] Invalid filter inputs")
            return

        if self._node_item:
            self.on_input_updated()
            self.propagate_outputs({"filtered_raw": self.filtered_raw})

    def execute(self, inputs):
        raw = inputs.get("raw", None)
        if raw is not None:
            try:
                raw_filtered = raw.copy().filter(self.low_freq, self.high_freq, verbose=False)
                self.filtered_raw = raw_filtered
                self.label.setText(f"Filtered: {self.low_freq}-{self.high_freq} Hz")
                print(f"[EEG Filter] Applied filter: {self.low_freq}-{self.high_freq} Hz")
                return {"filtered_raw": self.filtered_raw}
            except Exception as e:
                print(f"[EEG Filter] Error: {e}")
        return {"filtered_raw": None}

    def on_input_updated(self):
        if not self._node_item:
            return

        scene = self._node_item.scene()
        inputs = {}

        for pin in self._node_item.input_pins:
            for item in scene.items():
                if hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                    if item.end_pin == pin:
                        source_node = item.start_pin.parentItem()
                        source_output = item.start_pin.name
                        result = source_node.plugin._last_result or {}
                        inputs[pin.name] = result.get(source_output)

        print(f"[DEBUG] Propagation depuis EEG Filter")
        result = self.execute(inputs)
        self._last_result = result

        for output_pin in self._node_item.output_pins:
            if output_pin.name in result:
                val = result[output_pin.name]
                for item in scene.items():
                    if hasattr(item, "start_pin") and item.start_pin == output_pin:
                        dest_node = item.end_pin.parentItem()
                        if hasattr(dest_node.plugin, "on_input_updated"):
                            dest_node.plugin.on_input_updated()
