# plugins/eeg_visualizer_plugin.py

from PyQt5.QtCore import Qt
import numpy as np
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog, QLabel,
    QListWidget, QListWidgetItem, QCheckBox
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class EEGVisualizerPlugin(BasePlugin):
    name = "EEGVisualizer"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        # État UI
        self.figure = None
        self.axes = None
        self.canvas = None
        self.label = None
        self.channel_list = None
        self.chk_all = None
        self._raw = None           # dernier Raw reçu
        self._channels_populated = False

    def execute(self, **kwargs):
        raw = kwargs.get("raw", None)
        self._raw = raw

        if not (self.canvas and self.axes and self.label):
            return {}

        # Peupler la liste de canaux au premier raw (ou si nb canaux change)
        if raw is not None:
            if (not self._channels_populated) or (
                self.channel_list.count() != len(raw.ch_names)
            ):
                self._populate_channels(raw.ch_names)
                self._channels_populated = True

        # Mettre à jour le tracé selon sélection
        self._update_plot()
        return {}

    # ---------------- UI ----------------
    def build_widget(self):
        # Figure
        self.figure = Figure(figsize=(5, 2))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)

        # Label d’état
        self.label = QLabel("Aucun signal EEG")

        # Liste des canaux + “Tout afficher”
        self.channel_list = QListWidget()
        self.channel_list.setMinimumHeight(80)
        self.channel_list.setMaximumHeight(140)
        self.channel_list.itemChanged.connect(self._on_item_changed)

        self.chk_all = QCheckBox("Afficher tous les canaux")
        self.chk_all.setChecked(True)
        self.chk_all.stateChanged.connect(self._on_toggle_all)

        # Bouton agrandir
        self.button = QPushButton("Agrandir")
        self.button.clicked.connect(self._show_large_plot)

        # Layouts
        channels_bar = QHBoxLayout()
        channels_bar.addWidget(self.chk_all)
        channels_bar.addStretch(1)

        controls = QVBoxLayout()
        controls.addLayout(channels_bar)
        controls.addWidget(self.channel_list)
        controls.addWidget(self.canvas)
        controls.addWidget(self.label)
        controls.addWidget(self.button)

        container = QWidget()
        container.setLayout(controls)
        return container

    def _populate_channels(self, ch_names):
        self.channel_list.blockSignals(True)
        self.channel_list.clear()
        for name in ch_names:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # Par défaut: coché si “Tout afficher”
            it.setCheckState(Qt.Checked if (self.chk_all and self.chk_all.isChecked()) else Qt.Unchecked)
            self.channel_list.addItem(it)
        self.channel_list.blockSignals(False)

    # ------------ Sélection & tracé -------------
    def _selected_indices(self):
        if not self.channel_list:
            return []
        if self.chk_all and self.chk_all.isChecked():
            # Tous les canaux
            return list(range(self.channel_list.count()))
        # Sinon, seulement ceux cochés
        picks = []
        for i in range(self.channel_list.count()):
            if self.channel_list.item(i).checkState() == Qt.Checked:
                picks.append(i)
        return picks

    def _update_plot(self):
        self.axes.clear()

        raw = self._raw
        if raw is None:
            self.label.setText("Aucun signal EEG")
            self.axes.set_title("No Data")
            self.canvas.draw()
            return

        picks = self._selected_indices()
        if len(picks) == 0:
            self.label.setText("Aucun canal sélectionné")
            self.axes.set_title("No Channels")
            self.canvas.draw()
            return

        # Limiter le nombre d’échantillons affichés (perf/visu)
        N = min(1500, raw.n_times)  # ~3s à 500 Hz
        try:
            data, times = raw[picks, :N]  # data: (n_ch, n_times)
        except Exception as e:
            print(f"[EEGVisualizer] Erreur d'accès aux données: {e}")
            self.label.setText("Erreur d'accès aux données")
            self.canvas.draw()
            return

        n_ch = data.shape[0]
        if n_ch == 0:
            self.label.setText("Aucun canal sélectionné")
            self.axes.set_title("No Channels")
            self.canvas.draw()
            return

        # Empilement vertical propre
        # Échelle basée sur l'écart-type global (évite chevauchement)
        std = float(np.nanstd(data)) if np.isfinite(data).any() else 1.0
        spacing = std * 4 if std > 0 else 1.0
        offsets = np.arange(n_ch) * spacing

        for i in range(n_ch):
            self.axes.plot(times, data[i] + offsets[i])

        # Yticks = noms des canaux sélectionnés
        sel_names = [self.channel_list.item(i).text() for i in picks]
        self.axes.set_yticks(offsets)
        self.axes.set_yticklabels(sel_names)
        self.axes.set_xlabel("Temps (s)")
        self.axes.set_title(f"EEG ({n_ch} canal{'x' if n_ch>1 else ''})")

        self.label.setText("Signal EEG reçu")
        self.canvas.draw()

    # ------------- Événements UI ---------------
    def _on_toggle_all(self, state):
        # (Dé)cocher tous les items selon la case "Afficher tous"
        check = Qt.Checked if self.chk_all.isChecked() else Qt.Unchecked
        self.channel_list.blockSignals(True)
        for i in range(self.channel_list.count()):
            self.channel_list.item(i).setCheckState(check)
        self.channel_list.blockSignals(False)
        self._update_plot()

    def _on_item_changed(self, _item):
        # Si un item change manuellement, on désactive "Tout afficher"
        if self.chk_all.isChecked():
            self.chk_all.blockSignals(True)
            self.chk_all.setChecked(False)
            self.chk_all.blockSignals(False)
        self._update_plot()

    # ------------- Fenêtre agrandie -------------
    def _show_large_plot(self):
        raw = self._raw
        dialog = QDialog()
        dialog.setWindowTitle("Aperçu complet EEG")
        layout = QVBoxLayout(dialog)

        fig = Figure(figsize=(10, 4))
        ax = fig.add_subplot(111)

        if raw is not None:
            try:
                picks = self._selected_indices()
                if len(picks) == 0:
                    ax.set_title("Aucun canal sélectionné")
                else:
                    N = min(3000, raw.n_times)  # un peu plus long en vue large
                    data, times = raw[picks, :N]
                    n_ch = data.shape[0]
                    std = float(np.nanstd(data)) if np.isfinite(data).any() else 1.0
                    spacing = std * 4 if std > 0 else 1.0
                    offsets = np.arange(n_ch) * spacing
                    for i in range(n_ch):
                        ax.plot(times, data[i] + offsets[i])
                    sel_names = [self.channel_list.item(i).text() for i in picks]
                    ax.set_yticks(offsets)
                    ax.set_yticklabels(sel_names)
                    ax.set_xlabel("Temps (s)")
                    ax.set_title(f"Aperçu ({n_ch} canal{'x' if n_ch>1 else ''})")
            except Exception as e:
                print(f"[EEGVisualizer] Full plot error: {e}")
                ax.set_title("Erreur lors du tracé")
        else:
            ax.set_title("Pas de données EEG")

        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)
        dialog.setLayout(layout)
        dialog.exec_()
