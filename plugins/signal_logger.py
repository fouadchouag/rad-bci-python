from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout
from plugins.base import BasePlugin

class SignalLoggerPlugin(BasePlugin):
    name = "Signal Logger"
    inputs = ["input"]
    outputs = []
    language = "Python"

    def __init__(self):
        super().__init__()
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.label = QLabel("No input")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.widget.setLayout(layout)

    def execute(self, inputs):
        val = inputs.get("input", "")
        self.label.setText(f"Signal received:\n{val}")
        print(f"📥 Logged value: {val}")
        return {"logged": val}

    def on_input_updated(self):
        if not self._node_item:
            return

        scene = self._node_item.scene()
        inputs = {}

        for pin in self._node_item.input_pins:  # ✅ CORRIGÉ ICI
            for item in scene.items():
                if hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                    if item.end_pin == pin:
                        source_node = item.start_pin.parentItem()
                        source_output = item.start_pin.name
                        result = source_node.plugin._last_result or {}
                        inputs[pin.name] = result.get(source_output)

        print(f"[DEBUG] Propagation depuis Signal Logger")
        result = self.execute(inputs)
        self._last_result = result
