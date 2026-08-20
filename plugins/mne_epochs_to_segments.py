# plugins/mne_epochs_to_segments.py
# -*- coding: utf-8 -*-
"""
MNEEpochsToSegments
- Adapte des mne.Epochs en flux 'segment' pour EEGLiveDisplay.
- Pins:
    IN : epochs (mne.Epochs), fps (Hz, vitesse de lecture), loop (bool)
    OUT: segment (np.ndarray n_ch x n_s), ch_names (list[str]), sfreq (float), info (dict)
- UI pliable + config compatible.
"""

from typing import Optional
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QCheckBox, QSizePolicy, QLayout


class MNEEpochsToSegments(BasePlugin):
    help = help = {
        'summary': 'Stream mne.Epochs one-by-one as segment arrays at a configurable frame rate, for live display.',
        'usage': 'Connect mne.Epochs. The plugin buffers all epoch data and emits one segment per timer tick at the configured FPS.',
        'inputs': {
            'epochs': 'mne.Epochs — the epoched data to stream as segments',
            'fps': 'float — playback frame rate in Hz (default 20.0, range 1–60)',
            'loop': 'bool — restart from the first epoch after the last one (default True)',
        },
        'outputs': {
            'segment': 'np.ndarray (n_channels, n_samples) — the current epoch as a 2D array',
            'ch_names': 'list[str] — channel names (emitted once when epochs arrive)',
            'sfreq': 'float — sampling frequency in Hz (emitted once)',
            'info': 'dict — metadata: seg_index, seg_total, seg_len_s, reset flag',
            'config_out': 'dict — exported configuration (fps, loop)',
        },
        'parameters': [
            {'name': 'fps', 'type': 'float', 'default': 20.0, 'desc': 'Playback speed in frames per second (1–60)'},
            {'name': 'loop', 'type': 'bool', 'default': True, 'desc': 'Loop back to the first epoch after reaching the end'},
        ],
        'gotchas': [
            'All epoch data is loaded into memory (get_data()) when epochs arrive — can be large.',
            'The timer-based streaming requires a running Qt event loop.',
            'Channel names and sfreq are emitted once and retained even after streaming stops.',
            'Calling on_remove() stops the timer and frees the data buffer.',
        ],
    }

    name = "MNEEpochsToSegments"
    language = "Python"
    category = "Segmentation"
    supports_collapse = True

    def setup(self):
        # IN
        self.inputs["epochs"] = BehaviorSubject(None)
        self.inputs["fps"] = BehaviorSubject(20.0)
        self.inputs["loop"] = BehaviorSubject(True)

        # OUT
        self.outputs["segment"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"] = BehaviorSubject(None)
        self.outputs["info"] = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # état
        self._epochs = None
        self._data = None      # ndarray (n_ep, n_ch, n_s)
        self._idx = 0
        self._n_ep = 0
        self._n_ch = 0
        self._n_s = 0
        self._fs = 0.0
        self._names = []

        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)
        self._interval_ms = int(1000 / max(1.0, float(self.inputs["fps"].value)))

        self._emit_config()

    # -------- config --------
    def export_config(self) -> dict:
        return {"fps": float(self.inputs["fps"].value), "loop": bool(self.inputs["loop"].value)}

    def _emit_config(self):
        try: self.outputs["config_out"].on_next(self.export_config())
        except Exception: pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict): return
        if "fps" in cfg:
            try:
                v = float(cfg["fps"]); v = max(1.0, min(60.0, v))
                self.inputs["fps"].on_next(v)
                self._interval_ms = int(1000 / v)
                if self._timer.isActive():
                    self._timer.start(self._interval_ms)
            except Exception: pass
        if "loop" in cfg:
            try: self.inputs["loop"].on_next(bool(cfg["loop"]))
            except Exception: pass
        self._emit_config()

    def config_hints(self) -> dict:
        return {"fields": {
            "fps": {"type": "float", "min": 1.0, "max": 60.0, "step": 1.0},
            "loop": {"type": "bool"},
        }, "_order": ["fps", "loop"]}

    # -------- UI --------
    def build_widget(self) -> QWidget:
        root = QWidget(); root.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer = QVBoxLayout(root); outer.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget(); form = QFormLayout(panel)

        sp = QDoubleSpinBox(); sp.setRange(1.0, 60.0); sp.setSingleStep(1.0)
        sp.setValue(float(self.inputs["fps"].value))
        sp.valueChanged.connect(self._on_fps_changed)
        form.addRow("FPS lecture", sp)

        chk = QCheckBox("Loop"); chk.setChecked(bool(self.inputs["loop"].value))
        chk.stateChanged.connect(lambda s: self.inputs["loop"].on_next(bool(s)))
        form.addRow("", chk)

        outer.addWidget(CollapsibleSection("Lecture des epochs", panel, collapsed=True))
        self._emit_config()
        return root

    def _on_fps_changed(self, v):
        v = float(v); v = max(1.0, min(60.0, v))
        self.inputs["fps"].on_next(v)
        self._interval_ms = int(1000 / v)
        if self._timer.isActive():
            self._timer.start(self._interval_ms)
        self._emit_config()

    # -------- runtime --------
    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict):
            in_data = {}
        if kwargs:
            in_data.update(kwargs)

        epochs = in_data.get("epochs", None)
        if epochs is None:
            self._stop()
            self._clear_out()
            return {}

        # bufferize
        try:
            X = epochs.get_data()            # (n_ep, n_ch, n_s)
            names = list(epochs.ch_names)
            fs = float(epochs.info["sfreq"])
        except Exception:
            self._stop(); self._clear_out(); return {}

        self._epochs = epochs
        self._data = X.astype(np.float32, copy=False)
        self._n_ep, self._n_ch, self._n_s = self._data.shape
        self._names = names
        self._fs = fs
        self._idx = 0

        # meta once
        try:
            self.outputs["ch_names"].on_next(list(self._names))
            self.outputs["sfreq"].on_next(float(self._fs))
            seg_len_s = float(self._n_s) / float(self._fs) if self._fs > 0 else None
            info = {"seg_total": int(self._n_ep), "seg_len_s": seg_len_s, "reset": True}
            self.outputs["info"].on_next(info)
        except Exception:
            pass

        # start timer
        if self._n_ep > 0:
            self._timer.start(self._interval_ms)
        else:
            self._stop(); self._clear_out()
        return {}

    def _on_tick(self):
        if self._data is None or self._n_ep == 0:
            self._stop(); self._clear_out(); return

        # envoyer epoch courant comme segment (n_ch x n_s)
        seg = self._data[self._idx, :, :]
        try:
            self.outputs["segment"].on_next(seg)
            seg_len_s = float(self._n_s) / float(self._fs) if self._fs > 0 else None
            self.outputs["info"].on_next({"seg_index": int(self._idx + 1), "seg_total": int(self._n_ep), "seg_len_s": seg_len_s})
        except Exception:
            pass

        self._idx += 1
        if self._idx >= self._n_ep:
            if bool(self.inputs["loop"].value):
                self._idx = 0
                try:
                    self.outputs["info"].on_next({"seg_index": 0, "seg_total": int(self._n_ep), "reset": True})
                except Exception:
                    pass
            else:
                self._stop()

    def _stop(self):
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass

    def _clear_out(self):
        try:
            self.outputs["segment"].on_next(None)
            # ne pas effacer ch_names/sfreq pour garder la config d'affichage
        except Exception:
            pass

    def on_remove(self):
        self._stop()
        self._data = None
        self._epochs = None