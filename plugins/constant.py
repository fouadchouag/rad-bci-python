# plugins/constant_plugin.py
from PyQt5.QtWidgets import QWidget, QLineEdit, QVBoxLayout
from PyQt5.QtCore import Qt
from plugins.base import BasePlugin

class ConstantPlugin(BasePlugin):
    name = "Constant"
    inputs = []
    outputs = ["value"]
    language = "Python"

    def __init__(self):
        super().__init__()
        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.input_field = QLineEdit("1.0")
        self.input_field.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.input_field)
        self.widget.setLayout(layout)

        # Propagation dès qu'on change la valeur
        self.input_field.textChanged.connect(self._on_value_changed)

    def _on_value_changed(self):
        try:
            value = float(self.input_field.text())
        except ValueError:
            value = 0.0
        self._propagate({"value": value})

    def execute(self, inputs):
        try:
            return {"value": float(self.input_field.text())}
        except ValueError:
            return {"value": 0.0}

    def _propagate(self, result):
        print(f"[DEBUG] Propagation depuis {self.name}")
        print(f"Node: {self.name} -> Output: {result}")
        for output_pin in self._node_item.output_pins:
            if output_pin.name in result:
                output_value = result[output_pin.name]
                for item in self._node_item.scene().items():
                    if hasattr(item, "start_pin") and item.start_pin == output_pin:
                        dest_node = item.end_pin.parentItem()
                        if hasattr(dest_node.plugin, "on_input_updated"):
                            dest_node.plugin.on_input_updated()
