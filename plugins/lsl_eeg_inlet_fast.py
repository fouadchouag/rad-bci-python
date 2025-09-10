# plugins/lsl_eeg_inlet_fast.py
# -*- coding: utf-8 -*-

import threading, time, numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QSizePolicy, QStyle, QCheckBox
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
    # Ui helpers
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# --- utils temps réel (fallback local si core.rt_perf absent) ---
try:
    from core.rt_perf import DropOldQueue, start_qtimer
except Exception:
    from PyQt5.QtCore import QTimer
    class DropOldQueue:
        

        def __init__(self): 
            import threading
            self._lock=threading.Lock(); self._item=None
        def put(self, x):
            with self._lock: self._item=x
        def get_nowait(self):
            with self._lock:
                x=self._item; self._item=None
                return x
    def start_qtimer(interval_ms, callback, parent=None):
        t = QTimer(parent); t.setInterval(int(interval_ms)); t.timeout.connect(callback); t.start()
        return t

try:
    from pylsl import resolve_byprop, StreamInlet
    LSL_OK = True
except Exception:
    LSL_OK = False


class LSL_EEG_Inlet_Fast(BasePlugin):
    """
    Inlet EEG non-bloquant :
      - Thread lecteur (chunks 20–40 ms) → Drop queue (taille 1)
      - QTimer (100 ms par défaut) → push 'data' (N x C, float32)
    UI :
      - Refresh liste des streams EEG
      - Connect / Disconnect
      - Reglages emit_ms, chunk_ms, autoconnect
    Sorties :
      - data (np.float32, n_samples x n_channels)
      - sfreq (float), ch_names (list[str])
      - config_out (dict)

    Entrées config :
      - config_in (dict), lsl_eeg_conf (dict)
    """

    help = help = { 'gotchas': [ 'Verify channels and sampling rate.',
               'Network hiccups may cause gaps—use buffering.'],
  'inputs': {},
  'outputs': { 'ch_names': 'List[str]',
               'segment': '2D float [ch x samples]',
               'sfreq': 'float (Hz)'},
  'parameters': [ { 'default': 'EEG',
                    'desc': 'LSL stream name to subscribe to',
                    'name': 'stream_name',
                    'type': 'str'},
                  { 'default': 256,
                    'desc': 'Samples per pull',
                    'name': 'chunk_size',
                    'type': 'int'},
                  { 'default': 0.1,
                    'desc': 'Pull timeout',
                    'name': 'timeout',
                    'type': 'float',
                    'unit': 's'}],
  'summary': 'Inlet EEG non-bloquant :',
  'usage': 'Start external LSL stream; connect this inlet to processing pipeline.'}
    
    name = "LSL_EEG_Inlet_Fast"
    language = "Python"
    category = "Input Nodes"

    # ---------- lifecycle ----------
    def setup(self):
        # outputs
        self.outputs["data"] = BehaviorSubject(None)
        self.outputs["sfreq"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # config inputs
        self.inputs["config_in"] = BehaviorSubject(None)
        self.inputs["lsl_eeg_conf"] = BehaviorSubject(None)

        # state
        self._emit_ms = 100
        self._chunk_ms = 20
        self._streams = []      # [(name, info), ...]
        self._sel_name = None
        self._reader_th = None
        self._stop = False
        self._q = DropOldQueue()
        self._sf = None
        self._nch = None
        self._timer = None
        self._autoconnect = False

        # ui refs
        self._lbl = None
        self._cmb = None
        self._btn_conn = None
        self._sp_emit = None
        self._sp_chunk = None
        self._ck_auto = None

    # ---------- config ----------
    def export_config(self) -> dict:
        return {
            "emit_ms": int(self._emit_ms),
            "chunk_ms": int(self._chunk_ms),
            "stream_name": str(self._sel_name or ""),
            "autoconnect": bool(self._autoconnect),
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        if "emit_ms" in cfg:
            try:
                self._emit_ms = int(cfg["emit_ms"])
                if self._sp_emit: self._sp_emit.setValue(self._emit_ms)
                if self._timer: self._start_timer()
            except Exception: pass
        if "chunk_ms" in cfg:
            try:
                self._chunk_ms = int(cfg["chunk_ms"])
                if self._sp_chunk: self._sp_chunk.setValue(self._chunk_ms)
            except Exception: pass
        if "stream_name" in cfg and isinstance(cfg["stream_name"], str):
            nm = cfg["stream_name"].strip()
            if nm:
                self._sel_name = nm
                if self._cmb:
                    idx = self._cmb.findText(nm)
                    if idx >= 0: self._cmb.setCurrentIndex(idx)
        if "autoconnect" in cfg:
            self._autoconnect = bool(cfg["autoconnect"])
            if self._ck_auto: self._ck_auto.setChecked(self._autoconnect)
        # auto-connect si demandé
        if self._autoconnect and (self._reader_th is None or not self._reader_th.is_alive()):
            self._connect()
        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- UI ----------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        # Row: stream select + Refresh + Connect
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Stream EEG:"))
        self._cmb = QComboBox(); r0.addWidget(self._cmb, 1)
        btn_ref = UiKit.make_btn("Refresh", role="ghost", icon_sp=QStyle.SP_BrowserReload)
        btn_ref.clicked.connect(self._on_refresh); r0.addWidget(btn_ref)
        self._btn_conn = UiKit.make_btn("Connect", role="primary", icon_sp=QStyle.SP_ComputerIcon, checkable=True)
        self._btn_conn.clicked.connect(self._on_toggle_conn); r0.addWidget(self._btn_conn)
        v.addLayout(r0)

        # Row: timings
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("emit_ms:"))
        self._sp_emit = QSpinBox(); self._sp_emit.setRange(10, 2000); self._sp_emit.setValue(self._emit_ms)
        self._sp_emit.valueChanged.connect(lambda x: self._on_change_emit(int(x)))
        r1.addWidget(self._sp_emit)

        r1.addSpacing(8); r1.addWidget(QLabel("chunk_ms:"))
        self._sp_chunk = QSpinBox(); self._sp_chunk.setRange(5, 200); self._sp_chunk.setValue(self._chunk_ms)
        self._sp_chunk.valueChanged.connect(lambda x: self._on_change_chunk(int(x)))
        r1.addWidget(self._sp_chunk)

        self._ck_auto = QCheckBox("autoconnect"); self._ck_auto.setChecked(self._autoconnect)
        self._ck_auto.toggled.connect(self._on_toggle_auto)
        r1.addWidget(self._ck_auto)

        r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel("LSL: " + ("OK" if LSL_OK else "missing") + " | idle")
        v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("LSL EEG Fast", panel, collapsed=True))

        # do one refresh
        self._on_refresh()
        # emit initial config
        self._emit_config()
        return w

    def _on_toggle_auto(self, s: bool):
        self._autoconnect = bool(s)
        self._emit_config()
        if self._autoconnect and (self._reader_th is None or not self._reader_th.is_alive()):
            self._connect()

    def _on_change_emit(self, v: int):
        self._emit_ms = int(v)
        if self._timer: self._start_timer()
        self._emit_config()

    def _on_change_chunk(self, v: int):
        self._chunk_ms = int(v)
        self._emit_config()

    # ---------- UI handlers ----------
    def _on_refresh(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing (pip install pylsl)")
            return
        try:
            infos_type = resolve_byprop('type', 'EEG', timeout=1.0)
            infos_any  = resolve_byprop('type', '', timeout=0.2)  # parfois type non renseigné
            seen = {}
            for inf in (infos_type or []):
                seen[inf.name()] = inf
            for inf in (infos_any or []):
                nm = inf.name()
                if ('EEG' in (inf.type() or '').upper()) or nm.upper().endswith('_EEG'):
                    seen.setdefault(nm, inf)
            self._streams = sorted([(nm, inf) for nm,inf in seen.items()], key=lambda t: t[0].lower())
            self._cmb.blockSignals(True); self._cmb.clear()
            for nm,_ in self._streams:
                self._cmb.addItem(nm)
            self._cmb.blockSignals(False)
            if self._streams:
                if self._sel_name:
                    idx = self._cmb.findText(self._sel_name)
                    self._cmb.setCurrentIndex(idx if idx >= 0 else 0)
                else:
                    self._sel_name = self._streams[0][0]
                    self._cmb.setCurrentIndex(0)
                if self._lbl: self._lbl.setText(f"Found {len(self._streams)} EEG streams. Selected: {self._sel_name}")
            else:
                self._sel_name = None
                if self._lbl: self._lbl.setText("No EEG stream found.")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Refresh error: {e}")

        self._cmb.currentTextChanged.connect(lambda s: setattr(self, "_sel_name", s) or self._emit_config())

    def _on_toggle_conn(self, checked):
        if checked:
            ok = self._connect()
            if not ok:
                self._btn_conn.blockSignals(True); self._btn_conn.setChecked(False); self._btn_conn.blockSignals(False)
        else:
            self._disconnect()

    # ---------- connect / disconnect ----------
    def _connect(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing.")
            return False
        if not self._sel_name:
            if self._lbl: self._lbl.setText("Select a stream first.")
            return False
        if self._reader_th and self._reader_th.is_alive():
            if self._lbl: self._lbl.setText("Already connected.")
            return True

        self._stop = False
        self._q = DropOldQueue()
        self._reader_th = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_th.start()
        self._start_timer()
        if self._lbl: self._lbl.setText(f"Connected to {self._sel_name}")
        self._btn_conn.setText("Disconnect")
        self._emit_config()
        return True

    def _disconnect(self):
        self._stop = True
        if self._timer:
            self._timer.stop(); self._timer=None
        th = self._reader_th
        self._reader_th = None
        if th:
            try:
                th.join(timeout=0.8)
            except Exception:
                pass
        self._btn_conn.setText("Connect")
        if self._lbl: self._lbl.setText("Disconnected.")

    def on_stop(self):
        self._disconnect()

    # ---------- reader & drain ----------
    def _reader_loop(self):
        try:
            info = None
            for nm,inf in self._streams:
                if nm == self._sel_name:
                    info = inf; break
            if info is None:
                from pylsl import resolve_byprop
                lst = resolve_byprop('name', self._sel_name, timeout=3.0)
                info = lst[0] if lst else None
            if info is None:
                if self._lbl: self._lbl.setText("Stream not found at connect.")
                return

            inlet = StreamInlet(info, max_buflen=60, processing_flags=0)
            sf = float(info.nominal_srate())
            nch = int(info.channel_count())
            self._sf, self._nch = sf, nch
            try:
                ch_names = []
                desc = info.desc()
                if desc.child("channels").first_child():
                    ch = desc.child("channels").first_child()
                    while True:
                        ch_names.append(ch.child_value("label") or f"Ch{len(ch_names)+1}")
                        ch = ch.next_sibling()
                        if ch.empty(): break
                if not ch_names:
                    ch_names = [f"Ch{i+1}" for i in range(nch)]
            except Exception:
                ch_names = [f"Ch{i+1}" for i in range(nch)]
            self.outputs["sfreq"].on_next(sf)
            self.outputs["ch_names"].on_next(ch_names)

            while not self._stop:
                chunk = max(1, int(sf * (self._chunk_ms/1000.0)))
                X, ts = inlet.pull_chunk(max_samples=chunk, timeout=0.0)
                if X:
                    arr = np.asarray(X, dtype=np.float32)
                    if arr.ndim == 1: arr = arr[None, :]
                    self._q.put(arr)
                time.sleep(self._chunk_ms/1000.0)
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Reader error: {e}")

    def _start_timer(self):
        if self._timer:
            self._timer.stop()
        self._timer = start_qtimer(self._emit_ms, self._drain)

    def _drain(self):
        arr = self._q.get_nowait()
        if arr is None: return
        try:
            self.outputs["data"].on_next(arr)
            if self._lbl and self._sf:
                self._lbl.setText(f"{self._sel_name}: {arr.shape} @ {self._sf:.1f} Hz")
        except Exception:
            pass

    # ---------- runtime (unused) ----------
    def execute(self, **kw):
        merged = {}
        c1 = kw.get("config_in"); c2 = kw.get("lsl_eeg_conf")
        if isinstance(c1, dict): merged.update(c1)
        if isinstance(c2, dict): merged.update(c2)
        if merged: self.import_config(merged)
        return {}