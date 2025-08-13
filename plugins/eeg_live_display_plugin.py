# plugins/eeg_live_display_plugin.py

import time
import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QSpinBox, QPushButton, QCheckBox, QListWidget, QListWidgetItem,
    QDialog, QVBoxLayout as QVBoxLayout2, QLayout, QSizePolicy, QToolButton
)
from PyQt5.QtCore import Qt, QTimer
from core.node_base import BasePlugin

# Logger de métriques (timestamps ns -> CSV)
from utils.eval_log import log_evt

try:
    import pyqtgraph as pg
    PG_OK = True
except Exception:
    PG_OK = False


# --- Utils robustes pour vérifier l'état des objets Qt ---
def _qdead(obj):
    """True si obj est None ou si le wrapper Qt pointe sur un C++ supprimé."""
    if obj is None:
        return True
    try:
        import sip  # PyQt5
        return sip.isdeleted(obj)
    except Exception:
        pass
    # PySide fallback
    _isValid = None
    try:
        from shiboken2 import isValid as _isValid  # PySide2
    except Exception:
        try:
            from shiboken6 import isValid as _isValid  # PySide6
        except Exception:
            _isValid = None
    if _isValid is not None:
        try:
            return not _isValid(obj)
        except Exception:
            return True
    return False


class _CollapsibleSection(QWidget):
    """Section repliable qui retire vraiment la hauteur quand fermée."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(8, 8, 8, 8)
        self._wrap_l.setSpacing(6)
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


class EEGLiveDisplayPlugin(BasePlugin):
    """
    Affichage EEG live (défilement) multi-canaux.

    Modes d'entrée :
      1) segment/sfreq/ch_names (depuis WindowSlicer) -> défile quand des segments arrivent
      2) raw (depuis EEG/GDFReader) -> défile tout seul via un timer interne (From Raw)

    UI :
      - Window (s), Gain (x), Spacing (µV)
      - Pause, Clear, Agrandir (fenêtre dédiée)
      - From Raw (Auto), Overlap (%), Loop
      - All + sélection manuelle des canaux

    Raccourcis (fenêtre Agrandir) :
      - F11 : plein écran / normal
      - Échap : sortir du plein écran
    """
    name = "EEGLiveDisplay"
    language = "Python"
    category = "Output Nodes"

    # --------------------- DIALOG PLEIN ÉCRAN ---------------------
    class _FullscreenDialog(QDialog):
        def __init__(self, parent=None, on_closed=None):
            super().__init__(parent)
            self._fs = False
            self._on_closed = on_closed
            self.setAttribute(Qt.WA_DeleteOnClose, True)
            self.setFocusPolicy(Qt.StrongFocus)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key_F11:
                if self._fs:
                    self.showNormal()
                    self._fs = False
                else:
                    self.showFullScreen()
                    self._fs = True
                e.accept()
                return
            if e.key() == Qt.Key_Escape and self._fs:
                self.showNormal()
                self._fs = False
                e.accept()
                return
            super().keyPressEvent(e)

        def closeEvent(self, ev):
            try:
                if callable(self._on_closed):
                    self._on_closed()
            except Exception:
                pass
            super().closeEvent(ev)

    # --------------------------- SETUP ----------------------------
    def setup(self):
        # Entrées
        self.inputs["segment"]   = BehaviorSubject(None)   # (n_ch, n_samples)
        self.inputs["sfreq"]     = BehaviorSubject(None)   # float
        self.inputs["ch_names"]  = BehaviorSubject(None)   # list[str]
        self.inputs["raw"]       = BehaviorSubject(None)   # mne.io.Raw

        # État data
        self._sfreq = 0.0
        no_ch = []
        self._ch_names = no_ch
        self._buf = None            # (n_ch, buf_len) en µV
        self._buf_len = 0
        self._x = None              # axe temps [-win, 0]

        # Paramètres affichage
        self._win_s = 10.0
        self._gain = 1.0
        self._spacing = 100.0
        self._paused = False

        # Streaming RAW
        self._raw = None
        self._ridx = 0
        self._overlap = 0.50
        self._loop = True
        self._from_raw = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)

        # UI refs
        self._lbl_status = None
        self._spn_win = None
        self._spn_gain = None
        self._spn_spacing = None
        self._chk_pause = None
        self._chk_all = None
        self._lst_channels = None
        self._plot = None
        self._chk_from_raw = None
        self._spn_overlap = None
        self._chk_loop = None

        # Courbes (vue principale)
        self._curves = {}

        # Fenêtre Agrandir
        self._dlg = None
        self._big_plot = None
        self._big_curves = {}

        # ----------------- MÉTRIQUES / LOGGING -----------------
        self._frame_id = 0
        self._first_frame_done = False
        self._frames_attempted = 0
        self._frames_drawn = 0
        self._last_stat_log = time.time()

        self._samples_in = 0
        self._last_samples_log = time.time()

    # ----------------------------- UI -----------------------------
    def build_widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        lay.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if not PG_OK:
            lay.addWidget(QLabel("pyqtgraph non installé. `pip install pyqtgraph`"))
            w.destroyed.connect(self._on_main_widget_destroyed)
            return w

        # ------- Panneau Paramètres (repliable) -------
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(6)

        # Ligne paramètres de base
        row = QHBoxLayout()
        row.addWidget(QLabel("Window (s):"))
        self._spn_win = QDoubleSpinBox()
        self._spn_win.setRange(1.0, 60.0)
        self._spn_win.setSingleStep(1.0)
        self._spn_win.setValue(self._win_s)
        self._spn_win.valueChanged.connect(self._on_win_changed)
        self._spn_win.valueChanged.connect(lambda v: log_evt("PARAM_CHANGE", f"win_s={float(v)}"))
        row.addWidget(self._spn_win)

        row.addWidget(QLabel("Gain (x):"))
        self._spn_gain = QDoubleSpinBox()
        self._spn_gain.setRange(0.1, 20.0)
        self._spn_gain.setSingleStep(0.1)
        self._spn_gain.setValue(self._gain)
        self._spn_gain.valueChanged.connect(self._on_gain_changed)
        self._spn_gain.valueChanged.connect(lambda v: log_evt("PARAM_CHANGE", f"gain={float(v)}"))
        row.addWidget(self._spn_gain)

        row.addWidget(QLabel("Spacing (µV):"))
        self._spn_spacing = QDoubleSpinBox()
        self._spn_spacing.setRange(10.0, 1000.0)
        self._spn_spacing.setSingleStep(10.0)
        self._spn_spacing.setValue(self._spacing)
        self._spn_spacing.valueChanged.connect(self._on_spacing_changed)
        self._spn_spacing.valueChanged.connect(lambda v: log_evt("PARAM_CHANGE", f"spacing={float(v)}"))
        row.addWidget(self._spn_spacing)

        self._chk_pause = QCheckBox("Pause")
        self._chk_pause.stateChanged.connect(lambda _: self._set_paused(self._chk_pause.isChecked()))
        self._chk_pause.stateChanged.connect(lambda _: log_evt("PARAM_CHANGE", f"pause={self._chk_pause.isChecked()}"))
        row.addWidget(self._chk_pause)

        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self._on_clear)
        row.addWidget(btn_clear)

        btn_big = QPushButton("Agrandir")
        btn_big.clicked.connect(self._open_big)
        row.addWidget(btn_big)

        row.addStretch(1)
        pv.addLayout(row)

        # Ligne RAW streaming
        rowR = QHBoxLayout()
        self._chk_from_raw = QCheckBox("From Raw (Auto)")
        self._chk_from_raw.stateChanged.connect(self._on_toggle_from_raw)
        self._chk_from_raw.stateChanged.connect(lambda _: log_evt("PARAM_CHANGE", f"from_raw={self._chk_from_raw.isChecked()}"))
        rowR.addWidget(self._chk_from_raw)

        rowR.addWidget(QLabel("Overlap (%):"))
        self._spn_overlap = QSpinBox()
        self._spn_overlap.setRange(0, 95)
        self._spn_overlap.setSingleStep(5)
        self._spn_overlap.setValue(int(self._overlap * 100))
        self._spn_overlap.valueChanged.connect(self._on_overlap_changed)
        self._spn_overlap.valueChanged.connect(lambda v: log_evt("PARAM_CHANGE", f"overlap_pct={int(v)}"))
        rowR.addWidget(self._spn_overlap)

        self._chk_loop = QCheckBox("Loop")
        self._chk_loop.setChecked(True)
        self._chk_loop.stateChanged.connect(lambda _: setattr(self, "_loop", self._chk_loop.isChecked()))
        self._chk_loop.stateChanged.connect(lambda _: log_evt("PARAM_CHANGE", f"loop={self._chk_loop.isChecked()}"))
        rowR.addWidget(self._chk_loop)

        rowR.addStretch(1)
        pv.addLayout(rowR)

        # Ligne sélection canaux
        row2 = QHBoxLayout()
        self._chk_all = QCheckBox("All")
        self._chk_all.setChecked(True)
        self._chk_all.stateChanged.connect(self._on_toggle_all)
        row2.addWidget(self._chk_all)

        self._lst_channels = QListWidget()
        self._lst_channels.setSelectionMode(self._lst_channels.MultiSelection)
        self._lst_channels.itemSelectionChanged.connect(self._refresh_curves_list)
        self._lst_channels.setMaximumHeight(100)
        row2.addWidget(self._lst_channels, 1)
        pv.addLayout(row2)

        # Ajoute la section repliable
        lay.addWidget(_CollapsibleSection("Paramètres", panel, collapsed=True))

        # Plot principal
        pg.setConfigOptions(antialias=False)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("k")
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.setLabel("bottom", "Time", "s")
        self._plot.setLabel("left", "Amplitude", "µV (offset)")
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=False, y=False)
        lay.addWidget(self._plot, 1)

        self._lbl_status = QLabel("No data")
        lay.addWidget(self._lbl_status)

        # --- cleanup safe quand le widget est détruit ---
        w.destroyed.connect(self._on_main_widget_destroyed)
        if self._lst_channels is not None:
            self._lst_channels.destroyed.connect(lambda *a: setattr(self, "_lst_channels", None))
        if self._plot is not None:
            self._plot.destroyed.connect(lambda *a: setattr(self, "_plot", None))

        return w

    # --------------------------- RUNTIME --------------------------
    def execute(self, **kwargs):
        # --- Mode SEGMENT ---
        seg = kwargs.get("segment", None)
        sf  = kwargs.get("sfreq", None)
        chn = kwargs.get("ch_names", None)

        changed = False
        if isinstance(sf, (int, float)) and sf and sf != self._sfreq:
            self._sfreq = float(sf); changed = True
        if isinstance(chn, (list, tuple)) and chn and chn != self._ch_names:
            self._ch_names = list(chn); changed = True; self._rebuild_channel_list()
        if changed:
            self._resize_buffer()

        if seg is not None and isinstance(seg, np.ndarray) and seg.ndim == 2:
            # comptage d'échantillons entrants (mode segment)
            try:
                nsamp = int(seg.shape[1])
            except Exception:
                nsamp = 0
            self._samples_in += max(0, nsamp)
            now = time.time()
            if now - self._last_samples_log >= 5.0:
                log_evt("SAMPLES_IN", str(self._samples_in))
                self._last_samples_log = now

            if not self._paused and self._sfreq > 0 and self._buf is not None and not self._from_raw:
                self._append_segment(seg)
                self._redraw()

        # --- Mode RAW ---
        raw = kwargs.get("raw", None)
        if raw is not None and raw is not self._raw:
            self._raw = raw
            try:
                self._sfreq = float(raw.info.get("sfreq", 0.0))
            except Exception:
                self._sfreq = 0.0
            self._ch_names = list(raw.ch_names) if getattr(raw, "ch_names", None) else []
            self._ridx = 0
            self._rebuild_channel_list()
            self._resize_buffer()
            self._recompute_timer()

        # Status
        if not _qdead(self._lbl_status):
            if self._buf is None or self._sfreq <= 0:
                self._lbl_status.setText("No data")
            else:
                n_ch = self._buf.shape[0]
                src = "RAW" if (self._from_raw and self._raw is not None) else "Segments"
                self._lbl_status.setText(f"{n_ch} ch | Fs={self._sfreq:.1f} Hz | win={self._win_s:.1f}s | src={src}")

        return {}

    # ----------------------- RAW TIMER LOGIC ----------------------
    def _on_toggle_from_raw(self, _state):
        self._from_raw = self._chk_from_raw.isChecked() if self._chk_from_raw else False
        self._recompute_timer()

    def _on_overlap_changed(self, v: int):
        self._overlap = max(0.0, min(0.95, v / 100.0))
        self._recompute_timer()

    def _recompute_timer(self):
        # si l'UI est partie, ne stream pas
        if _qdead(self._plot) and _qdead(self._big_plot):
            try:
                self._timer.stop()
            except Exception:
                pass
            return
        if not self._from_raw or self._raw is None or self._sfreq <= 0:
            self._timer.stop()
            return
        n_win = max(1, int(round(self._win_s * self._sfreq)))
        step = max(1, int(round(n_win * (1.0 - self._overlap))))
        period_ms = max(10, int(round(1000.0 * step / self._sfreq)))
        self._timer.start(period_ms)

    def _on_tick(self):
        if self._paused or not self._from_raw or self._raw is None or self._sfreq <= 0:
            return
        # si l'UI est partie, ne rien dessiner
        if _qdead(self._plot) and _qdead(self._big_plot):
            try:
                self._timer.stop()
            except Exception:
                pass
            return

        n_win = max(1, int(round(self._win_s * self._sfreq)))
        step  = max(1, int(round(n_win * (1.0 - self._overlap))))
        start = self._ridx
        end   = min(start + step, int(self._raw.n_times))

        if end <= start:
            if self._loop:
                self._ridx = 0
                return
            else:
                self._timer.stop()
                return

        try:
            data, _ = self._raw[:, start:end]  # Volts
        except Exception:
            return

        # comptage d'échantillons entrants (mode RAW)
        nsamp = int(max(0, end - start))
        self._samples_in += nsamp
        now = time.time()
        if now - self._last_samples_log >= 5.0:
            log_evt("SAMPLES_IN", str(self._samples_in))
            self._last_samples_log = now

        self._ridx = end
        if self._buf is not None:
            self._append_segment(data)
            self._redraw()

    # ---------------------------- HELPERS -------------------------
    def _resize_buffer(self):
        if self._sfreq <= 0 or not self._ch_names:
            self._buf = None; self._buf_len = 0; self._x = None
            self._clear_plot_curves(self._plot, self._curves)
            self._clear_plot_curves(self._big_plot, self._big_curves)
            return

        buf_len = int(max(1, round(self._sfreq * self._win_s)))
        n_ch = len(self._ch_names)

        if self._buf is None or self._buf.shape[0] != n_ch or self._buf_len != buf_len:
            self._buf_len = buf_len
            self._buf = np.zeros((n_ch, buf_len), dtype=np.float32)
            self._x = np.linspace(-self._win_s, 0.0, buf_len, dtype=np.float32)

            # reset courbes
            self._clear_plot_curves(self._plot, self._curves)
            self._create_curves(self._plot, self._curves)

            if not _qdead(self._plot):
                self._plot.setXRange(-self._win_s, 0.0, padding=0)

            if not _qdead(self._big_plot):
                self._clear_plot_curves(self._big_plot, self._big_curves)
                self._create_curves(self._big_plot, self._big_curves)
                self._big_plot.setXRange(-self._win_s, 0.0, padding=0)

    def _append_segment(self, seg_v):
        # seg_v: (n_ch, n_new) en Volts
        n_ch = len(self._ch_names)
        if self._buf is None or seg_v.shape[0] != n_ch:
            return

        seg = seg_v.astype(np.float32) * (1e6 * float(self._gain))  # V -> µV * gain
        n_new = seg.shape[1]
        if n_new <= 0 or self._buf_len <= 0:
            return

        if n_new >= self._buf_len:
            self._buf[:] = seg[:, -self._buf_len:]
            return

        self._buf[:, :-n_new] = self._buf[:, n_new:]
        self._buf[:, -n_new:] = seg

    def _create_curves(self, plot, curves_dict):
        if not PG_OK or plot is None or _qdead(plot) or self._buf is None:
            return
        curves_dict.clear()
        idxs = self._selected_channel_indices()
        if not idxs:
            idxs = list(range(len(self._ch_names)))
        for idx in idxs:
            try:
                c = pg.PlotDataItem(pen=pg.mkPen((idx * 37) % 255))
                plot.addItem(c)
                curves_dict[idx] = c
            except Exception:
                pass

    def _clear_plot_curves(self, plot, curves_dict):
        if not PG_OK or plot is None or _qdead(plot):
            curves_dict.clear()
            return
        for c in list(curves_dict.values()):
            try:
                plot.removeItem(c)
            except Exception:
                pass
        curves_dict.clear()
        try:
            plot.clear()
            plot.showGrid(x=True, y=True, alpha=0.2)
            plot.setLabel("bottom", "Time", "s")
            plot.setLabel("left", "Amplitude", "µV (offset)")
        except Exception:
            pass

    def _redraw(self):
        if not PG_OK or self._buf is None or self._x is None:
            return

        # tentative de rendu
        self._frames_attempted += 1

        self._redraw_one(self._plot, self._curves)
        if not _qdead(self._big_plot):
            self._redraw_one(self._big_plot, self._big_curves)

        # frame effectivement dessinée
        log_evt("FRAME", f"n={self._frame_id}")
        self._frame_id += 1
        self._frames_drawn += 1

        if not self._first_frame_done and self._buf is not None and self._buf_len > 0:
            log_evt("FIRST_FRAME", f"frame_id={self._frame_id}")
            self._first_frame_done = True

        now = time.time()
        if now - self._last_stat_log >= 5.0:
            log_evt("FRAMES_STAT", f"{self._frames_drawn},{self._frames_attempted}")
            self._last_stat_log = now

    def _redraw_one(self, plot, curves_dict):
        if plot is None or _qdead(plot) or self._buf is None:
            return
        spacing = float(self._spacing)
        idxs = self._selected_channel_indices()
        if self._chk_all and not _qdead(self._chk_all) and self._chk_all.isChecked():
            idxs = list(range(self._buf.shape[0]))

        # sync set de courbes
        current = set(curves_dict.keys())
        want = set(idxs)
        for ridx in current - want:
            try:
                if not _qdead(plot):
                    plot.removeItem(curves_dict[ridx])
            except Exception:
                pass
            curves_dict.pop(ridx, None)
        for aidx in want - current:
            try:
                c = pg.PlotDataItem(pen=pg.mkPen((aidx * 37) % 255))
                if not _qdead(plot):
                    plot.addItem(c)
                    curves_dict[aidx] = c
            except Exception:
                pass

        for order, ch_idx in enumerate(sorted(curves_dict.keys())):
            try:
                y = self._buf[ch_idx, :] + order * spacing
                curves_dict[ch_idx].setData(self._x, y)
            except Exception:
                pass

        if curves_dict and not _qdead(plot):
            max_order = len(curves_dict) - 1
            try:
                plot.setYRange(-spacing * 0.5, spacing * (max_order + 0.5), padding=0)
                plot.setXRange(-self._win_s, 0.0, padding=0)
            except Exception:
                pass

    def _rebuild_channel_list(self):
        lst = self._lst_channels
        if _qdead(lst):
            return
        lst.clear()
        for name in self._ch_names:
            it = QListWidgetItem(name)
            it.setSelected(True)
            lst.addItem(it)

    def _selected_channel_indices(self):
        lst = self._lst_channels
        if _qdead(lst):
            return list(range(len(self._ch_names)))
        sel = lst.selectedIndexes()
        return [ix.row() for ix in sel]

    # --------------------- FENÊTRE AGRANDIR ----------------------
    def _on_dlg_closed(self):
        try:
            if self._dlg:
                self._dlg.deleteLater()
        except Exception:
            pass
        self._dlg = None
        self._clear_plot_curves(self._big_plot, self._big_curves)
        self._big_plot = None
        self._big_curves = {}

    def _toggle_big_fullscreen(self):
        if not self._dlg:
            return
        if self._dlg.isFullScreen():
            self._dlg.showNormal()
            try:
                self._dlg._fs = False
            except Exception:
                pass
        else:
            self._dlg.showFullScreen()
            try:
                self._dlg._fs = True
            except Exception:
                pass

    def _open_big(self):
        if not PG_OK:
            return

        if self._dlg is not None:
            if not self._dlg.isVisible():
                self._dlg.show()
            try:
                self._dlg.raise_()
                self._dlg.activateWindow()
            except Exception:
                pass
            return

        # Crée un nouveau dialog plein écran togglable (F11)
        self._dlg = EEGLiveDisplayPlugin._FullscreenDialog(on_closed=self._on_dlg_closed)
        self._dlg.setWindowTitle("EEG Live (Agrandir) – F11 pour plein écran / Échap pour quitter")
        self._dlg.finished.connect(self._on_dlg_closed)
        self._dlg.destroyed.connect(self._on_dlg_closed)

        v = QVBoxLayout2(self._dlg)

        # Plot agrandi
        self._big_plot = pg.PlotWidget()
        self._big_plot.setBackground("k")
        self._big_plot.showGrid(x=True, y=True, alpha=0.2)
        self._big_plot.setLabel("bottom", "Time", "s")
        self._big_plot.setLabel("left", "Amplitude", "µV (offset)")
        self._big_plot.setMenuEnabled(False)
        self._big_plot.setMouseEnabled(x=False, y=False)
        v.addWidget(self._big_plot, 1)

        # Crée les courbes si on a un buffer
        if self._buf is not None:
            self._create_curves(self._big_plot, self._big_curves)
            self._big_plot.setXRange(-self._win_s, 0.0, padding=0)

        # --- Barre de boutons (Full Screen + Fermer)
        btn_row = QHBoxLayout()
        btn_fs = QPushButton("Full Screen (F11)")
        btn_fs.clicked.connect(self._toggle_big_fullscreen)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self._dlg.close)
        btn_row.addWidget(btn_fs)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_close)
        v.addLayout(btn_row)

        try:
            self._big_plot.destroyed.connect(lambda *a: setattr(self, "_big_plot", None))
        except Exception:
            pass

        self._dlg.resize(1000, 600)
        self._dlg.show()

    # --------------------------- SLOTS UI -------------------------
    def _on_win_changed(self, v):
        self._win_s = float(v)
        self._resize_buffer()
        self._recompute_timer()

    def _on_gain_changed(self, v):
        self._gain = float(v)
        self._redraw()

    def _on_spacing_changed(self, v):
        self._spacing = float(v)
        self._redraw()

    def _set_paused(self, paused):
        self._paused = bool(paused)

    def _on_toggle_all(self):
        lst = self._lst_channels
        if _qdead(lst):
            return
        check = self._chk_all.isChecked() if (self._chk_all and not _qdead(self._chk_all)) else True
        for i in range(lst.count()):
            item = lst.item(i)
            item.setSelected(bool(check))
        self._redraw()

    def _refresh_curves_list(self):
        if self._chk_all and not _qdead(self._chk_all) and self._chk_all.isChecked():
            self._chk_all.blockSignals(True)
            self._chk_all.setChecked(False)
            self._chk_all.blockSignals(False)
        self._redraw()

    def _on_clear(self):
        # Vide vraiment l’affichage : plus de courbe, plus de buffer.
        self._buf = None
        self._buf_len = 0
        self._x = None
        self._clear_plot_curves(self._plot, self._curves)
        self._clear_plot_curves(self._big_plot, self._big_curves)
        if not _qdead(self._lbl_status):
            self._lbl_status.setText("Cleared (empty)")
        log_evt("CLEAR", "display")

    # --------------------- CLEANUP UI ----------------------
    def _on_main_widget_destroyed(self, *a):
        # Stoppe le timer “From Raw (Auto)” et oublie les refs UI
        try:
            if self._timer and self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        for attr in [
            "_plot", "_lst_channels", "_chk_all", "_spn_win", "_spn_gain",
            "_spn_spacing", "_chk_pause", "_chk_from_raw", "_spn_overlap",
            "_chk_loop", "_lbl_status"
        ]:
            try:
                setattr(self, attr, None)
            except Exception:
                pass
        self._big_plot = None
        self._big_curves = {}
        self._dlg = None
