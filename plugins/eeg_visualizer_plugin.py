# plugins/eeg_visualizer_plugin.py

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from plugins.base import BasePlugin
import numpy as np

class EEGVisualizerPlugin(BasePlugin):
    name = "EEG Visualizer"
    inputs = ["raw"]
    outputs = []
    language = "Python"

    def __init__(self):
        super().__init__()
        self.raw = None

        self.widget = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)

        self.label = QLabel("Waiting for data...")
        layout.addWidget(self.label)

        self.canvas = FigureCanvas(Figure(figsize=(3, 2)))
        layout.addWidget(self.canvas)
        self.ax = self.canvas.figure.add_subplot(111)

        self.button = QPushButton("Agrandir")
        self.button.clicked.connect(self._open_interactive_plot)
        layout.addWidget(self.button)

        self.widget.setLayout(layout)

    def _open_interactive_plot(self):
        if self.raw:
            self.raw.plot(show=True, block=False)  # ✅ Corrigé : plus d’axes=

    def execute(self, inputs):
        self.raw = inputs.get("raw", None)
        self.ax.clear()

        if self.raw:
            self.label.setText("Signal EEG reçu")
            try:
                data, times = self.raw[:, :500]  # 500 premiers points
                if data.shape[0] > 0:
                    signal = data[0]  # Premier canal
                    self.ax.plot(times, signal)
                    self.ax.set_title("Canal 0")
                    self.canvas.draw()
            except Exception as e:
                print(f"[EEG Visualizer] Erreur d'affichage : {e}")
                self.label.setText("Erreur d'affichage")
        else:
            self.label.setText("Aucun signal EEG")

        return {}
