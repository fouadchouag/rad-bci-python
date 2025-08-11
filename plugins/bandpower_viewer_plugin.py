# plugins/bandpower_viewer_plugin.py

from PyQt5.QtCore import Qt

from typing import Dict, List
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QLabel
)
from core.node_base import BasePlugin


class BandpowerViewerPlugin(BasePlugin):
    """
    Affiche un tableau des puissances par bande.
    Entrées:
      - features: dict {ch_name: {band: value, ...}, ...}
      - band_labels: list[str]
    Widget: QTableWidget (colonnes = bandes, lignes = canaux)
    """
    name = "BandpowerViewer"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        self.inputs["features"] = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)

        self._table = None
        self._status = None
        self._last_bands: List[str] = []
        self._row_index: Dict[str, int] = {}

    def execute(self, **kwargs):
        features = kwargs.get("features", None)
        bands = kwargs.get("band_labels", self._last_bands or None)

        if self._table is None:
            return {}

        if features is None or bands is None:
            self._status.setText("No features")
            return {}

        # Construire / ajuster la table si les bandes ont changé
        bands = list(bands)
        if bands != self._last_bands:
            self._setup_table_columns(bands)
            self._last_bands = bands

        # Remplir la table (1 ligne par canal)
        ch_names = sorted(features.keys())
        self._table.setRowCount(len(ch_names))
        self._row_index = {ch: i for i, ch in enumerate(ch_names)}

        for i, ch in enumerate(ch_names):
            # Colonne 0: nom de canal
            item = QTableWidgetItem(ch)
            item.setFlags(item.flags())  # lecture seule par défaut
            self._table.setItem(i, 0, item)

            # Colonnes suivantes: valeurs par bande
            per_band = features.get(ch, {})
            for j, b in enumerate(self._last_bands, start=1):
                val = per_band.get(b, float("nan"))
                cell = QTableWidgetItem(f"{val:.6g}")
                cell.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                self._table.setItem(i, j, cell)

        self._table.resizeColumnsToContents()
        self._status.setText(f"{len(ch_names)} channels | bands: {', '.join(self._last_bands)}")
        return {}

    def build_widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self._status = QLabel("No features")
        self._table = QTableWidget(0, 1)
        self._table.setHorizontalHeaderLabels(["Channel"])

        lay.addWidget(self._status)
        lay.addWidget(self._table)
        return w

    # ---------- helpers ----------
    def _setup_table_columns(self, bands: List[str]):
        cols = 1 + len(bands)
        self._table.setColumnCount(cols)
        headers = ["Channel"] + bands
        self._table.setHorizontalHeaderLabels(headers)
