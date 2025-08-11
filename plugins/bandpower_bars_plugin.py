# plugins/bandpower_bars_plugin.py

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from core.node_base import BasePlugin


class BandpowerBarsPlugin(BasePlugin):
    """
    Affiche un bar chart des puissances par bande pour le canal choisi.
    Entrées:
      - features: dict { ch_name: {band: value, ...}, ... }
      - band_labels: list[str] (ordre des bandes)
    """
    name = "BandpowerBars"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        self.inputs["features"] = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)

        self._features = None
        self._bands = None

        self._combo = None
        self._status = None
        self._fig = None
        self._ax = None
        self._canvas = None
        self._channels_populated = False

    def build_widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        # Ligne de sélection de canal
        row = QHBoxLayout()
        row.addWidget(QLabel("Channel:"))
        self._combo = QComboBox()
        self._combo.currentIndexChanged.connect(self._update_plot)
        row.addWidget(self._combo, 1)
        lay.addLayout(row)

        # Figure Matplotlib
        self._fig = Figure(figsize=(4, 2.6))
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(self._fig)
        lay.addWidget(self._canvas, 1)

        # Label d'état
        self._status = QLabel("No features")
        self._status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lay.addWidget(self._status)

        return w

    def execute(self, **kwargs):
        features = kwargs.get("features", None)
        bands = kwargs.get("band_labels", None)

        if features is None or bands is None or self._canvas is None:
            if self._status:
                self._status.setText("No features")
            return {}

        self._features = features
        self._bands = list(bands)

        # (Re)peupler la liste des canaux si nécessaire
        ch_names = sorted(self._features.keys())
        if not self._channels_populated or (self._combo.count() != len(ch_names) + 1):
            self._populate_channels(ch_names)

        # MAJ du graphe avec le canal courant
        self._update_plot()
        return {}

    # --------- UI helpers ----------
    def _populate_channels(self, ch_names):
        self._channels_populated = True
        self._combo.blockSignals(True)
        self._combo.clear()
        # Option moyenne globale
        self._combo.addItem("All (mean)")
        for ch in ch_names:
            self._combo.addItem(ch)
        self._combo.blockSignals(False)
        # Sélection par défaut: moyenne
        self._combo.setCurrentIndex(0)

    def _update_plot(self):
        if self._features is None or self._bands is None or self._ax is None:
            return

        current = self._combo.currentText() if self._combo else None
        bands = self._bands

        # Récupère les valeurs
        if current and current != "All (mean)":
            per_band = self._features.get(current, {})
            vals = np.array([float(per_band.get(b, np.nan)) for b in bands], dtype=float)
        else:
            # moyenne sur tous les canaux
            all_vals = []
            for ch, per_band in self._features.items():
                all_vals.append([float(per_band.get(b, np.nan)) for b in bands])
            if len(all_vals) == 0:
                vals = np.zeros(len(bands), dtype=float)
            else:
                vals = np.nanmean(np.array(all_vals, dtype=float), axis=0)

        # Remplace NaN par 0 pour l'affichage
        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)

        # Plot
        self._ax.clear()
        x = np.arange(len(bands))
        self._ax.bar(x, vals)
        self._ax.set_xticks(x)
        self._ax.set_xticklabels(bands)
        self._ax.set_ylabel("Power (a.u.)")
        title = current if current else "Bandpower"
        self._ax.set_title(f"Bandpower — {title}")
        self._fig.tight_layout()
        self._canvas.draw()

        # Statut
        self._status.setText(f"{title}: " + "  |  ".join(f"{b}={v:.3g}" for b, v in zip(bands, vals)))
