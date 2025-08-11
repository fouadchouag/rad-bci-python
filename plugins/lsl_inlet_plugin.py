# plugins/lsl_inlet_plugin.py
import threading
import time
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSpinBox
)
from PyQt5.QtCore import QObject, pyqtSignal, Qt

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

# Import explicite pylsl
try:
    from pylsl import StreamInlet, resolve_streams
except Exception:
    StreamInlet = None
    resolve_streams = None


class _QtBridge(QObject):
    """Porte d'entrée vers le thread GUI. On émet depuis le worker,
    Qt queue le signal et appelle les slots ci-dessous dans le thread UI."""
    sig_info = pyqtSignal(dict)
    sig_chunk = pyqtSignal(object, object)  # (arr, timestamps)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._emit_info_cb = None
        self._emit_chunk_cb = None

    def connect_callbacks(self, emit_info_cb, emit_chunk_cb):
        self._emit_info_cb = emit_info_cb
        self._emit_chunk_cb = emit_chunk_cb
        # Forcer l'exécution dans le thread GUI
        self.sig_info.connect(self._on_info, Qt.QueuedConnection)
        self.sig_chunk.connect(self._on_chunk, Qt.QueuedConnection)

    def _on_info(self, info: dict):
        if callable(self._emit_info_cb):
            self._emit_info_cb(info)

    def _on_chunk(self, arr, timestamps):
        if callable(self._emit_chunk_cb):
            self._emit_chunk_cb(arr, timestamps)


class LSLInletPlugin(BasePlugin):
    name = "LSL Inlet"
    category = "Input Nodes"

    def setup(self):
        # IMPORTANT : pour compat LiveDisplay, on émet 'segment' (et pas 'chunk')
        self.inputs = {}
        self.outputs = {
            "segment": BehaviorSubject(None),       # np.ndarray (n_channels, n_samples)
            "timestamps": BehaviorSubject(None),    # list[float]
            "info": BehaviorSubject(None),          # dict meta
        }

        self._stream_infos = []
        self._inlet = None
        self._reader_thr = None
        self._running = False
        self._chunk_len = 50
        self._status_cb = None

        # Bridge vers le thread GUI
        self._bridge = _QtBridge()
        self._bridge.connect_callbacks(self._emit_info_gui, self._emit_chunk_gui)

    def execute(self, inputs=None):
        return  # nœud source

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        if StreamInlet is None or resolve_streams is None:
            msg = QLabel(
                "❌ LSL indisponible. Installe pylsl :\n"
                "    pip install pylsl\n"
                "Ensuite relance l’application."
            )
            v.addWidget(msg)
            return w

        top = QHBoxLayout()
        self.cmb_streams = QComboBox()
        self.btn_refresh = QPushButton("🔎 Rechercher")
        self.btn_connect = QPushButton("▶️ Connecter")
        self.btn_disconnect = QPushButton("⏹️ Stop")
        self.btn_disconnect.setEnabled(False)

        top.addWidget(self.cmb_streams, 1)
        top.addWidget(self.btn_refresh)
        top.addWidget(self.btn_connect)
        top.addWidget(self.btn_disconnect)
        v.addLayout(top)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Chunk len (samples):"))
        self.spn_chunk = QSpinBox()
        self.spn_chunk.setRange(1, 4096)
        self.spn_chunk.setValue(self._chunk_len)
        row2.addWidget(self.spn_chunk)
        self.lbl_status = QLabel("Statut: idle")
        row2.addWidget(self.lbl_status, 1)
        v.addLayout(row2)

        self.btn_refresh.clicked.connect(self._refresh_streams)
        self.btn_connect.clicked.connect(self._start)
        self.btn_disconnect.clicked.connect(self._stop)
        self.spn_chunk.valueChanged.connect(self._on_chunk_change)
        self._status_cb = self.lbl_status.setText

        self._refresh_streams()
        return w

    # ---------- Logic ----------
    def _on_chunk_change(self, val: int):
        self._chunk_len = int(val)

    def _refresh_streams(self):
        try:
            self._stream_infos = resolve_streams(wait_time=1.0)
            self.cmb_streams.clear()
            for info in self._stream_infos:
                label = f"{info.name()} [{info.type()}] ({info.source_id()})"
                self.cmb_streams.addItem(label)
            if self._status_cb:
                self._status_cb(f"Statut: {len(self._stream_infos)} stream(s) trouvé(s)")
        except Exception as e:
            if self._status_cb:
                self._status_cb(f"Erreur scan LSL: {e}")

    def _start(self):
        if self._running or not self._stream_infos:
            return
        idx = self.cmb_streams.currentIndex()
        if idx < 0:
            if self._status_cb:
                self._status_cb("Aucun stream sélectionné")
            return

        try:
            info = self._stream_infos[idx]
            self._inlet = StreamInlet(info, max_chunklen=self._chunk_len)

            ch_count = info.channel_count()
            sfreq = info.nominal_srate()
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

            # → GUI thread
            self._bridge.sig_info.emit({
                "sfreq": float(sfreq),
                "ch_names": ch_names,
                "name": name,
                "type": stype,
                "uid": uid,
                "n_channels": int(ch_count),
            })

            self._running = True
            self.btn_connect.setEnabled(False)
            self.btn_disconnect.setEnabled(True)
            if self._status_cb:
                self._status_cb(f"Connecté à {name} [{stype}] • {ch_count} ch @ {sfreq} Hz")

            self._reader_thr = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thr.start()

        except Exception as e:
            if self._status_cb:
                self._status_cb(f"Erreur connexion LSL: {e}")
            self._running = False
            self._inlet = None

    def _reader_loop(self):
        while self._running and self._inlet is not None:
            try:
                samples, timestamps = self._inlet.pull_chunk(timeout=0.2, max_samples=self._chunk_len)
                if samples and len(samples) > 0:
                    # (n_samples, n_channels) -> (n_channels, n_samples)
                    arr = np.asarray(samples, dtype=np.float64).T
                    # → GUI thread
                    self._bridge.sig_chunk.emit(arr, timestamps)
                else:
                    time.sleep(0.01)
            except Exception as e:
                if self._status_cb:
                    self._status_cb(f"Erreur lecture: {e}")
                break

        self._cleanup_inlet()
        if self._status_cb:
            self._status_cb("Statut: idle")

    # ---------- Emission (dans le thread GUI) ----------
    def _emit_info_gui(self, info: dict):
        self.outputs["info"].on_next(info)

    def _emit_chunk_gui(self, arr, timestamps):
        # NOTE: on émet 'segment' pour coller au LiveDisplay
        self.outputs["segment"].on_next(arr)
        self.outputs["timestamps"].on_next(timestamps)

    def _stop(self):
        self._running = False
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)

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
