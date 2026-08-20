# -*- coding: utf-8 -*-
"""
EvokedViewer (single-channel capable)
- Entrées:
    evoked : mne.Evoked ou list[mne.Evoked]
    channel: (OPTIONNEL) str (nom) ou int (index) -> force la sélection
- UI:
    - Checkbox "Single channel"
    - Combo des ch_names auto-remplie
    - Bouton "Agrandir…"
"""
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QComboBox, QCheckBox, QDialog, QLabel
)
from PyQt5.QtCore import Qt

from core.collapsible import CollapsibleSection
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class _BigDialog(QDialog):
   

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evoked – Agrandi")
        self.resize(1000, 600)
        self.fig = Figure(figsize=(10, 5), tight_layout=True)
        self.canvas = FigureCanvas(self.fig)
        lay = QVBoxLayout(self)
        lay.addWidget(self.canvas)


class EvokedViewer(BasePlugin):
    
    help = {
        'summary': 'Displays MNE Evoked (ERP) data in butterfly or single-channel mode.',
        'usage': 'Connect an mne.Evoked or list of Evoked objects. Toggle single-channel mode to inspect individual channels.',
        'inputs': {
            'evoked': 'mne.Evoked or list[mne.Evoked] — evoked/averaged EEG data (if list, first element is used)',
            'channel': 'str or int — optional: force channel selection by name or index (only applies in single-channel mode)',
        },
        'outputs': {},
        'parameters': [],
        'gotchas': [
            'If a list of Evoked is provided, only the first is displayed.',
            'Single-channel mode requires the checkbox to be enabled in the UI; channel input alone does not activate it.',
            'The channel input accepts a string (name, case-insensitive) or integer (index).',
            'Butterfly mode overlays all channels on the same axes — can be dense with many channels.',
            'Requires MNE to be installed for Evoked data handling.',
        ],
    }
     
    name = "EvokedViewer"
    language = "Python"
    category = "Output Nodes"
    supports_collapse = True
    start_hidden = True

    def setup(self):
        self.inputs = {
            "evoked": BehaviorSubject(None),
            # OPTIONNEL: permet de piloter la sélection depuis le workflow (str nom ou int index)
            "channel": BehaviorSubject(None),
        }
        self.outputs = {}

        # UI / état
        self._widget = None
        self._fig = None
        self._canvas = None
        self._big = None

        self._chk_single = None
        self._cb_channel = None
        self._lbl_info = None

        self._last_evoked = None
        self._ch_names = []
        self._single_mode = False
        self._channel_hint = None  # valeur reçue via pin "channel" (str/int)

    # ---------- UI ----------
    def build_widget(self):
        if self._widget is not None:
            return self._widget

        panel = QWidget()
        pv = QVBoxLayout(panel)

        # Figure compacte
        self._fig = Figure(figsize=(5, 3), tight_layout=True)
        self._canvas = FigureCanvas(self._fig)
        pv.addWidget(self._canvas)

        # Ligne contrôle: single + combo + agrandir
        row = QHBoxLayout()
        self._chk_single = QCheckBox("Single channel")
        self._chk_single.stateChanged.connect(self._on_toggle_single)
        row.addWidget(self._chk_single)

        self._cb_channel = QComboBox()
        self._cb_channel.setEnabled(False)  # activée seulement en mode single
        self._cb_channel.currentTextChanged.connect(lambda _: self._render_small())
        row.addWidget(QLabel("Channel:"))
        row.addWidget(self._cb_channel, 1)

        btn = QPushButton("Agrandir…")
        btn.clicked.connect(self._open_big)
        row.addWidget(btn)

        pv.addLayout(row)

        # petite étiquette d’info
        self._lbl_info = QLabel("")
        self._lbl_info.setStyleSheet("color: #bbb; font-style: italic;")
        pv.addWidget(self._lbl_info)

        # Collapsible
        wrap = QWidget()
        wlay = QVBoxLayout(wrap)
        wlay.addWidget(CollapsibleSection("Evoked (ERP) Viewer", panel, collapsed=False))

        self._widget = wrap
        return wrap

    def _on_toggle_single(self, s):
        self._single_mode = (s == Qt.Checked)
        self._cb_channel.setEnabled(self._single_mode)
        # si on vient d'activer, synchroniser la sélection avec le hint s'il existe
        if self._single_mode and self._channel_hint is not None:
            self._apply_channel_hint()
        self._render_small()

    def _open_big(self):
        if self._big is None:
            self._big = _BigDialog()
        self._plot_into(self._big.fig, self._last_evoked, big=True)
        self._big.canvas.draw_idle()
        self._big.show()
        self._big.raise_()
        self._big.activateWindow()

    # ---------- Plot helpers ----------
    def _update_channel_list(self, evoked):
        # Récupère les noms de canaux
        try:
            ch_names = list(getattr(evoked, "ch_names", []) or [])
        except Exception:
            ch_names = []
        self._ch_names = ch_names

        # Remplir combo (sans boucler les signaux)
        if self._cb_channel is not None:
            self._cb_channel.blockSignals(True)
            self._cb_channel.clear()
            if ch_names:
                self._cb_channel.addItems(ch_names)
            self._cb_channel.blockSignals(False)

        # appliquer éventuel hint externe
        if self._channel_hint is not None:
            self._apply_channel_hint()

    def _apply_channel_hint(self):
        """Applique la sélection reçue via l'input 'channel' (str ou int)."""
        if not self._cb_channel:
            return
        hint = self._channel_hint
        if hint is None or not self._ch_names:
            return
        self._cb_channel.blockSignals(True)
        try:
            if isinstance(hint, int):
                idx = max(0, min(hint, len(self._ch_names) - 1))
                self._cb_channel.setCurrentIndex(idx)
            else:
                # str -> cherche insensible à la casse
                s = str(hint).strip().lower()
                idx = -1
                for i, nm in enumerate(self._ch_names):
                    if nm.lower() == s:
                        idx = i
                        break
                if idx >= 0:
                    self._cb_channel.setCurrentIndex(idx)
        except Exception:
            pass
        self._cb_channel.blockSignals(False)

    def _current_channel_index(self):
        """Index à tracer si single mode. Priorité: combo; sinon 0."""
        if not self._single_mode or not self._ch_names:
            return None
        idx = self._cb_channel.currentIndex() if self._cb_channel else -1
        if idx < 0 and self._ch_names:
            idx = 0
        return idx if 0 <= idx < len(self._ch_names) else None

    def _plot_into(self, fig, evoked, big=False):
        fig.clear()
        ax = fig.add_subplot(111)

        if evoked is None:
            ax.set_title("No evoked")
            fig.canvas.draw_idle()
            return

        # si list -> premier
        if isinstance(evoked, (list, tuple)) and len(evoked) > 0:
            evoked = evoked[0]

        try:
            data = evoked.get_data()  # (n_channels, n_times)
            times = evoked.times
            ch_names = getattr(evoked, "ch_names", None)
        except Exception:
            ax.set_title("Invalid evoked")
            fig.canvas.draw_idle()
            return

        if self._single_mode:
            idx = self._current_channel_index()
            if idx is None:
                ax.set_title("Single channel: none selected")
            else:
                y = data[idx, :]
                label = ch_names[idx] if ch_names and 0 <= idx < len(ch_names) else f"ch {idx}"
                ax.plot(times, y, linewidth=1.2)
                ax.axvline(0.0, linestyle="--", linewidth=0.8)
                ax.set_xlabel("Time (s)")
                ax.set_ylabel("Amplitude (a.u.)")
                ax.set_title(f"Evoked – {label}")
        else:
            # butterfly
            ax.plot(times, data.T, linewidth=0.6)
            ax.axvline(0.0, linestyle="--", linewidth=0.8)
            ax.set_xlabel("Time (s)")
            ax.set_ylabel("Amplitude (a.u.)")
            ch_n = data.shape[0]
            ax.set_title(f"Evoked – butterfly ({ch_n} ch)")

        ax.grid(True)
        fig.canvas.draw_idle()

        # petite info UI (seulement dans petit viewer)
        if not big and self._lbl_info is not None:
            try:
                sf = getattr(evoked.info, "sfreq", None)
                txt = f"{data.shape[0]} ch × {data.shape[1]} samples"
                if sf:
                    txt += f"  |  sf={sf:.2f} Hz"
            except Exception:
                txt = ""
            self._lbl_info.setText(txt)

    def _render_small(self):
        if not self._canvas or not self._fig:
            return
        self._plot_into(self._fig, self._last_evoked, big=False)
        self._canvas.draw_idle()

    # ---------- Exécution ----------
    def execute(self, **kwargs):
        # fusionne kwargs et in_data (compat max)
        in_data = kwargs.get("in_data", {}) if "in_data" in kwargs else {}
        in_data.update(kwargs)

        # hint de canal (optionnel)
        if "channel" in in_data:
            self._channel_hint = in_data.get("channel")

        evk = in_data.get("evoked", None)
        self._last_evoked = evk

        # maj liste canaux si nouveau evoked
        if evk is not None:
            # si list -> premier pour l'UI
            ev = evk[0] if isinstance(evk, (list, tuple)) and len(evk) > 0 else evk
            self._update_channel_list(ev)
        self._render_small()
        return {}