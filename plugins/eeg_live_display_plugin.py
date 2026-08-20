# plugins/eeg_live_display.py
# -*- coding: utf-8 -*-
"""
EEGLiveDisplay — affichage RAW/SEGMENT avec défilement fluide (Matplotlib+Qt)
• Optimisations anti-lag: décimation, throttling FPS, maj différée via singleShot(0)
• Compatibilité ConfigNode: export_config / import_config / config_hints + config_out
• Hooks métriques (pour TTFP / Throughput / Dropped / Latency):
    - TTFP: event "TTFP" avec champ ttfp_s (s)
    - FRAME_RENDERED avec lat_ms (ms) pour P50/P95
    - FRAME_DROPPED quand throttle
    - RENDER_STATS (2 s): fps, dropped_pct, throughput_sps (+ throughput_ksps)
    - CPU_MEM (1 s, si psutil dispo)
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QDialog, QLabel,
    QListWidget, QListWidgetItem, QCheckBox, QToolButton, QLayout,
    QSizePolicy, QDoubleSpinBox, QScrollArea, QSpinBox
)
import numpy as np
import time, os

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from core.metrics_logger import metrics  # HOOKS METRICS

try:
    import mne  # noqa: F401
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

try:
    import psutil  # pour CPU_MEM (optionnel)
except Exception:
    psutil = None


class _CollapsibleSection(QWidget):
    

    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._wrap = QWidget()
        self._wrap_l = QVBoxLayout(self._wrap); self._wrap_l.setContentsMargins(0, 0, 0, 0); self._wrap_l.setSpacing(0)
        self._content = content or QWidget(); self._wrap_l.addWidget(self._content)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(4)
        root.addWidget(self._btn); root.addWidget(self._wrap)
        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed if isinstance(collapsed, bool) else True)
        self._on_toggled(self._btn.isChecked())

    def _poke(self):
        w = self
        while w is not None:
            if w.layout(): w.layout().invalidate()
            w.adjustSize(); w.updateGeometry()
            w = w.parentWidget()

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        if expanded:
            self.setMaximumHeight(16777215); self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            h = self._btn.sizeHint().height() + 6
            self.setMaximumHeight(h); self.setMinimumHeight(h); self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._poke()


class EEGLiveDisplay(BasePlugin):
    help = {
        'summary': 'Real-time EEG display with scrolling traces. Supports both raw (continuous) and segment modes.',
        'usage': 'Connect upstream EEG data (raw or segment). Adjust window size, scroll speed, and FPS in the properties panel.',
        'inputs': {
            'raw': 'MNE Raw object — for continuous raw display mode',
            'segment': '2D float [channels x samples] — for segment display mode',
            'ch_names': 'list[str] — channel names',
            'sfreq': 'float — sampling frequency (Hz)',
            'info': 'dict — metadata (reset, seg_index, seg_len_s, etc.)',
        },
        'outputs': {
            'config_out': 'dict — current parameter state',
        },
        'parameters': [
            {'name': 'loop', 'type': 'bool', 'default': True, 'desc': 'Loop playback for RAW mode'},
            {'name': 'window_s', 'type': 'float', 'default': 10.0, 'desc': 'Display window duration (seconds)'},
            {'name': 'step_s', 'type': 'float', 'default': 0.2, 'desc': 'RAW scroll step (seconds)'},
            {'name': 'seg_len_auto', 'type': 'bool', 'default': True, 'desc': 'Auto-detect segment length from incoming data'},
            {'name': 'max_points', 'type': 'int', 'default': 3000, 'desc': 'Max plot points per trace (decimation limit)'},
            {'name': 'max_fps', 'type': 'int', 'default': 20, 'desc': 'Max rendering frame rate (5–120)'},
            {'name': 'force_nch', 'type': 'int', 'default': 0, 'desc': 'Force number of displayed channels (0 = auto/all)'},
        ],
        'gotchas': [
            'High max_fps can drop performance on slow machines; start with 20–30.',
            'max_points controls decimation — lower values = smoother but less detail.',
            'In RAW mode, data must be streamed continuously (e.g., from LSLInlet).',
        ],
    }

    name = "EEGLiveDisplay"
    language = "Python"
    category = "Output Nodes"

    # -------------------- lifecycle --------------------
    def setup(self):
        self.inputs = {
            "raw": BehaviorSubject(None),
            "segment": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "info": BehaviorSubject(None),
        }
        self.outputs["config_out"] = BehaviorSubject(None)

        # UI
        self.figure = None; self.axes = None; self.canvas = None
        self.label = None; self.channel_list = None; self.chk_all = None; self.chk_loop = None

        # popup
        self._popup = None; self._pop_canvas = None; self._pop_ax = None
        self._pop_fullscreen = False; self._pop_scroll = None; self._pop_row_h = 90

        # mode d’affichage
        self._mode = "idle"  # "raw" | "segment" | "idle"

        # RAW state
        self._raw = None; self._last_raw_obj_id = None
        self._cursor = 0; self._paused = False; self._loop = True
        self._window_s = 10.0; self._step_s = 0.2

        # timers (⚠️ pas de parent QObject)
        self._timer = QTimer()
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._on_tick)

        # Horloge RAW monotone
        self._raw_time_shift = 0.0
        self._raw_prev_times_last = None; self._raw_prev_times_first = None

        # SEGMENT ring buffer
        self._last_seg = None; self._last_names = []; self._last_fs = 0.0
        self._seg_buf = None; self._seg_buf_fs = 0.0; self._seg_buf_names = []; self._seg_buf_len = 0

        # Compteur de segments
        self._seg_index = 0; self._seg_total = None

        # Seg (s) + Auto
        self._seg_len_auto = True; self._seg_len_manual = None; self._seg_len_effective = None
        self._sp_seg_len = None; self._chk_seg_auto = None

        # Force n-ch
        self._force_nch = 0; self._sp_force_nch = None

        # sélection canaux
        self._sel_keep_all = True; self._sel_names = set(); self._ui_ch_names = None

        # draw throttling
        self._max_points = 3000; self._max_fps = 20; self._last_draw = 0.0; self._is_drawing = False

        # micro-planification
        self._pending_update = False

        # --- NEW: refs to spinboxes for max_points/fps
        self._sp_max_points = None
        self._sp_max_fps = None

        # --- METRICS state ---
        self._first_frame_logged = False
        self._frames_rendered = 0
        self._frames_dropped = 0
        self._last_stat_t = time.monotonic()

        # stats périodiques (⚠️ pas de parent QObject)
        self._stat_timer = QTimer()
        self._stat_timer.setInterval(2000)  # stats toutes les 2s
        self._stat_timer.timeout.connect(self._emit_render_stats)
        self._stat_timer.start()

        # CPU probe optionnel (1 Hz)
        self._cpu_last = time.time()

        # --- TTFP & latence par frame ---
        self._ttfp_t0 = None        # perf_counter() quand 1ère donnée arrive (raw/segment)
        self._ttfp_done = False     # True après 1ère frame dessinée
        self._lat_last_req_t = None # perf_counter() au moment du schedule_update

    # --------------- config I/O ----------------
    def export_config(self) -> dict:
        return {
            "loop": bool(self._loop),
            "window_s": float(self._window_s),
            "step_s": float(self._step_s),
            "seg_len_auto": bool(self._seg_len_auto),
            "seg_len_manual": (float(self._seg_len_manual) if (self._seg_len_manual is not None and not self._seg_len_auto) else None),
            "force_nch": int(self._force_nch),
            "max_points": int(self._max_points),
            "max_fps": int(self._max_fps),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        def _get(k, typ=None, d=None):
            v = cfg.get(k, d)
            if typ is None or v is None: return v
            try: return typ(v)
            except Exception: return d

        loop = _get("loop", bool, self._loop)
        if loop is not None and loop != self._loop:
            self._loop = bool(loop)
            if self.chk_loop: self.chk_loop.blockSignals(True); self.chk_loop.setChecked(self._loop); self.chk_loop.blockSignals(False)

        win = _get("window_s", float, self._window_s)
        if win is not None and win != self._window_s: self._window_s = float(win)

        step = _get("step_s", float, self._step_s)
        if step is not None and step != self._step_s: self._step_s = float(step)

        auto = _get("seg_len_auto", bool, self._seg_len_auto)
        if auto is not None and auto != self._seg_len_auto:
            self._seg_len_auto = bool(auto)
            if self._chk_seg_auto:
                self._chk_seg_auto.blockSignals(True); self._chk_seg_auto.setChecked(self._seg_len_auto); self._chk_seg_auto.blockSignals(False)
            if self._sp_seg_len:
                self._sp_seg_len.setEnabled(not self._seg_len_auto if isinstance(self._seg_len_auto, bool) else False)

        manual = cfg.get("seg_len_manual", None)
        if manual is not None:
            try:
                mv = float(manual)
                self._seg_len_manual = mv if not self._seg_len_auto else None
                self._seg_len_effective = (mv if not self._seg_len_auto else self._seg_len_effective)
                if self._sp_seg_len:
                    self._sp_seg_len.blockSignals(True); self._sp_seg_len.setValue(max(0.0, mv)); self._sp_seg_len.blockSignals(False)
            except Exception:
                pass

        fn = _get("force_nch", int, self._force_nch)
        if fn is not None and fn != self._force_nch:
            self._force_nch = int(fn)
            if self._sp_force_nch:
                self._sp_force_nch.blockSignals(True); self._sp_force_nch.setValue(self._force_nch); self._sp_force_nch.blockSignals(False)

        mp = _get("max_points", int, self._max_points)
        if mp is not None:
            self._max_points = int(mp)
            if self._sp_max_points:
                self._sp_max_points.blockSignals(True)
                self._sp_max_points.setValue(self._max_points)
                self._sp_max_points.blockSignals(False)

        fps = _get("max_fps", int, self._max_fps)
        if fps is not None:
            self._max_fps = int(fps)
            if self._sp_max_fps:
                self._sp_max_fps.blockSignals(True)
                self._sp_max_fps.setValue(self._max_fps)
                self._sp_max_fps.blockSignals(False)

        self._emit_config()
        self._schedule_update(mode=self._mode)

    def config_hints(self) -> dict:
        return {
            "fields": {
                "loop": {"type": "bool", "help": "Lecture RAW en boucle"},
                "window_s": {"type": "float", "min": 0.5, "max": 60.0, "step": 0.5, "label": "Fenêtre (s)"},
                "step_s": {"type": "float", "min": 0.05, "max": 5.0, "step": 0.05, "label": "Pas RAW (s)"},
                "seg_len_auto": {"type": "bool", "label": "Longueur segment Auto"},
                "seg_len_manual": {"type": "float", "min": 0.05, "max": 30.0, "step": 0.05, "label": "Longueur segment (manuel)"},
                "force_nch": {"type": "int", "min": 0, "max": 256, "label": "Forcer #canaux (0=auto)"},
                "max_points": {"type": "int", "min": 500, "max": 20000, "step": 100, "help": "Décimation graphique"},
                "max_fps": {"type": "int", "min": 5, "max": 120, "step": 1, "help": "FPS maximum du tracé"},
            },
            "_order": ["loop","window_s","step_s","seg_len_auto","seg_len_manual","force_nch","max_points","max_fps"],
        }

    def build_widget(self):
        root = QWidget()
        outer = QVBoxLayout(root); outer.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self.figure = Figure(figsize=(5, 2))
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        outer.addWidget(self.canvas, 1)

        panel = QWidget(); pv = QVBoxLayout(panel); pv.setContentsMargins(8, 8, 8, 8); pv.setSpacing(6)

        row1 = QHBoxLayout()
        btn_pause = QPushButton("Pause"); btn_pause.setCheckable(True); btn_pause.clicked.connect(lambda: self._on_toggle_pause(btn_pause)); row1.addWidget(btn_pause)
        btn_stop = QPushButton("Stop"); btn_stop.clicked.connect(self._on_stop); row1.addWidget(btn_stop)
        self.chk_loop = QCheckBox("Loop"); self.chk_loop.setChecked(self._loop); self.chk_loop.stateChanged.connect(self._on_loop_changed); row1.addWidget(self.chk_loop)
        row1.addStretch(1)
        row1.addWidget(QLabel("Window (s):"))
        sp_w = QDoubleSpinBox(); sp_w.setRange(0.5, 60.0); sp_w.setSingleStep(0.5); sp_w.setValue(self._window_s); sp_w.valueChanged.connect(self._on_window_changed); row1.addWidget(sp_w)
        row1.addWidget(QLabel("Step (s):"))
        sp_s = QDoubleSpinBox(); sp_s.setRange(0.05, 5.0); sp_s.setSingleStep(0.05); sp_s.setValue(self._step_s); sp_s.valueChanged.connect(self._on_step_changed); row1.addWidget(sp_s)
        pv.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Seg (s):"))
        self._sp_seg_len = QDoubleSpinBox(); self._sp_seg_len.setDecimals(3); self._sp_seg_len.setRange(0.05, 30.0); self._sp_seg_len.setSingleStep(0.05)
        self._sp_seg_len.setValue(0.0); self._sp_seg_len.setEnabled(False); self._sp_seg_len.valueChanged.connect(self._on_seg_len_changed); row2.addWidget(self._sp_seg_len)
        self._chk_seg_auto = QCheckBox("Auto"); self._chk_seg_auto.setChecked(True); self._chk_seg_auto.stateChanged.connect(self._on_seg_auto_toggled); row2.addWidget(self._chk_seg_auto)
        row2.addSpacing(18)
        row2.addWidget(QLabel("Force n-ch (0=auto):"))
        self._sp_force_nch = QSpinBox(); self._sp_force_nch.setRange(0, 256); self._sp_force_nch.setValue(0); self._sp_force_nch.valueChanged.connect(self._on_force_nch_changed); row2.addWidget(self._sp_force_nch)
        row2.addStretch(1)
        pv.addLayout(row2)

        # --- NOUVELLE RANGÉE : Max points / Max FPS ---
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Max points:"))
        self._sp_max_points = QSpinBox()
        self._sp_max_points.setRange(500, 20000)
        self._sp_max_points.setSingleStep(100)
        self._sp_max_points.setValue(self._max_points)
        self._sp_max_points.valueChanged.connect(self._on_max_points_changed)
        row3.addWidget(self._sp_max_points)

        row3.addSpacing(12)
        row3.addWidget(QLabel("Max FPS:"))
        self._sp_max_fps = QSpinBox()
        self._sp_max_fps.setRange(5, 120)
        self._sp_max_fps.setSingleStep(1)
        self._sp_max_fps.setValue(self._max_fps)
        self._sp_max_fps.valueChanged.connect(self._on_max_fps_changed)
        row3.addWidget(self._sp_max_fps)
        row3.addStretch(1)
        pv.addLayout(row3)

        self.channel_list = QListWidget(); self.channel_list.setMinimumHeight(80); self.channel_list.setMaximumHeight(140)
        self.channel_list.itemChanged.connect(self._on_item_changed)
        self.chk_all = QCheckBox("Afficher tous les canaux"); self.chk_all.setChecked(True); self.chk_all.stateChanged.connect(self._on_toggle_all)

        chbar = QHBoxLayout(); chbar.addWidget(self.chk_all); chbar.addStretch(1); pv.addLayout(chbar)
        pv.addWidget(self.channel_list)

        self.label = QLabel("Aucun signal EEG"); pv.addWidget(self.label)

        btn_big = QPushButton("Agrandir"); btn_big.clicked.connect(self._show_large_plot); pv.addWidget(btn_big)

        outer.addWidget(_CollapsibleSection("Paramètres & Contrôles", panel, collapsed=True))
        root.destroyed.connect(self._on_destroy)

        self._emit_config()
        return root

    # -------------------- UI helpers --------------------
    def _bench_param(self, key, val):
        try:
            metrics().param_change(name=str(key), new=val)
        except Exception:
            pass

    def _on_loop_changed(self, _state):
        self._loop = bool(self.chk_loop.isChecked()) if self.chk_loop else True
        self._bench_param("loop", int(self._loop))
        self._emit_config()

    def _on_step_changed(self, v):
        self._step_s = float(v)
        self._bench_param("step_s", v)
        self._emit_config()

    def _on_max_points_changed(self, v: int):
        self._max_points = int(v)
        self._bench_param("max_points", self._max_points)
        self._emit_config()
        self._schedule_update(mode=self._mode)

    def _on_max_fps_changed(self, v: int):
        self._max_fps = int(v)
        self._bench_param("max_fps", self._max_fps)
        self._emit_config()
        # throttle appliqué dès la prochaine frame

    def _on_toggle_pause(self, btn):
        self._paused = btn.isChecked()
        btn.setText("Resume" if self._paused else "Pause")
        self._update_plot(flush_only=True, force_mode=self._mode)

    def _on_stop(self):
        self._paused = True
        self._cursor = 0
        self._raw_time_shift = 0.0
        self._raw_prev_times_last = None
        self._raw_prev_times_first = None
        self._schedule_update(mode=("segment" if self._mode == "segment" else "raw"))

    def _on_window_changed(self, v):
        self._window_s = float(v)
        self._reset_segment_buffer()
        self._bench_param("win_s", v)
        self._emit_config()
        self._schedule_update(mode=("segment" if self._mode == "segment" else "raw"))

    def _on_seg_auto_toggled(self, _state):
        self._seg_len_auto = bool(self._chk_seg_auto.isChecked()) if self._chk_seg_auto else True
        if self._sp_seg_len is not None:
            self._sp_seg_len.setEnabled(not self._seg_len_auto)
            if self._seg_len_auto and self._seg_len_effective is not None:
                self._sp_seg_len.blockSignals(True); self._sp_seg_len.setValue(max(0.0, float(self._seg_len_effective))); self._sp_seg_len.blockSignals(False)
        if self._seg_len_auto:
            self._seg_len_manual = None
        else:
            self._seg_len_manual = float(self._sp_seg_len.value()); self._seg_len_effective = self._seg_len_manual
        self._bench_param("seg_auto", int(self._seg_len_auto))
        self._emit_config()
        self._update_plot(flush_only=True, force_mode=self._mode)

    def _on_seg_len_changed(self, v):
        if not self._seg_len_auto:
            self._seg_len_manual = float(v)
            self._seg_len_effective = float(v)
            self._bench_param("seg_len_s", v)
            self._emit_config()
            self._update_plot(flush_only=True, force_mode=self._mode)

    def _on_force_nch_changed(self, v):
        self._force_nch = int(v) if v is not None else 0
        self._bench_param("force_nch", v)
        self._emit_config()
        if self._mode == "raw" and self._raw is not None:
            try: names = list(self._raw.ch_names)
            except Exception: names = []
            names = self._apply_force_nch_to_names(names)
            self._populate_channels(names)
        elif self._mode == "segment" and self._last_names:
            names = self._apply_force_nch_to_names(self._last_names)
            self._populate_channels(names)
        self._schedule_update(mode=self._mode)

    def _norm_name(self, s: str) -> str:
        return (s or "").strip().lower()

    def _snapshot_selection(self):
        if self.channel_list is None or self.channel_list.count() == 0:
            return
        if self.chk_all and self.chk_all.isChecked():
            self._sel_keep_all = True
            self._sel_names = set(self._norm_name(self.channel_list.item(i).text()) for i in range(self.channel_list.count()))
        else:
            self._sel_keep_all = False
            names = set()
            for i in range(self.channel_list.count()):
                it = self.channel_list.item(i)
                if it and it.checkState() == Qt.Checked:
                    names.add(self._norm_name(it.text()))
            self._sel_names = names

    def _apply_force_nch_to_names(self, names):
        if not names: return []
        if self._force_nch and self._force_nch > 0:
            return list(names)[: min(self._force_nch, len(names))]
        return list(names)

    def _apply_force_nch_to_array(self, arr, names):
        if arr is None: return arr, names
        n_ch = arr.shape[0]
        if self._force_nch and self._force_nch > 0 and n_ch > self._force_nch:
            keep = self._force_nch; arr = arr[:keep, :]
            if names: names = list(names)[:keep]
        return arr, names

    def _populate_channels(self, ch_names):
        if self.channel_list is None: return
        ch_names = self._apply_force_nch_to_names(ch_names)
        keep_all = bool(self._sel_keep_all); sel_set = set(self._sel_names)
        self.channel_list.blockSignals(True); self.channel_list.clear()
        for name in ch_names:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if (keep_all or self._norm_name(name) in sel_set) else Qt.Unchecked)
            self.channel_list.addItem(it)
        self.channel_list.blockSignals(False)
        if self.chk_all:
            self.chk_all.blockSignals(True); self.chk_all.setChecked(keep_all); self.chk_all.blockSignals(False)
        self._ui_ch_names = list(ch_names)

    def _selected_indices(self, all_names=None):
        if self.channel_list is None: return []
        if self.channel_list.count() == 0:
            if all_names is not None:
                names_trim = self._apply_force_nch_to_names(all_names)
                return list(range(len(names_trim)))
            return []
        if self.chk_all and self.chk_all.isChecked(): return list(range(self.channel_list.count()))
        picks = []
        for i in range(self.channel_list.count()):
            if self.channel_list.item(i).checkState() == Qt.Checked:
                picks.append(i)
        return picks

    # -------------------- ring buffer --------------------
    def _reset_segment_buffer(self):
        self._seg_buf = None; self._seg_buf_fs = 0.0; self._seg_buf_names = []; self._seg_buf_len = 0

    def _ensure_seg_buffer(self, n_ch: int, fs: float, names):
        fs = float(fs or 0.0)
        if fs <= 0 or n_ch <= 0:
            self._reset_segment_buffer()
            return
        want_len = max(1, int(round(self._window_s * fs)))
        need_new = (
            self._seg_buf is None
            or self._seg_buf.shape[0] != n_ch
            or self._seg_buf_len != want_len
            or abs(self._seg_buf_fs - fs) > 1e-6
        )
        if need_new:
            self._seg_buf = np.zeros((n_ch, want_len), dtype=np.float32)
            self._seg_buf_len = want_len; self._seg_buf_fs = fs
            self._seg_buf_names = list(names) if names else [f"ch{i+1}" for i in range(n_ch)]

    def _append_segment_to_buffer(self, seg: np.ndarray):
        if self._seg_buf is None: return
        n_new = seg.shape[1]; n_buf = self._seg_buf.shape[1]
        if n_new >= n_buf: self._seg_buf[:, :] = seg[:, -n_buf:]
        else:
            self._seg_buf[:, :-n_new] = self._seg_buf[:, n_new:]
            self._seg_buf[:, -n_new:] = seg

    # -------------------- RAW tick --------------------
    def _on_tick(self):
        if self._mode == "segment" or self._paused or self._raw is None: return
        try:
            n_times = int(getattr(self._raw, "n_times", 0))
            sfreq = float(getattr(self._raw, "info", {}).get("sfreq", 0.0))
        except Exception:
            n_times, sfreq = 0, 0.0
        if n_times <= 0 or sfreq <= 0: return
        step = max(1, int(round(self._step_s * sfreq)))
        if self._cursor == 0: self._cursor = min(n_times, int(round(self._window_s * sfreq)))
        self._cursor = min(self._cursor + step, n_times)
        if self._cursor >= n_times:
            if self._loop: self._cursor = min(int(round(self._window_s * sfreq)), n_times)
            else: self._paused = True
        self._schedule_update(mode="raw")

    # -------------------- dessin + métriques --------------------
    def _maybe_draw(self, canvas):
        if canvas is None or getattr(canvas, "figure", None) is None:
            return
        if hasattr(canvas, "isVisible") and not canvas.isVisible():
            return

        now_mono = time.monotonic()
        now_perf = time.perf_counter()

        # throttle : on "droppe" la frame si trop tôt
        throttled = (now_mono - getattr(self, "_last_draw", 0.0)) < (1.0 / float(max(1, self._max_fps)))
        if throttled:
            self._frames_dropped += 1
            try:
                metrics().event("FRAME_DROPPED", reason="throttle", max_fps=self._max_fps)
            except Exception:
                pass
            return  # pas de draw

        # --- TTFP: première frame réellement rendue ---
        is_first_render = (self._frames_rendered == 0)
        if is_first_render and (self._ttfp_t0 is not None) and (not self._ttfp_done):
            ttfp_s = float(now_perf - self._ttfp_t0)
            try:
                metrics().event("TTFP", ttfp_s=ttfp_s)
            except Exception:
                pass
            self._ttfp_done = True

        # --- Latence par frame (ms) = temps depuis la dernière demande de rendu ---
        lat_ms = None
        if self._lat_last_req_t is not None:
            lat_ms = float((now_perf - self._lat_last_req_t) * 1000.0)

        # draw
        canvas.draw()
        self._last_draw = now_mono
        self._frames_rendered += 1

        # event par frame (n_frames, p50/p95) + latence
        try:
            if not self._first_frame_logged:
                metrics().event("FIRST_FRAME")
                self._first_frame_logged = True
            if lat_ms is not None:
                metrics().event("FRAME_RENDERED", lat_ms=lat_ms)
            else:
                metrics().event("FRAME_RENDERED")
        except Exception:
            pass

        # CPU_MEM 1 Hz (optionnel)
        if psutil:
            now2 = time.time()
            if now2 - self._cpu_last >= 1.0:
                try:
                    cpu = float(psutil.cpu_percent(interval=None))
                    rss_mb = int(psutil.Process(os.getpid()).memory_info().rss / (1024*1024))
                    metrics().cpu_mem(cpu=cpu, rss_mb=rss_mb)
                except Exception:
                    pass
                self._cpu_last = now2

    def _plot_data(self, data, times, names, title_prefix="EEG"):
        if self.axes is None or self.canvas is None: return
        if self._is_drawing: return
        self._is_drawing = True
        try:
            ax = self.axes; ax.clear()
            if data.shape[1] > self._max_points:
                dec = int(np.ceil(data.shape[1] / self._max_points))
                data = data[:, ::dec]; times = times[::dec]
            n_ch = int(data.shape[0]) if data is not None else 0
            if n_ch == 0 or data.shape[1] == 0:
                if self.label: self.label.setText("Aucun canal sélectionné")
                ax.set_title("No Channels"); ax.set_xlabel("Temps (s)")
                self._maybe_draw(self.canvas); return
            std = float(np.nanstd(data)) if np.isfinite(data).any() else 1.0
            spacing = std * 4 if std > 0 else 1.0
            offsets = np.arange(n_ch) * spacing
            for i in range(n_ch): ax.plot(times, data[i] + offsets[i], linewidth=0.8)
            labels = names if names else [f"ch{i+1}" for i in range(n_ch)]
            if n_ch <= 24: sel_idx = list(range(n_ch))
            else:
                step = int(np.ceil(n_ch / 24)); sel_idx = list(range(0, n_ch, step))
            ax.set_yticks([offsets[i] for i in sel_idx]); ax.set_yticklabels([labels[i] for i in sel_idx])
            ax.set_xlabel("Temps (s)"); ax.set_title(f"{title_prefix} — {n_ch} canal{'x' if n_ch > 1 else ''}")
            self._maybe_draw(self.canvas)

            if self._pop_canvas is not None and self._pop_ax is not None and self._popup is not None and self._popup.isVisible():
                px_h = max(int(self._pop_row_h * n_ch), 300); px_w = max(self._popup.width() - 60, 800)
                fig = self._pop_ax.figure; dpi = fig.get_dpi()
                fig.set_size_inches(px_w / dpi, px_h / dpi, forward=True)
                self._pop_canvas.setMinimumHeight(px_h); self._pop_canvas.setMinimumWidth(px_w)
                self._pop_ax.clear()
                for i in range(n_ch): self._pop_ax.plot(times, data[i] + offsets[i], linewidth=0.8)
                self._pop_ax.set_yticks([offsets[i] for i in sel_idx]); self._pop_ax.set_yticklabels([labels[i] for i in sel_idx])
                self._pop_ax.set_xlabel("Temps (s)"); self._pop_ax.set_title(f"{title_prefix} — vue agrandie")
                self._maybe_draw(self._pop_canvas)
        finally:
            self._is_drawing = False

    def _update_plot(self, flush_only=False, force_mode=None):
        if self.axes is None or self.canvas is None: return
        mode = force_mode or self._mode

        # SEGMENT
        if mode == "segment" and self._seg_buf is not None and self._seg_buf_fs > 0:
            names = self._seg_buf_names if self._seg_buf_names else [f"ch{i+1}" for i in range(self._seg_buf.shape[0])]
            if self.channel_list and self.channel_list.count() == 0: self._populate_channels(names)
            picks = self._selected_indices(all_names=names); picks = [i for i in picks if 0 <= i < self._seg_buf.shape[0]]
            if not picks:
                if self.label: self.label.setText("Aucun canal sélectionné")
                self.axes.clear(); self.axes.set_title("No Channels"); self.axes.set_xlabel("Temps (s)")
                self._maybe_draw(self.canvas); return
            data = self._seg_buf[picks, :]; fs = float(self._seg_buf_fs); t = np.arange(self._seg_buf.shape[1], dtype=float) / fs
            sel_names = [names[i] for i in picks]
            if self._seg_len_effective is not None and self._seg_len_effective > 0: seg_len_txt = f", {self._seg_len_effective:.2f}s"
            else: seg_len_txt = ""
            if self._seg_total is not None:
                seg_txt = f"EEG (segment {self._seg_index}/{self._seg_total}{seg_len_txt})"; lbl_seg = f"Segment {self._seg_index}/{self._seg_total}{seg_len_txt}"
            else:
                seg_txt = f"EEG (segment {self._seg_index}/?{seg_len_txt})"; lbl_seg = f"Segment {self._seg_index}/?{seg_len_txt}"
            self._plot_data(data, t, sel_names, title_prefix=seg_txt)
            if self.label and data.size: self.label.setText(f"{lbl_seg} | fs={fs:.2f} Hz | fenêtre = {self._window_s:.1f}s")
            return

        # RAW
        raw = self._raw
        if raw is None:
            self.axes.clear(); self.axes.set_title("No Data"); self.axes.set_xlabel("Temps (s)"); self._maybe_draw(self.canvas)
            if self.label: self.label.setText("Aucun signal EEG")
            return

        try:
            sfreq = float(raw.info.get("sfreq", 0.0)); n_times = int(getattr(raw, "n_times", 0))
        except Exception:
            sfreq, n_times = 0.0, 0
        if sfreq <= 0 or n_times <= 0:
            self.axes.clear(); self.axes.set_title("Invalid signal"); self._maybe_draw(self.canvas)
            if self.label: self.label.setText("Signal invalide")
            return

        N = max(1, int(round(self._window_s * sfreq)))
        stop = min(max(self._cursor, N), n_times)
        start = max(0, stop - N)

        try:
            all_names = list(raw.ch_names)
        except Exception:
            all_names = None

        names_for_ui = self._apply_force_nch_to_names(all_names or [])
        if self.channel_list and (self._ui_ch_names is None or len(self._ui_ch_names) != len(names_for_ui)):
            self._populate_channels(names_for_ui)

        picks = self._selected_indices(all_names=all_names)
        if self._force_nch and self._force_nch > 0:
            picks = [i for i in picks if i < min(self._force_nch, len(all_names or []))]

        if len(picks) == 0:
            if self.label: self.label.setText("Aucun canal sélectionné")
            self.axes.clear(); self.axes.set_title("No Channels"); self.axes.set_xlabel("Temps (s)"); self._maybe_draw(self.canvas)
            return

        try:
            data, times = raw[picks, start:stop]
        except Exception:
            if self.label: self.label.setText("Erreur d'accès aux données")
            self.axes.clear(); self.axes.set_title("Data error"); self._maybe_draw(self.canvas)
            return

        if data.size:
            if self._raw_prev_times_last is not None:
                if times[0] <= 1e-9: self._raw_time_shift = float(self._raw_prev_times_last)
            abs_times = times + self._raw_time_shift
            self._raw_prev_times_first = float(abs_times[0]); self._raw_prev_times_last = float(abs_times[-1])
        else:
            abs_times = times

        sel_names = [names_for_ui[i] if (0 <= i < len(names_for_ui)) else f"ch{i+1}" for i in range(len(picks))]
        try:
            alln = list(all_names) if all_names else []
            sel_names = [alln[p] if 0 <= p < len(alln) else f"ch{p+1}" for p in picks]
        except Exception:
            pass

        self._plot_data(data, abs_times, sel_names, title_prefix="EEG Live")
        if self.label and data.size:
            self.label.setText(f"t = {abs_times[-1]:.2f}s | fenêtre = {self._window_s:.1f}s")

    def _schedule_update(self, mode=None):
        if mode: self._mode = mode
        if self._pending_update: return
        self._pending_update = True

        # horodatage pour la latence "request → render"
        self._lat_last_req_t = time.perf_counter()

        def _do():
            self._pending_update = False
            self._update_plot(flush_only=True, force_mode=self._mode)
        QTimer.singleShot(0, _do)

    # -------------------- execute --------------------
    def execute(self, inputs=None, **kwargs):
        args = {}; 
        if isinstance(inputs, dict): args.update(inputs)
        args.update(kwargs)

        ch_kw = args.get("ch_names", None)
        if isinstance(ch_kw, (list, tuple)) and ch_kw:
            new_names = self._apply_force_nch_to_names(list(ch_kw))
            need_rebuild = (self._ui_ch_names is None or len(self._ui_ch_names) != len(new_names)
                            or any(a != b for a, b in zip(self._ui_ch_names, new_names)))
            if need_rebuild:
                self._snapshot_selection(); self._populate_channels(new_names)

        sf_kw = args.get("sfreq", None)
        if isinstance(sf_kw, (int, float)): self._last_fs = float(sf_kw)

        info = args.get("info", None)
        if isinstance(info, dict):
            if info.get("reset"):
                self._cursor = 0; self._raw_time_shift = 0.0; self._raw_prev_times_last = None; self._raw_prev_times_first = None; self._seg_index = 0
            if "total_segments" in info:
                try: self._seg_total = int(info["total_segments"])
                except Exception: self._seg_total = None
            if "seg_total" in info:
                try: self._seg_total = int(info["seg_total"])
                except Exception: pass
            if "seg_index" in info:
                try: self._seg_index = int(info["seg_index"])
                except Exception: pass
            if "seg_len_s" in info:
                try:
                    val = float(info["seg_len_s"])
                    if val > 0:
                        if self._seg_len_auto and self._sp_seg_len is not None:
                            self._sp_seg_len.blockSignals(True); self._sp_seg_len.setValue(val); self._sp_seg_len.blockSignals(False)
                        if not self._seg_len_auto: self._seg_len_manual = val
                        self._seg_len_effective = val
                except Exception:
                    pass

        # MODE SEGMENT
        if "segment" in args:
            seg_in = args.get("segment", None)
            if seg_in is None:
                if self._mode == "segment":
                    self._last_seg = None; self._reset_segment_buffer()
                    if self._raw is None:
                        if self.axes is not None:
                            self.axes.clear(); self.axes.set_title("Stopped"); self.axes.set_xlabel("Temps (s)"); self._maybe_draw(self.canvas)
                        if self.label: self.label.setText("Segment: disconnected")
                        self._mode = "idle"
                    else:
                        self._mode = "raw"; self._paused = False
                        if not self._timer.isActive(): self._timer.start()
                return {}
            else:
                # point de départ TTFP si pas déjà armé
                if self._ttfp_t0 is None:
                    self._ttfp_t0 = time.perf_counter()
                    self._ttfp_done = False

                arr = np.asarray(seg_in)
                if arr.ndim == 1: arr = arr[None, :]

                n_kw = len(ch_kw) if isinstance(ch_kw, (list, tuple)) else None
                n_known = len(self._last_names) if self._last_names else None

            if arr.ndim == 2:
                n0, n1 = arr.shape; trans = False
                if n_kw is not None: trans = (n1 == n_kw) and (n0 != n_kw)
                elif n_known is not None: trans = (n1 == n_known) and (n0 != n_known)
                else: trans = (n0 > n1)
                if trans: arr = arr.T

                self._last_seg = arr.astype(np.float32, copy=False)
                if isinstance(ch_kw, (list, tuple)) and ch_kw: self._last_names = list(ch_kw)
                else: self._last_names = [f"ch{i+1}" for i in range(self._last_seg.shape[0])]
                sf = args.get("sfreq", None)
                if isinstance(sf, (int, float)): self._last_fs = float(sf)

                self._last_seg, self._last_names = self._apply_force_nch_to_array(self._last_seg, self._last_names)
                self._ensure_seg_buffer(self._last_seg.shape[0], self._last_fs, self._last_names)
                self._append_segment_to_buffer(self._last_seg)

                self._seg_index = int(self._seg_index) + 1

                calc_len = None
                try:
                    if self._last_fs and self._last_seg is not None and self._last_seg.shape[1] > 0:
                        calc_len = float(self._last_seg.shape[1]) / float(self._last_fs)
                except Exception:
                    calc_len = None

                if self._seg_len_auto:
                    self._seg_len_effective = calc_len
                    if (calc_len is not None) and (self._sp_seg_len is not None):
                        self._sp_seg_len.blockSignals(True); self._sp_seg_len.setValue(max(0.0, calc_len)); self._sp_seg_len.blockSignals(False)
                else:
                    if self._seg_len_manual is None and calc_len is not None:
                        self._seg_len_manual = calc_len
                        if self._sp_seg_len is not None:
                            self._sp_seg_len.blockSignals(True); self._sp_seg_len.setValue(calc_len); self._sp_seg_len.blockSignals(False)
                    self._seg_len_effective = float(self._seg_len_manual) if self._seg_len_manual else calc_len

                if self.channel_list:
                    need = (self.channel_list.count() != len(self._last_names)) or (self._ui_ch_names is None)
                    if need:
                        self._snapshot_selection(); self._populate_channels(self._last_names)

                self._mode = "segment"
                if self._timer.isActive(): self._timer.stop()
                if not self._paused: self._schedule_update(mode="segment")

        # MODE RAW
        if "raw" in args:
            new_raw = args.get("raw", None)
            if new_raw is None:
                if self._timer.isActive(): self._timer.stop()
                self._raw = None; self._last_raw_obj_id = None
                self._raw_time_shift = 0.0; self._raw_prev_times_last = None; self._raw_prev_times_first = None
                if self._mode != "segment" and self.axes is not None:
                    self.axes.clear(); self.axes.set_title("No Data"); self.axes.set_xlabel("Temps (s)"); self._maybe_draw(self.canvas)
                    if self.label: self.label.setText("Aucun signal EEG")
            else:
                if self._last_raw_obj_id is not None and id(new_raw) == self._last_raw_obj_id and self._mode == "raw":
                    return {}

                # point de départ TTFP si pas déjà armé
                if self._ttfp_t0 is None:
                    self._ttfp_t0 = time.perf_counter()
                    self._ttfp_done = False

                old_raw = self._raw; changed = (old_raw is None)
                try: new_names_full = list(new_raw.ch_names)
                except Exception: new_names_full = []
                try: new_fs = float(new_raw.info.get("sfreq", 0.0))
                except Exception: new_fs = 0.0

                new_fs = float(new_raw.info.get("sfreq", 0.0))

                if old_raw is not None:
                    try: old_names_full = list(old_raw.ch_names)
                    except Exception: old_names_full = []
                    try: old_fs = float(old_raw.info.get("sfreq", 0.0))
                    except Exception: old_fs = 0.0
                    if (len(new_names_full) != len(old_names_full)) or any(a != b for a, b in zip(new_names_full, old_names_full)): changed = True
                    if abs(new_fs - old_fs) > 1e-9: changed = True

                self._raw = new_raw; self._last_raw_obj_id = id(new_raw)

                new_names = self._apply_force_nch_to_names(new_names_full)
                self._populate_channels(new_names)

                if changed:
                    self._cursor = 0; self._raw_time_shift = 0.0; self._raw_prev_times_last = None; self._raw_prev_times_first = None
                else:
                    try:
                        n_times = int(getattr(self._raw, "n_times", 0))
                        max_win = int(round(self._window_s * new_fs)) if new_fs > 0 else 1
                        if self._cursor < max_win: self._cursor = max(self._cursor, max_win)
                        self._cursor = min(self._cursor, n_times)
                    except Exception:
                        pass

                if self._mode != "segment":
                    self._mode = "raw"; self._paused = False
                    if not self._timer.isActive(): self._timer.start()

        if self._mode == "segment" and self._seg_buf is not None and self._seg_buf_fs > 0 and not self._paused:
            self._schedule_update(mode="segment")
        elif self._mode == "raw" and self._raw is not None and not self._paused:
            self._schedule_update(mode="raw")
        return {}

    # -------------------- UI events --------------------
    def _on_toggle_all(self, _state):
        if not self.channel_list:
            return
        check = Qt.Checked if (self.chk_all and self.chk_all.isChecked()) else Qt.Unchecked
        self.channel_list.blockSignals(True)
        for i in range(self.channel_list.count()):
            self.channel_list.item(i).setCheckState(check)
        self.channel_list.blockSignals(False)
        self._snapshot_selection()
        self._schedule_update(mode=("segment" if self._mode == "segment" else "raw"))

    def _on_item_changed(self, _item):
        if self.chk_all and self.chk_all.isChecked():
            self.chk_all.blockSignals(True)
            self.chk_all.setChecked(False)
            self.chk_all.blockSignals(False)
        self._snapshot_selection()
        self._schedule_update(mode=("segment" if self._mode == "segment" else "raw"))

    # -------------------- popup --------------------
    def _show_large_plot(self):
        if self._popup is not None:
            try:
                self._popup.close()
            except Exception:
                pass
            self._popup = None
            self._pop_canvas = None
            self._pop_ax = None
            self._pop_fullscreen = False
            self._pop_scroll = None

        dialog = QDialog()
        dialog.setWindowTitle("EEG — Vue agrandie")
        layout = QVBoxLayout(dialog)
        tb = QHBoxLayout()
        btn_full = QPushButton("Plein écran")
        btn_close = QPushButton("Fermer")
        tb.addWidget(btn_full)
        tb.addStretch(1)
        tb.addWidget(btn_close)
        layout.addLayout(tb)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        layout.addWidget(scroller, 1)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(0)

        fig = Figure(figsize=(12, 6))
        ax = fig.add_subplot(111)
        canvas = FigureCanvas(fig)
        cl.addWidget(canvas)
        scroller.setWidget(content)
        dialog.setLayout(layout)

        self._popup = dialog
        self._pop_canvas = canvas
        self._pop_ax = ax
        self._pop_fullscreen = False
        self._pop_scroll = scroller

        try:
            if self._mode == "segment" and self._seg_buf is not None and self._seg_buf_fs > 0:
                names = self._seg_buf_names if self._seg_buf_names else [f"ch{i+1}" for i in range(self._seg_buf.shape[0])]
                if self.channel_list and self.channel_list.count() == 0:
                    self._populate_channels(names)
                picks = self._selected_indices(all_names=names)
                picks = [i for i in picks if 0 <= i < self._seg_buf.shape[0]]
                if picks:
                    data = self._seg_buf[picks, :]
                    fs = float(self._seg_buf_fs or 0.0)
                    t = (np.arange(data.shape[1]) / fs) if fs > 0 else np.arange(data.shape[1])
                    sel = [names[i] for i in picks]
                    if self._seg_len_effective is not None and self._seg_len_effective > 0:
                        seg_len_txt = f", {self._seg_len_effective:.2f}s"
                    else:
                        seg_len_txt = ""
                    if self._seg_total is not None:
                        seg_txt = f"EEG (segment {self._seg_index}/{self._seg_total}{seg_len_txt})"
                    else:
                        seg_txt = f"EEG (segment {self._seg_index}/?{seg_len_txt})"
                    self._plot_data(data, t, sel, title_prefix=seg_txt)
            elif self._mode == "raw" and self._raw is not None:
                raw = self._raw
                sfreq = float(raw.info.get("sfreq", 0.0))
                n_times = int(getattr(raw, "n_times", 0))
                N = max(1, int(round(self._window_s * sfreq)))
                stop = min(max(self._cursor, N), n_times)
                start = max(0, stop - N)
                try:
                    names_full = list(raw.ch_names)
                except Exception:
                    names_full = None
                picks = self._selected_indices(all_names=names_full)
                if self._force_nch and self._force_nch > 0:
                    picks = [i for i in picks if i < min(self._force_nch, len(names_full or []))]
                if picks:
                    data, times = raw[picks, start:stop]
                    if data.size:
                        if self._raw_prev_times_last is not None and times[0] <= 1e-9:
                            self._raw_time_shift = float(self._raw_prev_times_last)
                        abs_times = times + self._raw_time_shift
                    else:
                        abs_times = times
                    names_for_ui = self._apply_force_nch_to_names(names_full or [])
                    sel = [names_for_ui[i] if 0 <= i < len(names_for_ui) else f"ch{i+1}" for i in picks]
                    self._plot_data(data, abs_times, sel, title_prefix="EEG Live")
        except Exception:
            pass

        btn_full.clicked.connect(lambda: self._toggle_fullscreen(btn_full))
        btn_close.clicked.connect(dialog.close)
        dialog.showMaximized()
        self._update_plot(flush_only=True, force_mode=self._mode)

        def _on_finish(*a):
            self._pop_canvas = None
            self._pop_ax = None
            self._popup = None
            self._pop_fullscreen = False
            self._pop_scroll = None

        dialog.finished.connect(_on_finish)

    def _toggle_fullscreen(self, btn_full):
        if not self._popup:
            return
        if not self._pop_fullscreen:
            self._popup.showFullScreen()
            self._pop_fullscreen = True
            btn_full.setText("Fenêtré")
        else:
            self._popup.showMaximized()
            self._pop_fullscreen = False
            btn_full.setText("Plein écran")

    # -------------------- cleanup --------------------
    def _on_destroy(self, *_):
        try:
            if self._timer.isActive(): self._timer.stop()
        except Exception:
            pass
        try:
            if self._popup is not None: self._popup.close()
        except Exception:
            pass
        self._popup = None; self._pop_canvas = None; self._pop_ax = None; self._pop_scroll = None

    def on_remove(self):
        self._on_destroy()
        self._raw = None; self._last_raw_obj_id = None
        self._reset_segment_buffer()
        try:
            if self._stat_timer.isActive():
                self._stat_timer.stop()
        except Exception:
            pass

    # -------------------- stats périodiques --------------------
    def _emit_render_stats(self):
        try:
            dt = max(1e-6, time.monotonic() - self._last_stat_t)
            frames = self._frames_rendered
            total   = frames + self._frames_dropped
            fps     = frames / dt
            drop_pct = (100.0 * self._frames_dropped / total) if total > 0 else 0.0

            # --- n_ch (canaux effectivement affichés)
            if self.channel_list and self.channel_list.count() > 0:
                picks = self._selected_indices(all_names=self._ui_ch_names or [])
                n_ch = len(picks)
            elif self._mode == "segment" and self._seg_buf is not None:
                n_ch = int(self._seg_buf.shape[0])
            elif self._raw is not None:
                try: n_ch = len(self._raw.ch_names)
                except Exception: n_ch = 0
            else:
                n_ch = 0

            # --- points (par trace)
            if self._mode == "segment" and self._seg_buf is not None:
                points = int(self._seg_buf.shape[1])
            else:
                fs = float(self._last_fs or 0.0)
                if fs <= 0.0 and self._raw is not None:
                    try: fs = float(self._raw.info.get("sfreq", 0.0))
                    except Exception: fs = 0.0
                points = int(round(max(0.0, self._window_s) * max(0.0, fs)))
                points = min(points, int(self._max_points or points))

            throughput_sps = float(n_ch * points * fps) if (n_ch > 0 and points > 0 and fps > 0.0) else 0.0

            # --- EMIT: toujours inclure throughput_sps
            metrics().event(
                "RENDER_STATS",
                fps=f"{fps:.2f}",
                dropped_frames=self._frames_dropped,
                total_frames=total,
                dropped_frames_pct=f"{drop_pct:.2f}",
                throughput_sps=f"{throughput_sps:.0f}",
            )
        except Exception:
            pass
        finally:
            self._frames_rendered = 0
            self._frames_dropped = 0
            self._last_stat_t = time.monotonic()