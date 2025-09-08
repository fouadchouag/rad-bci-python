# plugins/bandpower_inspector_plugin.py
import numpy as np
from typing import Dict, List, Optional, Any

from rx.subject import BehaviorSubject
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QCheckBox,
    QStackedLayout, QTableWidget, QTableWidgetItem, QAbstractItemView,
    QToolButton, QDialog, QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.node_base import BasePlugin


# ---------- Dialog scrollable + recherche ----------
class ChannelPickerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], channels: List[str], current: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("Select Channel")
        self.setModal(True)
        self.resize(360, 520)

        lay = QVBoxLayout(self)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Rechercher un canal…")
        lay.addWidget(self._search)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        lay.addWidget(self._list, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        lay.addWidget(btns)

        # All en premier
        self._all_labels = ["All"] + channels
        for ch in self._all_labels:
            QListWidgetItem(ch, self._list)

        # selection courante
        cur = current or "All"
        items = self._list.findItems(cur, Qt.MatchExactly)
        if items:
            self._list.setCurrentItem(items[0])

        # connexions
        self._search.textChanged.connect(self._on_filter)
        self._list.itemDoubleClicked.connect(lambda _it: self.accept())
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

    def _on_filter(self, text: str):
        t = text.strip().lower()
        for i in range(self._list.count()):
            it = self._list.item(i)
            it.setHidden(False if not t else (t not in it.text().lower()))

    def selected_channel(self) -> str:
        it = self._list.currentItem()
        return it.text() if it else "All"


class BandpowerInspectorPlugin(BasePlugin):
    help = help = { 'gotchas': ['Use adequate window length for low frequencies.'],
  'inputs': {'segment': '2D float [ch x samples] or epochs', 'sfreq': 'float (Hz)'},
  'outputs': { 'features': 'array/dict',
               'freqs': 'optional freqs',
               'psd': 'optional PSD'},
  'parameters': [ { 'default': 1.0,
                    'desc': 'Lower frequency',
                    'name': 'fmin',
                    'type': 'float',
                    'unit': 'Hz'},
                  { 'default': 40.0,
                    'desc': 'Upper frequency',
                    'name': 'fmax',
                    'type': 'float',
                    'unit': 'Hz'}],
  'summary': 'Inspecteur bandpower avec:',
  'usage': 'Connect windowed or epoched data; feed features to ML nodes.'}

    """
    Inspecteur bandpower avec:
      - bouton 'Pick channel' (recherche, All)
      - clic sur la table = filtre ; re-clic quand une seule ligne = retour All
      - vue Table/Bars + Relative %
    """
    name = "BandpowerInspector"
    language = "Python"
    category = "Output Nodes"

    # pliable comme les autres nodes
    start_hidden = True
    supports_collapse = True

    # -------------------- Reactive setup --------------------
    def setup(self):
        self.inputs["features"] = BehaviorSubject(None)
        self.inputs["band_labels"] = BehaviorSubject(None)

        self._features: Optional[Dict[str, Dict[str, float]]] = None
        self._bands: Optional[List[str]] = None

        self._last_bands: List[str] = []
        self._current_channels: List[str] = []
        self._current_channels_set = set()
        self._selected_channel: Optional[str] = None  # None => All

        # UI refs
        self._status: Optional[QLabel] = None
        self._btn_pick: Optional[QToolButton] = None
        self._combo_view: Optional[QComboBox] = None
        self._chk_relative: Optional[QCheckBox] = None
        self._stack: Optional[QStackedLayout] = None

        # Table
        self._table: Optional[QTableWidget] = None
        self._row_index: Dict[str, int] = {}

        # Figure
        self._fig: Optional[Figure] = None
        self._ax = None
        self._canvas: Optional[FigureCanvas] = None

    # -------------------- GUI --------------------
    def build_widget(self):
        w = QWidget()
        w.setMinimumSize(460, 320)
        w.setProperty("start_hidden", True)
        w.setProperty("collapsible", True)

        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Channel:"))

        self._btn_pick = QToolButton()
        self._btn_pick.setText("Pick channel")
        self._btn_pick.setToolTip("Choisir un canal (ou All) avec recherche.")
        self._btn_pick.clicked.connect(self._open_picker_dialog)
        toolbar.addWidget(self._btn_pick)

        self._combo_view = QComboBox()
        self._combo_view.addItems(["Table", "Bars"])
        self._combo_view.activated[str].connect(lambda _t: self._switch_view())
        toolbar.addWidget(QLabel("View:"))
        toolbar.addWidget(self._combo_view)

        self._chk_relative = QCheckBox("Relative %")
        self._chk_relative.setToolTip(
            "Affiche chaque bande en pourcentage de la somme des bandes du canal affiché."
        )
        self._chk_relative.stateChanged.connect(lambda _s: self._update_view())
        toolbar.addWidget(self._chk_relative)

        toolbar.addStretch(1)
        root.addLayout(toolbar)

        # Statut
        self._status = QLabel("No features")
        self._status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self._status)

        # Stack (Table/Bars)
        self._stack = QStackedLayout()
        root.addLayout(self._stack, 1)

        # Table
        table_host = QWidget()
        v = QVBoxLayout(table_host)
        v.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, 1)
        self._table.setHorizontalHeaderLabels(["Channel"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.cellClicked.connect(self._on_table_cell_clicked)  # toggle filtre/All
        v.addWidget(self._table)
        self._stack.addWidget(table_host)

        # Bars
        bars_host = QWidget()
        vb = QVBoxLayout(bars_host)
        vb.setContentsMargins(0, 0, 0, 0)
        self._fig = Figure(figsize=(4, 2.6))
        self._ax = self._fig.add_subplot(111)
        self._canvas = FigureCanvas(self._fig)
        vb.addWidget(self._canvas, 1)
        self._stack.addWidget(bars_host)

        self._stack.setCurrentIndex(0)
        self._set_controls_enabled(False)
        return w

    # -------------------- Reactive exec --------------------
    def execute(self, **kwargs):
        if "features" in kwargs and kwargs["features"] is not None:
            self._features = self._normalize_features(kwargs["features"])
        if "band_labels" in kwargs and kwargs["band_labels"] is not None:
            self._bands = list(kwargs["band_labels"])

        if self._bands is None and self._features is not None:
            self._bands = self._infer_bands_from_features(self._features)

        if self._features is None or self._bands is None:
            self._clear_table()
            self._clear_plot()
            self._set_controls_enabled(False)
            if self._status:
                self._status.setText("No features")
            return {}

        ch_set = set(self._features.keys())
        if ch_set != self._current_channels_set:
            ch_names = sorted(ch_set)
            self._current_channels = ch_names
            self._current_channels_set = ch_set
            if self._selected_channel and self._selected_channel not in ch_set:
                self._selected_channel = None  # All

        if self._bands != self._last_bands:
            self._setup_table_columns(self._bands)
            self._last_bands = list(self._bands)

        self._set_controls_enabled(True)
        self._update_view()

        if self._status:
            sel = self._selected_channel or "All"
            self._status.setText(
                f"{len(self._current_channels)} channels | bands: {', '.join(self._bands)} | selected: {sel}"
            )
        return {}

    # -------------------- Normalisations & inférence --------------------
    def _normalize_features(self, feat: Any) -> Dict[str, Dict[str, float]]:
        if isinstance(feat, dict) and feat and isinstance(next(iter(feat.values())), dict):
            return {str(ch): {str(b): float(v) for b, v in per.items()} for ch, per in feat.items()}
        if isinstance(feat, (list, tuple)) and len(feat) > 0 and isinstance(feat[0], dict):
            out = {}
            for d in feat:
                ch = d.get("channel") or d.get("ch") or d.get("name")
                if not ch:
                    continue
                per = {k: float(v) for k, v in d.items() if k not in ("channel", "ch", "name")}
                out[str(ch)] = per
            if out:
                return out
        return {}

    def _infer_bands_from_features(self, features: Dict[str, Dict[str, float]]) -> List[str]:
        band_set = set()
        for per in features.values():
            band_set.update(map(str, per.keys()))
        if not band_set:
            return []
        preferred = ["delta", "theta", "alpha", "beta", "gamma"]
        ordered = [b for b in preferred if b in band_set]
        rest = sorted(b for b in band_set if b not in preferred)
        return ordered + rest

    # -------------------- Sélection / Toggle --------------------
    def _on_table_cell_clicked(self, row: int, _col: int):
        if not self._table:
            return
        ch_item = self._table.item(row, 0)
        if not ch_item:
            return
        clicked = ch_item.text()

        # Si une seule ligne est affichée ET qu'on reclique dessus -> All
        if self._table.rowCount() == 1 and self._selected_channel == clicked:
            self._selected_channel = None  # All
        else:
            self._selected_channel = clicked  # filtre sur ce canal

        self._update_view()

    def _open_picker_dialog(self):
        channels = self._current_channels or (sorted(self._features.keys()) if self._features else [])
        cur = self._selected_channel or "All"
        dlg = ChannelPickerDialog(None, channels, cur)
        if dlg.exec_() == QDialog.Accepted:
            self._set_selected_channel(dlg.selected_channel())

    def _set_selected_channel(self, text: str):
        self._selected_channel = None if (not text or text in ("All", "All (mean)")) else text
        self._update_view()

    # -------------------- Controls & View --------------------
    def _set_controls_enabled(self, ok: bool):
        for w in (self._btn_pick, self._combo_view, self._chk_relative):
            if w is not None:
                w.setEnabled(ok)

    def _switch_view(self):
        if not self._stack or not self._combo_view:
            return
        self._stack.setCurrentIndex(0 if self._combo_view.currentText() == "Table" else 1)
        self._update_view()

    def _update_view(self):
        if self._features is None or self._bands is None:
            return
        if not self._combo_view:
            return
        if self._combo_view.currentText() == "Table":
            self._update_table()
        else:
            self._update_plot()

    # -------------------- Table --------------------
    def _setup_table_columns(self, bands: List[str]):
        if not self._table:
            return
        self._table.setColumnCount(1 + len(bands))
        self._table.setHorizontalHeaderLabels(["Channel"] + bands)

    def _update_table(self):
        if self._table is None or self._features is None or self._bands is None:
            return

        # All -> tous ; sinon -> canal unique
        all_channels = sorted(self._features.keys())
        if self._selected_channel and self._selected_channel in self._features:
            display_channels = [self._selected_channel]
        else:
            display_channels = all_channels

        self._table.setRowCount(len(display_channels))
        self._row_index = {ch: i for i, ch in enumerate(display_channels)}

        relative = bool(self._chk_relative and self._chk_relative.isChecked())

        for i, ch in enumerate(display_channels):
            item = QTableWidgetItem(ch)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self._table.setItem(i, 0, item)

            vals = self._compute_values_for_channel(ch, self._bands, relative)
            for j, val in enumerate(vals, start=1):
                cell = QTableWidgetItem(f"{val:.6g}")
                cell.setTextAlignment(int(Qt.AlignRight | Qt.AlignVCenter))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self._table.setItem(i, j, cell)

        self._table.resizeColumnsToContents()

        # sélectionner la ligne si vue filtrée
        if len(display_channels) == 1:
            self._table.selectRow(0)

    def _clear_table(self):
        if self._table:
            self._table.clearContents()
            self._table.setRowCount(0)

    # -------------------- Bars --------------------
    def _update_plot(self):
        if self._ax is None or self._canvas is None or self._features is None or self._bands is None:
            return

        current = self._selected_channel or "All"
        relative = bool(self._chk_relative and self._chk_relative.isChecked())
        vals = self._compute_values_for_channel(current, self._bands, relative)

        self._ax.clear()
        x = np.arange(len(self._bands))
        self._ax.bar(x, vals)
        self._ax.set_xticks(x)
        self._ax.set_xticklabels(self._bands)
        self._ax.set_ylabel("% of total" if relative else "Power (a.u.)")
        self._ax.set_title(f"Bandpower — {current}")
        if self._fig:
            self._fig.tight_layout()
        self._canvas.draw()

    def _clear_plot(self):
        if self._ax and self._canvas:
            self._ax.clear()
            self._ax.set_title("No data")
            if self._fig:
                self._fig.tight_layout()
            self._canvas.draw()

    # -------------------- Calculs --------------------
    def _compute_values_for_channel(self, channel: str, bands: List[str], relative: bool) -> np.ndarray:
        if self._features is None:
            return np.zeros(len(bands), dtype=float)

        # All -> moyenne ; canal -> valeurs du canal
        if not channel or channel in ("All", "All (mean)"):
            all_vals = []
            for _, per_band in self._features.items():
                all_vals.append([float(per_band.get(b, np.nan)) for b in bands])
            vals = np.nanmean(np.array(all_vals, dtype=float), axis=0) if len(all_vals) else np.zeros(len(bands))
        else:
            per_band = self._features.get(channel, {})
            vals = np.array([float(per_band.get(b, np.nan)) for b in bands], dtype=float)

        vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)

        if relative:
            s = float(np.sum(vals))
            vals = (vals / s) * 100.0 if s > 0 else np.zeros_like(vals)

        return vals