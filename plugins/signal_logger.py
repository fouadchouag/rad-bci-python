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
        value = inputs.get("input", "")
        self.label.setText(f"Signal received:\n{value}")
        return {}
