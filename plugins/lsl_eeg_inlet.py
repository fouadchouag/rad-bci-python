# plugins/lsl_eeg_inlet.py
# -*- coding: utf-8 -*-

import os, threading, time, numpy as np
from collections import deque
from rx.subject import BehaviorSubject

os.environ.setdefault("LSL_NO_IPV6", "1")  # réduit warnings sous Windows

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QDoubleSpinBox,
    QSpinBox, QSizePolicy, QStyle
)
from PyQt5.QtCore import Qt, QTimer

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    from pylsl import resolve_byprop, StreamInlet
    LSL_OK = True
except Exception:
    LSL_OK = False


class LSL_EEG_Inlet(BasePlugin):
    """
    Inlet LSL générique pour flux EEG (float32, multi-canaux).

    Sorties:
      - data       : np.ndarray shape (N, C) float32 (chunk agrégé depuis le dernier tick)
      - sfreq      : float (Hz)
      - ch_names   : list[str]
      - timestamps : np.ndarray shape (N,) float64 (temps LSL abs)
      - last_ts    : float (timestamp LSL du dernier échantillon)

    UI:
      - choix du stream par nom (type='EEG'), refresh, connect, chunk_ms, emit_ms, buffer_max_s
    """
    name = "LSL_EEG_Inlet"
    language = "Python"
    category = "I/O"

    # -------- lifecycle --------
    def setup(self):
        # outputs
        self.outputs["data"]       = BehaviorSubject(None)
        self.outputs["sfreq"]      = BehaviorSubject(None)
        self.outputs["ch_names"]   = BehaviorSubject(None)
        self.outputs["timestamps"] = BehaviorSubject(None)
        self.outputs["last_ts"]    = BehaviorSubject(None)

        # state
        self._inlet = None
        self._reader = None
        self._run = False
        self._buf_x = deque(maxlen=0)   # list of small arrays (n,c)
        self._buf_t = deque(maxlen=0)   # list of small vectors (n,)
        self._sfreq = None
        self._ch_names = None
        self._chunk_ms = 20
        self._emit_ms  = 50
        self._buf_max_s = 5.0
        self._combo = None
        self._lbl = None
        self._timer = None

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Stream (type=EEG):"))
        self._combo = QComboBox(); r0.addWidget(self._combo, 1)
        btn_refresh = UiKit.make_btn("Refresh", role="ghost", icon_sp=QStyle.SP_BrowserReload)
        btn_refresh.clicked.connect(self._refresh_streams); r0.addWidget(btn_refresh)
        btn_conn = UiKit.make_btn("Connect", role="primary", icon_sp=QStyle.SP_DialogYesButton)
        btn_conn.clicked.connect(self._connect); r0.addWidget(btn_conn)
        btn_disc = UiKit.make_btn("Disconnect", role="danger", icon_sp=QStyle.SP_DialogCancelButton)
        btn_disc.clicked.connect(self._disconnect); r0.addWidget(btn_disc)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("chunk [ms]:"))
        sp_chunk = QSpinBox(); sp_chunk.setRange(2, 200); sp_chunk.setValue(self._chunk_ms)
        sp_chunk.valueChanged.connect(lambda v: setattr(self, "_chunk_ms", int(v))); r1.addWidget(sp_chunk)
        r1.addSpacing(12)
        r1.addWidget(QLabel("emit [ms]:"))
        sp_emit = QSpinBox(); sp_emit.setRange(5, 500); sp_emit.setValue(self._emit_ms)
        sp_emit.valueChanged.connect(self._on_emit_ms_changed); r1.addWidget(sp_emit)
        r1.addSpacing(12)
        r1.addWidget(QLabel("buffer max [s]:"))
        sp_buf = QDoubleSpinBox(); sp_buf.setRange(0.5, 60.0); sp_buf.setDecimals(1); sp_buf.setValue(self._buf_max_s)
        sp_buf.valueChanged.connect(self._on_bufmax_changed); r1.addWidget(sp_buf)
        r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel("LSL: " + ("OK" if LSL_OK else "missing")); v.addWidget(self._lbl)

        root.addWidget(CollapsibleSection("LSL EEG Inlet", panel, collapsed=False))

        # timer emission
        self._timer = QTimer(w)
        self._timer.timeout.connect(self._emit_tick)
        self._timer.start(self._emit_ms)

        # init streams list
        self._refresh_streams()

        return w

    # -------- UI handlers --------
    def _on_emit_ms_changed(self, v):
        self._emit_ms = int(v)
        if self._timer:
            self._timer.setInterval(self._emit_ms)

    def _on_bufmax_changed(self, v):
        self._buf_max_s = float(v)
        self._update_deque_limits()

    def _update_deque_limits(self):
        # taille max en échantillons ≈ sfreq * buf_max_s (si sfreq connu)
        if self._sfreq:
            maxlen = int(max(1, self._sfreq * self._buf_max_s / max(1, int(self._chunk_ms)/1000.0)))
            self._buf_x = deque(self._buf_x, maxlen=maxlen)
            self._buf_t = deque(self._buf_t, maxlen=maxlen)

    def _refresh_streams(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing. pip install pylsl")
            return
        try:
            infos = resolve_byprop('type', 'EEG', timeout=1.0)
            names = [inf.name() for inf in infos]
            self._combo.clear()
            if names:
                self._combo.addItems(names)
            else:
                self._combo.addItem("(no EEG streams)")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Resolve error: {e}")

    # -------- LSL connect/threads --------
    def _connect(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing.")
            return
        try:
            name = self._combo.currentText().strip()
            infos = resolve_byprop('name', name, timeout=1.5) if name and "(no EEG" not in name else resolve_byprop('type','EEG',timeout=1.5)
            if not infos:
                if self._lbl: self._lbl.setText("No matching EEG stream.")
                return
            info = infos[0]
            self._inlet = StreamInlet(info, max_buflen=60, processing_flags=0)
            # meta
            self._sfreq = float(info.nominal_srate())
            self._ch_names = self._parse_ch_labels(info)
            self.outputs["sfreq"].on_next(self._sfreq)
            self.outputs["ch_names"].on_next(list(self._ch_names))
            # buffers
            self._buf_x.clear(); self._buf_t.clear()
            self._update_deque_limits()
            # thread
            self._run = True
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            if self._lbl: self._lbl.setText(f"Connected to {info.name()} | fs={self._sfreq:.1f} | C={len(self._ch_names)}")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Connect error: {e}")

    def _disconnect(self):
        self._run = False
        try:
            if self._reader and self._reader.is_alive():
                self._reader.join(timeout=0.5)
        except Exception:
            pass
        self._reader = None
        self._inlet = None
        if self._lbl: self._lbl.setText("Disconnected.")

    def _read_loop(self):
        # lit en petits chunks et empile dans les deques
        while self._run and (self._inlet is not None):
            try:
                if not self._sfreq:
                    fs = 250.0
                else:
                    fs = self._sfreq
                nmax = max(1, int(fs * (self._chunk_ms/1000.0)))
                samples, stamps = self._inlet.pull_chunk(timeout=0.2, max_samples=nmax)
                if samples and stamps:
                    arr = np.asarray(samples, dtype=np.float32)
                    ts  = np.asarray(stamps, dtype=np.float64)
                    # sécurité sur shape (N, C)
                    if arr.ndim == 1:
                        arr = arr[None, :]
                    self._buf_x.append(arr)
                    self._buf_t.append(ts)
                else:
                    # petit sleep pour ne pas brûler CPU
                    time.sleep(0.002)
            except Exception:
                time.sleep(0.01)

    def _emit_tick(self):
        # agrège tout depuis le dernier tick et publie
        if (len(self._buf_x) == 0) or (len(self._buf_t) == 0):
            return
        try:
            X = np.concatenate(list(self._buf_x), axis=0); self._buf_x.clear()
            T = np.concatenate(list(self._buf_t), axis=0); self._buf_t.clear()
        except Exception:
            return
        try:
            self.outputs["data"].on_next(X)
            self.outputs["timestamps"].on_next(T)
            if len(T):
                self.outputs["last_ts"].on_next(float(T[-1]))
        except Exception:
            pass

    # -------- helpers --------
    @staticmethod
    def _parse_ch_labels(info):
        labels=[]
        try:
            desc = info.desc().child("channels").first_child()
            while not desc.empty():
                lab = desc.child_value("label")
                labels.append(lab if lab else f"ch{len(labels)}")
                desc = desc.next_sibling()
        except Exception:
            pass
        if not labels:
            labels = [f"ch{i}" for i in range(info.channel_count())]
        return labels

    # node engine does not call execute() periodically for inputs (none). We emit via QTimer.
    def execute(self, **kw):
        return {}
