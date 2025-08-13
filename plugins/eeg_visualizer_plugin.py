# plugins/eeg_visualizer_plugin.py

from PyQt5.QtCore import Qt
import numpy as np
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog, QLabel,
    QListWidget, QListWidgetItem, QCheckBox, QToolButton, QLayout, QSizePolicy
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class _CollapsibleSection(QWidget):
    """Section repliable qui retire vraiment la hauteur quand fermée."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0)
        self._wrap_l.setSpacing(0)
        self._content = content or QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._wrap_l.addWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed)
        self._on_toggled(self._btn.isChecked())

    def _poke_ancestors(self):
        w = self
        while w is not None:
            if w.layout():
                w.layout().invalidate()
            w.adjustSize()
            w.updateGeometry()
            w = w.parentWidget()

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)

        if expanded:
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self._wrap.setMaximumHeight(16777215)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            header_h = self._btn.sizeHint().height() + 6
            self._wrap.setMaximumHeight(0)
            self._wrap.setMinimumHeight(0)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMaximumHeight(header_h)
            self.setMinimumHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self._poke_ancestors()


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

        if not (self.canvas and self.axes):
            return {}

        # Peupler/repeupler la liste de canaux au premier raw ou si nb canaux change
        if raw is not None:
            try:
                ch_names = list(raw.ch_names)
            except Exception:
                ch_names = []
            if (not self._channels_populated) or (self.channel_list.count() != len(ch_names)):
                self._populate_channels(ch_names)
                self._channels_populated = True

        # Mettre à jour le tracé selon sélection
        self._update_plot()
        return {}

    # ---------------- UI ----------------
    def build_widget(self):
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

        # Figure principale (toujours visible)
        self.figure = Figure(figsize=(5, 2))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        outer.addWidget(self.canvas, 1)

        # --- Panneau repliable: contrôles + statut ---
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(6)

        # Liste des canaux + “Tout afficher”
        self.channel_list = QListWidget()
        self.channel_list.setMinimumHeight(80)
        self.channel_list.setMaximumHeight(140)
        self.channel_list.itemChanged.connect(self._on_item_changed)

        self.chk_all = QCheckBox("Afficher tous les canaux")
        self.chk_all.setChecked(True)
        self.chk_all.stateChanged.connect(self._on_toggle_all)

        channels_bar = QHBoxLayout()
        channels_bar.addWidget(self.chk_all)
        channels_bar.addStretch(1)
        pv.addLayout(channels_bar)
        pv.addWidget(self.channel_list)

        # Label d’état (rangé dans la section)
        self.label = QLabel("Aucun signal EEG")
        pv.addWidget(self.label)

        # Bouton agrandir
        self.button = QPushButton("Agrandir")
        self.button.clicked.connect(self._show_large_plot)
        pv.addWidget(self.button)

        # Section repliable (fermée par défaut)
        sec = _CollapsibleSection("Paramètres & Contrôles", panel, collapsed=True)
        outer.addWidget(sec)

        return root

    def _populate_channels(self, ch_names):
        if self.channel_list is None:
            return
        self.channel_list.blockSignals(True)
        self.channel_list.clear()
        check_all = (self.chk_all and self.chk_all.isChecked())
        for name in ch_names:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if check_all else Qt.Unchecked)
            self.channel_list.addItem(it)
        self.channel_list.blockSignals(False)

    # ------------ Sélection & tracé -------------
    def _selected_indices(self):
        if not self.channel_list:
            return []
        if self.chk_all and self.chk_all.isChecked():
            return list(range(self.channel_list.count()))
        picks = []
        for i in range(self.channel_list.count()):
            if self.channel_list.item(i).checkState() == Qt.Checked:
                picks.append(i)
        return picks

    def _update_plot(self):
        self.axes.clear()

        raw = self._raw
        if raw is None:
            if self.label:
                self.label.setText("Aucun signal EEG")
            self.axes.set_title("No Data")
            self.axes.set_xlabel("Temps (s)")
            self.canvas.draw()
            return

        picks = self._selected_indices()
        if len(picks) == 0:
            if self.label:
                self.label.setText("Aucun canal sélectionné")
            self.axes.set_title("No Channels")
            self.axes.set_xlabel("Temps (s)")
            self.canvas.draw()
            return

        try:
            n_times = int(getattr(raw, "n_times", 0))
        except Exception:
            n_times = 0
        N = min(1500, n_times) if n_times and n_times > 0 else 1500

        try:
            data, times = raw[picks, :N]  # data: (n_ch, n_times)
        except Exception as e:
            print(f"[EEGVisualizer] Erreur d'accès aux données: {e}")
            if self.label:
                self.label.setText("Erreur d'accès aux données")
            self.axes.set_title("Data error")
            self.canvas.draw()
            return

        n_ch = int(data.shape[0]) if data is not None else 0
        if n_ch == 0:
            if self.label:
                self.label.setText("Aucun canal sélectionné")
            self.axes.set_title("No Channels")
            self.canvas.draw()
            return

        # Empilement vertical propre
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
        self.axes.set_title(f"EEG ({n_ch} canal{'x' if n_ch > 1 else ''})")

        if self.label:
            self.label.setText("Signal EEG reçu")
        self.canvas.draw()

    # ------------- Événements UI ---------------
    def _on_toggle_all(self, _state):
        if not self.channel_list:
            return
        check = Qt.Checked if (self.chk_all and self.chk_all.isChecked()) else Qt.Unchecked
        self.channel_list.blockSignals(True)
        for i in range(self.channel_list.count()):
            self.channel_list.item(i).setCheckState(check)
        self.channel_list.blockSignals(False)
        self._update_plot()

    def _on_item_changed(self, _item):
        # Si un item change manuellement, on désactive "Tout afficher"
        if self.chk_all and self.chk_all.isChecked():
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
                    try:
                        n_times = int(getattr(raw, "n_times", 0))
                    except Exception:
                        n_times = 0
                    N = min(3000, n_times) if n_times and n_times > 0 else 3000
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
