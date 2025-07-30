# plugins/eeg_visualizer_plugin.py

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QPushButton, QDialog, QLabel
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class EEGVisualizerPlugin(BasePlugin):
    name = "EEGVisualizer"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)

    def execute(self, **kwargs):
        raw = kwargs.get("raw", None)

        if not hasattr(self, "canvas") or not hasattr(self, "axes") or not hasattr(self, "label"):
            return {}

        self.axes.clear()
        if raw is not None:
            self.label.setText("Signal EEG reçu")
            try:
                data, times = raw[:, :500]  # ✅ Utilise la même logique que ta version stable
                if data.shape[0] > 0:
                    signal = data[0]
                    self.axes.plot(times, signal)
                    self.axes.set_title("Canal 0")
                    self.canvas.draw()
            except Exception as e:
                print(f"[EEGVisualizer] Erreur d'affichage : {e}")
                self.label.setText("Erreur d'affichage")
        else:
            self.label.setText("Aucun signal EEG")
            self.axes.set_title("No Data")
            self.canvas.draw()

        return {}

    def build_widget(self):
        self.figure = Figure(figsize=(5, 2))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)

        self.label = QLabel("Aucun signal EEG")
        layout.addWidget(self.label)

        self.button = QPushButton("Agrandir")
        self.button.clicked.connect(self._show_large_plot)
        layout.addWidget(self.button)

        container = QWidget()
        container.setLayout(layout)
        return container

    def _show_large_plot(self):
        raw = self._values.get("raw")
        dialog = QDialog()
        dialog.setWindowTitle("Aperçu complet EEG")
        layout = QVBoxLayout(dialog)

        fig = Figure(figsize=(10, 4))
        ax = fig.add_subplot(111)

        if raw is not None:
            try:
                data, times = raw[:, :1000]
                if data.shape[0] > 0:
                    ax.plot(times, data[0])
                    ax.set_title("Aperçu complet - Canal 0")
            except Exception as e:
                print(f"[EEGVisualizer] Full plot error: {e}")
                ax.set_title("Erreur lors du tracé")
        else:
            ax.set_title("Pas de données EEG")

        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)
        dialog.setLayout(layout)
        dialog.exec_()
