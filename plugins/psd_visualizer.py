# plugins/psd_visualizer.py
# -*- coding: utf-8 -*-
"""
PSDVisualizer
- Affiche la/les courbe(s) de PSD (Welch).
- Entrées essentielles :
    • freqs     : np.ndarray shape (n_freqs,)
    • psd       : np.ndarray shape (n_ch, n_freqs)
    • ch_names  : list[str] | None
    • info      : dict | None
- Sorties :
    • config_out: dict  (pour ConfigNode)

UI (pliable) :
    • Moyenne sur canaux (on/off)
    • Échelle dB (10*log10)
    • max_points (décimation visuelle)
    • liste des canaux (avec “tous”)
    • bouton “Agrandir” (popup + plein écran)

Notes :
- Robuste face aux erreurs de type/shape et à l’ambiguïté NumPy.
- Le même rendu est tracé sur la vue principale et, si ouverte, sur la popup.
"""

import time
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QSpinBox, QPushButton,
    QListWidget, QListWidgetItem, QLayout, QSizePolicy, QDialog
)

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


class PSDVisualizer(BasePlugin):
    help = {
        'summary': 'Displays Welch PSD curves per channel with optional averaging and dB scaling.',
        'usage': 'Connect freqs and psd outputs from a PSD computation node. Toggle averaging and dB in the collapsible panel.',
        'inputs': {
            'freqs': '1D float array — frequency axis (Hz) from Welch computation',
            'psd': '2D float array [channels x frequencies] — power spectral density values',
            'ch_names': 'list[str] — channel names for the channel selector',
            'info': 'dict — optional metadata (not currently used)',
        },
        'outputs': {
            'config_out': 'dict — current config: {average_channels, use_db, max_points}',
        },
        'parameters': [
            {'name': 'average_channels', 'type': 'bool', 'default': True, 'desc': 'Average PSD across all selected channels into a single curve'},
            {'name': 'use_db', 'type': 'bool', 'default': True, 'desc': 'Display power on a logarithmic dB scale (10*log10)'},
            {'name': 'max_points', 'type': 'int', 'default': 4096, 'desc': 'Visual decimation limit — frequencies are downsampled if above this count'},
        ],
        'gotchas': [
            'psd must be 2D [n_ch x n_freqs]; 1D or 3D inputs are rejected as shape mismatches.',
            'freqs and psd shapes must be compatible (psd.shape[1] == freqs.shape[0]).',
            'dB mode clamps values at 1e-20 floor to avoid log(0) issues.',
            'Channel selector syncs with upstream ch_names; if names are missing, generic ch1/ch2 labels are used.',
            'Drawing is throttled to ~25 FPS to avoid UI lag on rapid updates.',
        ],
    }

    name = "PSDVisualizer"
    language = "Python"
    category = "Output Nodes"
    supports_collapse = True

    # --------------- lifecycle ----------------
    def setup(self):
        # inputs
        self.inputs["freqs"] = BehaviorSubject(None)
        self.inputs["psd"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["info"] = BehaviorSubject(None)

        # outputs
        self.outputs["config_out"] = BehaviorSubject(None)

        # state/UI params
        self._avg = True
        self._db = True
        self._max_points = 4096

        self._ui_ch_names = []
        self._keep_all = True
        self._sel_names = set()

        # main canvas
        self.figure = None
        self.axes = None
        self.canvas = None
        self._status = None
        self._ch_list = None
        self._chk_all = None

        # popup stuff
        self._popup = None
        self._pop_canvas = None
        self._pop_ax = None
        self._pop_fullscreen = False

        # throttling
        self._max_fps = 25
        self._last_draw = 0.0
        self._pending = False

        # cache signature (éviter redraw identiques)
        self._last_sig = None

    # --------------- config I/O ----------------
    def export_config(self) -> dict:
        return {
            "average_channels": bool(self._avg),
            "use_db": bool(self._db),
            "max_points": int(self._max_points),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return

        def _get(k, cur, typ):
            try:
                v = cfg.get(k, cur)
                return typ(v)
            except Exception:
                return cur

        self._avg = _get("average_channels", self._avg, bool)
        self._db = _get("use_db", self._db, bool)
        self._max_points = max(128, _get("max_points", self._max_points, int))
        self._emit_config()
        self._schedule_update()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "average_channels": {"type": "bool", "label": "Average across channels"},
                "use_db": {"type": "bool", "label": "Log scale (dB)"},
                "max_points": {"type": "int", "min": 128, "max": 100000, "step": 64, "label": "Décimation max points"},
            },
            "_order": ["average_channels", "use_db", "max_points"],
        }

    # --------------- UI ----------------
    def build_widget(self):
        root = QWidget()
        UiKit.apply_node_style(root)
        outer = QVBoxLayout(root)
        outer.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # figure
        self.figure = Figure(figsize=(5, 3))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        outer.addWidget(self.canvas, 1)

        # panneau de réglages
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(6)

        r1 = QHBoxLayout()
        chk_avg = QCheckBox("Average across channels")
        chk_avg.setChecked(self._avg)
        chk_avg.stateChanged.connect(lambda s: self._on_toggle("avg", s == Qt.Checked))
        r1.addWidget(chk_avg)

        chk_db = QCheckBox("Log scale (dB)")
        chk_db.setChecked(self._db)
        chk_db.stateChanged.connect(lambda s: self._on_toggle("db", s == Qt.Checked))
        r1.addWidget(chk_db)

        r1.addWidget(QLabel("max_points:"))
        sp_mp = QSpinBox()
        sp_mp.setRange(128, 100000)
        sp_mp.setSingleStep(64)
        sp_mp.setValue(self._max_points)
        sp_mp.valueChanged.connect(lambda v: self._on_set_max_points(int(v)))
        r1.addWidget(sp_mp)

        btn_big = QPushButton("Agrandir")
        btn_big.clicked.connect(self._show_large_plot)
        r1.addWidget(btn_big)

        r1.addStretch(1)
        pv.addLayout(r1)

        # canaux
        r2 = QHBoxLayout()
        self._chk_all = QCheckBox("Afficher tous les canaux")
        self._chk_all.setChecked(True)
        self._chk_all.stateChanged.connect(self._on_toggle_all)
        r2.addWidget(self._chk_all)
        r2.addStretch(1)
        pv.addLayout(r2)

        self._ch_list = QListWidget()
        self._ch_list.setMinimumHeight(80)
        self._ch_list.setMaximumHeight(140)
        self._ch_list.itemChanged.connect(self._on_item_changed)
        pv.addWidget(self._ch_list)

        # statut
        self._status = QLabel("PSD: en attente")
        pv.addWidget(self._status)

        outer.addWidget(CollapsibleSection("Paramètres & Sélection canaux", panel, collapsed=True))

        root.destroyed.connect(self._on_destroy)
        self._emit_config()
        return root

    # --------------- Exécution (réception des pins) ---------------
    def execute(self, in_data=None, **kwargs):
        d = {}
        if isinstance(in_data, dict):
            d.update(in_data)
        if kwargs:
            d.update(kwargs)

        for k in ("freqs", "psd", "ch_names", "info"):
            if k in d:
                try:
                    self.inputs[k].on_next(d[k])
                except Exception:
                    pass

        self._schedule_update()
        return {}

    # --------------- UI handlers ---------------
    def _on_toggle(self, key, val):
        if key == "avg":
            self._avg = bool(val)
        elif key == "db":
            self._db = bool(val)
        self._emit_config()
        self._schedule_update()

    def _on_set_max_points(self, v):
        self._max_points = max(128, int(v))
        self._emit_config()
        self._schedule_update()

    def _on_toggle_all(self, _s):
        check = Qt.Checked if self._chk_all.isChecked() else Qt.Unchecked
        self._ch_list.blockSignals(True)
        for i in range(self._ch_list.count()):
            self._ch_list.item(i).setCheckState(check)
        self._ch_list.blockSignals(False)
        self._snapshot_selection()
        self._schedule_update()

    def _on_item_changed(self, _it):
        if self._chk_all.isChecked():
            self._chk_all.blockSignals(True)
            self._chk_all.setChecked(False)
            self._chk_all.blockSignals(False)
        self._snapshot_selection()
        self._schedule_update()

    def _snapshot_selection(self):
        if self._ch_list.count() == 0:
            self._keep_all = True
            self._sel_names = set()
            return
        if self._chk_all.isChecked():
            self._keep_all = True
            self._sel_names = {self._ch_list.item(i).text().strip().lower()
                               for i in range(self._ch_list.count())}
        else:
            self._keep_all = False
            names = set()
            for i in range(self._ch_list.count()):
                it = self._ch_list.item(i)
                if it and it.checkState() == Qt.Checked:
                    names.add(it.text().strip().lower())
            self._sel_names = names

    def _populate_channels(self, names):
        names = list(names or [])
        self._ch_list.blockSignals(True)
        self._ch_list.clear()
        for nm in names:
            it = QListWidgetItem(nm)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (self._keep_all or nm.strip().lower() in self._sel_names)
                             else Qt.Unchecked)
            self._ch_list.addItem(it)
        self._ch_list.blockSignals(False)
        self._ui_ch_names = list(names)

    # --------------- popup (Agrandir) ---------------
    # --- remplace entièrement cette méthode ---
    def _show_large_plot(self):
        # fermer l'existant
        if self._popup is not None:
            try:
                self._popup.close()
            except Exception:
                pass
            self._popup = None
            self._pop_canvas = None
            self._pop_ax = None
            self._pop_fullscreen = False

        dlg = QDialog()
        dlg.setWindowTitle("PSD — Vue agrandie")
        lay = QVBoxLayout(dlg)
        tb = QHBoxLayout()
        btn_full = QPushButton("Plein écran")
        btn_close = QPushButton("Fermer")
        tb.addWidget(btn_full)
        tb.addStretch(1)
        tb.addWidget(btn_close)
        lay.addLayout(tb)

        fig = Figure(figsize=(12, 7))
        ax = fig.add_subplot(111)
        canvas = FigureCanvas(fig)
        lay.addWidget(canvas, 1)

        self._popup = dlg
        self._pop_canvas = canvas
        self._pop_ax = ax
        self._pop_fullscreen = False

        btn_full.clicked.connect(lambda: self._toggle_fullscreen(btn_full))
        btn_close.clicked.connect(dlg.close)

        def _on_finish(*_a):
            self._pop_canvas = None
            self._pop_ax = None
            self._popup = None
            self._pop_fullscreen = False

        dlg.finished.connect(_on_finish)
        dlg.showMaximized()

        # 👇 FORCER le redraw immédiat pour la popup
        self._last_sig = None
        self._update_plot()


    def _toggle_fullscreen(self, btn):
        if not self._popup:
            return
        if not self._pop_fullscreen:
            self._popup.showFullScreen()
            self._pop_fullscreen = True
            btn.setText("Fenêtré")
        else:
            self._popup.showMaximized()
            self._pop_fullscreen = False
            btn.setText("Plein écran")

    # --------------- drawing helpers ---------------
    def _maybe_draw(self, canvas=None):
        cv = canvas or self.canvas
        if cv is None:
            return
        now = time.monotonic()
        if now - self._last_draw < 1.0 / float(self._max_fps) and cv is self.canvas:
            cv.draw_idle()
            return
        cv.draw()
        if cv is self.canvas:
            self._last_draw = now

    def _schedule_update(self):
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._update_plot)

    # --------------- main update ---------------
    def _update_plot(self):
        self._pending = False
        ax = self.axes
        if ax is None:
            return

        F = self.inputs["freqs"].value
        P = self.inputs["psd"].value
        names_in = self.inputs["ch_names"].value

        # === checks ===
        if F is None or P is None:
            for a, cv, title in ((self.axes, self.canvas, "PSD — no data"),
                                 (self._pop_ax, self._pop_canvas, "PSD — no data")):
                if a is not None:
                    a.clear(); a.set_title(title); self._maybe_draw(cv)
            if self._status: self._status.setText("PSD: no data")
            return

        if not isinstance(F, np.ndarray) or not isinstance(P, np.ndarray):
            for a, cv, title in ((self.axes, self.canvas, "PSD — invalid types"),
                                 (self._pop_ax, self._pop_canvas, "PSD — invalid types")):
                if a is not None:
                    a.clear(); a.set_title(title); self._maybe_draw(cv)
            if self._status: self._status.setText("PSD: invalid input types")
            return

        if F.ndim != 1 or P.ndim != 2 or F.size == 0 or P.size == 0 or P.shape[1] != F.shape[0]:
            for a, cv, title in ((self.axes, self.canvas, "PSD — shape mismatch"),
                                 (self._pop_ax, self._pop_canvas, "PSD — shape mismatch")):
                if a is not None:
                    a.clear(); a.set_title(title); self._maybe_draw(cv)
            if self._status: self._status.setText("PSD: shape mismatch")
            return

        # noms de canaux
        if isinstance(names_in, (list, tuple)) and len(names_in) == P.shape[0]:
            ch_names = [str(x) for x in names_in]
        else:
            ch_names = [f"ch{i+1}" for i in range(P.shape[0])]

        # alimenter la liste (si vide / taille change)
        if not self._ui_ch_names or len(self._ui_ch_names) != len(ch_names):
            self._populate_channels(ch_names)

        # sélection
        if self._chk_all.isChecked():
            picks = list(range(P.shape[0]))
        else:
            want = {nm.strip().lower() for nm in (self._sel_names or [])}
            picks = [i for i, nm in enumerate(ch_names) if nm.strip().lower() in want]
        if not picks:
            for a, cv, title in ((self.axes, self.canvas, "PSD — no channel selected"),
                                 (self._pop_ax, self._pop_canvas, "PSD — no channel selected")):
                if a is not None:
                    a.clear(); a.set_title(title); self._maybe_draw(cv)
            if self._status: self._status.setText("PSD: no channel selected")
            return

        # décimation visuelle
        Fp = F
        Pp = P[picks, :]
        if self._max_points > 0 and Fp.size > self._max_points:
            dec = int(np.ceil(Fp.size / float(self._max_points)))
            Fp = Fp[::dec]
            Pp = Pp[:, ::dec]

        # dB si demandé
        if self._db:
            Pp = 10.0 * np.log10(np.maximum(Pp, 1e-20))
            ylab = "Power (dB)"
        else:
            ylab = "Power"

        # signature
        try:
            chk_head = float(np.nanmean(Pp[:, :min(8, Pp.shape[1])]))
            chk_tail = float(np.nanmean(Pp[:, -min(8, Pp.shape[1]):]))
        except Exception:
            chk_head = chk_tail = 0.0
        sig = (
            int(Fp.size),
            tuple(picks),
            bool(self._avg),
            bool(self._db),
            int(self._max_points),
            round(chk_head, 6),
            round(chk_tail, 6),
        )
        if sig == self._last_sig:
            return
        self._last_sig = sig

        # --- draw on main + popup (si ouverte) ---
        self._draw_to_axes(self.axes, self.canvas, Fp, Pp, picks, ch_names, ylab)
        if self._pop_ax is not None and self._pop_canvas is not None and self._popup is not None:
            self._draw_to_axes(self._pop_ax, self._pop_canvas, Fp, Pp, picks, ch_names, ylab)

        if self._status:
            self._status.setText(f"PSD: {P.shape[0]} ch × {F.shape[0]} f — shown {len(picks)} ch")

    def _draw_to_axes(self, ax, canvas, Fp, Pp, picks, ch_names, ylab):
        if ax is None:
            return
        ax.clear()
        if self._avg:
            y = np.nanmean(Pp, axis=0)
            ax.plot(Fp, y, linewidth=1.2)
            ax.set_title(f"PSD (Welch) — average of {len(picks)} ch")
        else:
            max_legend = 12
            for i, idx in enumerate(picks):
                lbl = ch_names[idx] if i < max_legend else None
                ax.plot(Fp, Pp[i, :], linewidth=0.8, label=lbl)
            if len(picks) > 1:
                ax.legend(loc="best", fontsize=8)
            ax.set_title(f"PSD (Welch) — {len(picks)} ch")

        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel(ylab)
        ax.grid(True, alpha=0.25)
        self._maybe_draw(canvas)

    # --------------- cleanup ---------------
    def _on_destroy(self, *_):
        try:
            if self.canvas is not None:
                self.canvas.close()
        except Exception:
            pass
        try:
            if self._popup is not None:
                self._popup.close()
        except Exception:
            pass
        self.canvas = None
        self.axes = None
        self.figure = None
        self._pop_canvas = None
        self._pop_ax = None
        self._popup = None