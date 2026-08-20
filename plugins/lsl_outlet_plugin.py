# plugins/lsl_outlet_plugin.py
# -*- coding: utf-8 -*-
"""
LSL Outlet — publie un signal EEG (segment + sfreq + ch_names) vers un
stream LSL sortant. Pendant-miroir de LSLInletPlugin.

Entrées:
  - segment     : np.ndarray (n_ch, n_samples)  (doit être sans None pour pousser)
  - sfreq       : float
  - ch_names    : list[str]

Sorties: aucune (nœud sink)

Usage typique: construire un pipeline
  LSL Inlet -> (filtre optionnel) -> LSL Outlet
pour republier le signal sur le réseau LSL sous un nouveau nom
(ex: BenchmarkOutput) afin qu'un client externe puisse le recevoir.

Ce plugin a été créé spécifiquement pour permettre des benchmarks
cross-plateforme (RBciAD vs OpenViBE vs BCI2000) où chaque plateforme
doit republier la sortie de son pipeline sur LSL pour qu'une sonde
externe commune mesure la latence end-to-end.
"""

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QLayout, QSizePolicy
)

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# pylsl (optional import: graceful failure si pylsl manquant)
try:
    from pylsl import StreamInfo, StreamOutlet
    LSL_OK = True
except Exception:
    StreamInfo = None
    StreamOutlet = None
    LSL_OK = False


# ===================== Plugin =========================
class LSLOutletPlugin(BasePlugin):
    help = {
        'gotchas': [
            'Requires pylsl installed (pip install pylsl).',
            'The outlet is created lazily on first incoming segment; changing parameters after creation requires disconnecting the input.',
            'Segment must be 2D numpy array (n_channels x n_samples); 1D arrays are rejected.',
            'Sfreq and ch_names are cached from the most recent execute() call; if they arrive after segment, the first push uses defaults (250 Hz, auto-generated names).',
            'This is a sink node with no outputs.',
        ],
        'inputs': {
            'segment': '2D float [channels x samples] — EEG data to push',
            'sfreq': 'float (Hz) — sampling rate for outlet creation',
            'ch_names': 'List[str] — channel labels written into LSL stream metadata',
        },
        'outputs': {},
        'parameters': [
            {'default': 'BenchmarkOutput',
             'desc': 'LSL stream name to publish',
             'name': 'stream_name',
             'type': 'str'},
            {'default': 'EEG',
             'desc': 'LSL stream type',
             'name': 'stream_type',
             'type': 'str'},
            {'default': 'rbciad_lsl_outlet',
             'desc': 'Source ID for LSL (unique per device)',
             'name': 'source_id',
             'type': 'str'},
        ],
        'summary': 'LSL Outlet — publish pipeline output as LSL stream (sink node).',
        'usage': 'Connect segment, sfreq, and ch_names from any upstream node. The outlet is created automatically on the first segment arrival.',
    }

    name = "LSL Outlet"
    category = "Output Nodes"
    language = "Python"
    start_hidden = True
    supports_collapse = True

    # Family hints for connection validation (matches LSLInletPlugin convention)
    PIN_FAMILY_HINTS = {
        "segment": "segment",
        "sfreq": "sfreq",
        "ch_names": "ch_names",
    }

    # ---------- lifecycle ----------
    def setup(self):
        self.inputs = {
            "segment": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }
        self.outputs = {}  # sink node: no outputs

        # Configurable parameters
        self._stream_name = "BenchmarkOutput"
        self._stream_type = "EEG"
        self._source_id = "rbciad_lsl_outlet"

        # LSL state
        self._outlet = None
        self._outlet_n_channels = 0
        self._outlet_sfreq = 0.0
        self._outlet_ch_names = None
        self._n_pushed = 0  # count for UI

        # Cached sfreq / ch_names from latest execute() call
        self._cached_sfreq = 0.0
        self._cached_ch_names = None

        # UI refs
        self.edit_name = None
        self.edit_type = None
        self.edit_source_id = None
        self.lbl_status = None

    def execute(self, inputs=None, **kwargs):
        """Reactive entry point: called by RBciAD engine when inputs change."""
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        # Cache sfreq and ch_names if present
        sf = args.get("sfreq", None)
        if isinstance(sf, (int, float)) and sf > 0:
            self._cached_sfreq = float(sf)

        chn = args.get("ch_names", None)
        if isinstance(chn, (list, tuple)) and chn:
            self._cached_ch_names = list(chn)

        # Process a segment if provided
        seg = args.get("segment", None)
        if seg is not None:
            self._on_segment(seg)

        return {}

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget()
        UiKit.apply_node_style(w)
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        if not LSL_OK:
            msg = QLabel("❌ pylsl unavailable — install it: pip install pylsl")
            root.addWidget(msg)
            return w

        # Collapsible panel
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Stream name
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Stream name:"))
        self.edit_name = QLineEdit(self._stream_name)
        row1.addWidget(self.edit_name, 1)
        v.addLayout(row1)

        # Stream type
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Stream type:"))
        self.edit_type = QLineEdit(self._stream_type)
        row2.addWidget(self.edit_type, 1)
        v.addLayout(row2)

        # Source ID
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Source ID:"))
        self.edit_source_id = QLineEdit(self._source_id)
        row3.addWidget(self.edit_source_id, 1)
        v.addLayout(row3)

        # Status
        self.lbl_status = QLabel("Status: not streaming (waiting for data)")
        v.addWidget(self.lbl_status)

        # Hint
        hint = QLabel("Outlet is created automatically on first incoming "
                      "segment. Changing parameters after creation requires "
                      "disconnecting the input and reconnecting.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #777; font-size: 10px;")
        v.addWidget(hint)

        root.addWidget(CollapsibleSection("LSL Outlet Parameters",
                                           panel, collapsed=False))

        # Connect UI -> internal state
        self.edit_name.textChanged.connect(
            lambda s: setattr(self, "_stream_name", str(s).strip()
                              or "BenchmarkOutput"))
        self.edit_type.textChanged.connect(
            lambda s: setattr(self, "_stream_type", str(s).strip() or "EEG"))
        self.edit_source_id.textChanged.connect(
            lambda s: setattr(self, "_source_id", str(s).strip()
                              or "rbciad_lsl_outlet"))

        return w

    # ---------- LSL outlet creation (lazy) ----------
    def _ensure_outlet(self, n_channels: int, sfreq: float,
                       ch_names=None):
        """Create the LSL outlet on demand, once we know channel count + fs."""
        if not LSL_OK:
            return False
        if self._outlet is not None:
            # Already created: check that config is compatible
            if (n_channels != self._outlet_n_channels
                    or abs(sfreq - self._outlet_sfreq) > 1e-6):
                # Config changed mid-stream: destroy and recreate
                self._outlet = None
                self._outlet_n_channels = 0
                self._outlet_sfreq = 0.0
                self._outlet_ch_names = None
            else:
                return True  # already good

        if n_channels <= 0 or sfreq <= 0:
            return False

        try:
            info = StreamInfo(
                name=self._stream_name,
                type=self._stream_type,
                channel_count=int(n_channels),
                nominal_srate=float(sfreq),
                channel_format="float32",
                source_id=self._source_id,
            )
            # Populate channel metadata if we have names
            if ch_names and len(ch_names) == n_channels:
                channels = info.desc().append_child("channels")
                for cname in ch_names:
                    ch = channels.append_child("channel")
                    ch.append_child_value("label", str(cname))
                    ch.append_child_value("unit", "microvolts")
                    ch.append_child_value("type", self._stream_type)

            self._outlet = StreamOutlet(info, chunk_size=0, max_buffered=360)
            self._outlet_n_channels = int(n_channels)
            self._outlet_sfreq = float(sfreq)
            self._outlet_ch_names = list(ch_names) if ch_names else None
            self._n_pushed = 0
            self._set_status(f"streaming '{self._stream_name}' "
                             f"[{self._stream_type}] {n_channels}ch "
                             f"@ {sfreq:.1f} Hz")
            return True
        except Exception as e:
            self._set_status(f"error creating outlet: {e}")
            self._outlet = None
            return False

    # ---------- Reactive: push incoming segment ----------
    def _on_segment(self, seg):
        """Called from execute() whenever a new segment arrives."""
        if seg is None:
            return
        if not LSL_OK:
            return

        arr = np.asarray(seg)
        if arr.ndim != 2:
            self._set_status(f"warn: unexpected shape {arr.shape}")
            return

        # arr is (n_ch, n_samples) by RBciAD convention (see LSLInletPlugin).
        # pylsl expects (n_samples, n_channels), so transpose.
        n_ch, n_samples = arr.shape
        if n_samples == 0:
            return

        # Use cached sfreq and ch_names from previous execute() calls
        sfreq_f = self._cached_sfreq if self._cached_sfreq > 0 else 250.0

        if not self._ensure_outlet(n_ch, sfreq_f, self._cached_ch_names):
            return

        try:
            # pylsl wants list of lists: [[ch0,ch1,...],...] (samples-major)
            chunk = arr.T.astype(np.float32).tolist()
            self._outlet.push_chunk(chunk)
            self._n_pushed += n_samples
            if self.lbl_status is not None and (self._n_pushed % 1000) < n_samples:
                self._set_status(f"streaming '{self._stream_name}' "
                                 f"({self._n_pushed} samples pushed)")
        except Exception as e:
            self._set_status(f"push error: {e}")

    # ---------- Helpers ----------
    def _set_status(self, txt: str):
        if self.lbl_status is not None:
            try:
                self.lbl_status.setText(f"Status: {txt}")
            except Exception:
                pass

    def on_remove(self):
        self._outlet = None
