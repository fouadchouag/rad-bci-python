# plugins/lsl_inlet_plugin.py
# -*- coding: utf-8 -*-
"""
LSL Inlet — compatible LiveDisplay / SliceFilter
Sorties:
  - segment     : np.ndarray (n_ch, n_samples)
  - timestamps  : list[float]
  - info        : dict {name,type,uid,n_channels,sfreq,ch_names,reset}
  - sfreq       : float
  - ch_names    : list[str]
"""

import threading
import time
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox,
    QLayout, QSizePolicy, QStyle
)
from PyQt5.QtCore import QObject, pyqtSignal, Qt

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# pylsl
try:
    from pylsl import StreamInlet, resolve_streams
except Exception:
    StreamInlet = None
    resolve_streams = None


# ---------- Bridge Qt (retour thread -> GUI) ----------
class _QtBridge(QObject):
    sig_info = pyqtSignal(dict)                    # info dict
    sig_chunk = pyqtSignal(object, object)         # (arr, timestamps)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._emit_info_cb = None
        self._emit_chunk_cb = None

    def connect_callbacks(self, emit_info_cb, emit_chunk_cb):
        self._emit_info_cb = emit_info_cb
        self._emit_chunk_cb = emit_chunk_cb
        self.sig_info.connect(self._on_info, Qt.QueuedConnection)
        self.sig_chunk.connect(self._on_chunk, Qt.QueuedConnection)

    def _on_info(self, info: dict):
        if callable(self._emit_info_cb):
            self._emit_info_cb(info)

    def _on_chunk(self, arr, timestamps):
        if callable(self._emit_chunk_cb):
            self._emit_chunk_cb(arr, timestamps)


# ===================== Plugin =========================
class LSLInletPlugin(BasePlugin):
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
  'summary': 'LSL Inlet — compatible LiveDisplay / SliceFilter',
  'usage': 'Start external LSL stream; connect this inlet to processing pipeline.'}

    name = "LSL Inlet"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True

    # ---------- lifecycle ----------
    def setup(self):
        self.outputs = {
            "segment": BehaviorSubject(None),
            "timestamps": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }

        self._stream_infos = []
        self._inlet = None
        self._reader_thr = None
        self._running = False
        self._chunk_len = 50

        # cache méta
        self._sfreq = 0.0
        self._ch_names = []

        # UI refs
        self.cmb_streams = None
        self.btn_refresh = None
        self.btn_connect = None
        self.btn_disconnect = None
        self.spn_chunk = None
        self.lbl_status = None

        # Bridge Qt
        self._bridge = _QtBridge()
        self._bridge.connect_callbacks(self._emit_info_gui, self._emit_chunk_gui)

    def execute(self, inputs=None):
        return {}  # nœud source

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget()
        UiKit.apply_node_style(w)
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if StreamInlet is None or resolve_streams is None:
            msg = QLabel("❌ pylsl indisponible — installez-le:  pip install pylsl")
            root.addWidget(msg)
            return w

        # Panneau repliable (tout dedans)
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # Ligne: liste des streams + actions
        row1 = QHBoxLayout()
        self.cmb_streams = QComboBox(); row1.addWidget(self.cmb_streams, 1)
        self.btn_refresh = UiKit.make_btn("Rechercher", icon_sp=QStyle.SP_BrowserReload); row1.addWidget(self.btn_refresh)
        self.btn_connect = UiKit.make_btn("Connecter", role="primary", icon_sp=QStyle.SP_MediaPlay); row1.addWidget(self.btn_connect)
        self.btn_disconnect = UiKit.make_btn("Stop", role="danger", icon_sp=QStyle.SP_MediaStop); self.btn_disconnect.setEnabled(False); row1.addWidget(self.btn_disconnect)
        v.addLayout(row1)

        # Ligne: chunk + statut
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Chunk len (samples):"))
        self.spn_chunk = QSpinBox(); self.spn_chunk.setRange(1, 4096); self.spn_chunk.setValue(self._chunk_len)
        row2.addWidget(self.spn_chunk)
        self.lbl_status = QLabel("Statut: idle"); row2.addWidget(self.lbl_status, 1)
        v.addLayout(row2)

        root.addWidget(CollapsibleSection("Paramètres & Statut", panel, collapsed=True))

        # Connexions
        self.btn_refresh.clicked.connect(self._refresh_streams)
        self.btn_connect.clicked.connect(self._start)
        self.btn_disconnect.clicked.connect(self._stop)
        self.spn_chunk.valueChanged.connect(lambda v: setattr(self, "_chunk_len", int(v)))

        self._refresh_streams()
        return w

    # ---------- Logic ----------
    def _set_status(self, s: str):
        if self.lbl_status:
            self.lbl_status.setText(f"Statut: {s}")

    def _refresh_streams(self):
        try:
            self._stream_infos = resolve_streams(wait_time=1.0)
            self.cmb_streams.clear()
            for info in self._stream_infos:
                label = f"{info.name()} [{info.type()}] ({info.source_id()})"
                self.cmb_streams.addItem(label)
            self._set_status(f"{len(self._stream_infos)} stream(s) trouvé(s)")
        except Exception as e:
            self._set_status(f"Erreur scan LSL: {e}")

    def _start(self):
        if self._running or not self._stream_infos:
            return
        idx = self.cmb_streams.currentIndex()
        if idx < 0:
            self._set_status("Aucun stream sélectionné")
            return

        try:
            info = self._stream_infos[idx]
            self._inlet = StreamInlet(info, max_chunklen=self._chunk_len)

            ch_count = int(info.channel_count())
            sfreq = float(info.nominal_srate() or 0.0)
            name = info.name()
            stype = info.type()
            uid = info.source_id()

            # labels de canaux (si fournis)
            ch_names = []
            try:
                node = info.desc().child("channels").first_child()
                while node.name():
                    lab = node.child_value("label")
                    ch_names.append(lab if lab else f"ch{len(ch_names)+1}")
                    node = node.next_sibling()
            except Exception:
                ch_names = [f"ch{i+1}" for i in range(ch_count)]

            # méta -> GUI (reset=True attendu par LiveDisplay)
            self._bridge.sig_info.emit({
                "sfreq": sfreq,
                "ch_names": ch_names,
                "name": name,
                "type": stype,
                "uid": uid,
                "n_channels": ch_count,
                "reset": True,
            })

            self._running = True
            if self.btn_connect: self.btn_connect.setEnabled(False)
            if self.btn_disconnect: self.btn_disconnect.setEnabled(True)
            self._set_status(f"Connecté à {name} [{stype}] • {ch_count} ch @ {sfreq:.1f} Hz")

            self._reader_thr = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thr.start()

        except Exception as e:
            self._set_status(f"Erreur connexion LSL: {e}")
            self._running = False
            self._inlet = None

    def _reader_loop(self):
        while self._running and self._inlet is not None:
            try:
                samples, timestamps = self._inlet.pull_chunk(timeout=0.2, max_samples=self._chunk_len)
                if samples and len(samples) > 0:
                    # -> (n_samples, n_channels) -> transpose
                    arr = np.asarray(samples, dtype=np.float64).T
                    self._bridge.sig_chunk.emit(arr, timestamps)
                else:
                    time.sleep(0.01)
            except Exception as e:
                self._set_status(f"Erreur lecture: {e}")
                break

        self._cleanup_inlet()
        self._set_status("idle")
        # notifier la chaîne que le flux s'arrête
        self._bridge.sig_chunk.emit(None, None)

    # ---- Emission côté GUI ----
    def _emit_info_gui(self, info: dict):
        # mémos + sorties dédiées
        self._sfreq = float(info.get("sfreq", 0.0)) if isinstance(info.get("sfreq", None), (int, float)) else 0.0
        self._ch_names = list(info.get("ch_names", [])) if isinstance(info.get("ch_names", None), (list, tuple)) else []
        if self._sfreq > 0:
            self.outputs["sfreq"].on_next(self._sfreq)
        if self._ch_names:
            self.outputs["ch_names"].on_next(self._ch_names)
        # info global
        self.outputs["info"].on_next(info)

    def _emit_chunk_gui(self, arr, timestamps):
        if arr is None:
            # arrêt / déconnexion
            self.outputs["segment"].on_next(None)
            self.outputs["timestamps"].on_next(None)
            return
        self.outputs["segment"].on_next(arr)
        self.outputs["timestamps"].on_next(list(timestamps) if timestamps is not None else None)

    # ---- Stop / cleanup ----
    def _stop(self):
        self._running = False
        if self.btn_connect: self.btn_connect.setEnabled(True)
        if self.btn_disconnect: self.btn_disconnect.setEnabled(False)

    def _cleanup_inlet(self):
        try:
            if self._inlet is not None:
                self._inlet.close_stream()
        except Exception:
            pass
        self._inlet = None

    def on_remove(self):
        self._running = False
        self._cleanup_inlet()