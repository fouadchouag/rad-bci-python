from PyQt5.QtWidgets import QWidget, QLineEdit, QVBoxLayout
from PyQt5.QtCore import Qt
from plugins.base import BasePlugin
from gui.main_window import MainWindow

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

        self.input_field.textChanged.connect(self._on_value_changed)

    def _on_value_changed(self):
        win = MainWindow.instance()
        if win:
            win._auto_run_graph()

    def execute(self, inputs):
        try:
            value = float(self.input_field.text())
        except ValueError:
            value = 0.0
        return {"value": value}
