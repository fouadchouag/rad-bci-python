# plugins/synthetic_lr_plugin.py

import numpy as np
import mne
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox
)
from PyQt5.QtCore import QTimer
from core.node_base import BasePlugin


class SyntheticLRPlugin(BasePlugin):
    """
    Génère un Raw MNE synthétique avec blocs alternés 'Left' / 'Right'.
    8 canaux (C3, C4, CZ, PZ, F3, F4, O1, O2), 200 Hz, 120 s, blocs de 2 s.

    + Mode streaming avec contrôle Start/Stop :
      - Sorties:
          raw       : mne.io.Raw (one-shot)
          segment   : ndarray (n_ch, n_samples) en Volts (stream)
          info      : dict {"sfreq","ch_names",...}
          run       : bool (True = play, False = pause) pour piloter un slicer/aval
          reset     : bool (True ponctuel) pour remettre l'index aval à 0
    """
    name = "SyntheticLR"
    language = "Python"
    category = "Input Nodes"

    # ----------------- Setup -----------------
    def setup(self):
        # Sorties
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["segment"] = BehaviorSubject(None)
        self.outputs["info"] = BehaviorSubject(None)
        # Contrôle aval (à relier au slicer)
        self.outputs["run"] = BehaviorSubject(None)     # bool
        self.outputs["reset"] = BehaviorSubject(None)   # bool (pulse)

        # UI refs
        self._label = None
        self._btn_start = None
        self._btn_stop = None
        self._spn_win = None
        self._spn_ov = None
        self._chk_loop = None

        # Données synthétiques mises en cache (pour streaming)
        self._sfreq = 200.0
        self._duration_s = 120
        self._block_s = 2
        self._ch_names = ["EEG C3","EEG C4","EEG CZ","EEG PZ","EEG F3","EEG F4","EEG O1","EEG O2"]
        self._data = None            # ndarray (n_ch, n_samp) en Volts
        self._n_times = 0

        # Streaming state
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)
        self._streaming = False
        self._idx = 0
        self._win_s = 2.0
        self._overlap = 0.5
        self._loop = True

        # Cache tailles
        self._n_win = 0
        self._step = 0

    def execute(self, **kwargs):
        return {}

    # ----------------- UI -----------------
    def build_widget(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)

        self._label = QLabel("No data (synthetic)")
        lay.addWidget(self._label)

        # Génération one-shot (Raw)
        row0 = QHBoxLayout()
        btn_gen = QPushButton("Generate Left/Right Raw")
        btn_gen.clicked.connect(self._generate_raw)
        row0.addWidget(btn_gen)
        row0.addStretch(1)
        lay.addLayout(row0)

        # Paramètres stream
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Window (s):"))
        self._spn_win = QDoubleSpinBox()
        self._spn_win.setRange(0.1, 30.0)
        self._spn_win.setSingleStep(0.1)
        self._spn_win.setValue(self._win_s)
        self._spn_win.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self._spn_win)

        row1.addWidget(QLabel("Overlap (%):"))
        self._spn_ov = QSpinBox()
        self._spn_ov.setRange(0, 95)
        self._spn_ov.setSingleStep(5)
        self._spn_ov.setValue(int(self._overlap * 100))
        self._spn_ov.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self._spn_ov)

        self._chk_loop = QCheckBox("Loop")
        self._chk_loop.setChecked(self._loop)
        self._chk_loop.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self._chk_loop)

        row1.addStretch(1)
        lay.addLayout(row1)

        # Contrôle streaming
        row2 = QHBoxLayout()
        self._btn_start = QPushButton("Start Streaming")
        self._btn_start.clicked.connect(self._start_stream)
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.clicked.connect(self._stop_stream)
        self._btn_stop.setEnabled(False)
        row2.addWidget(self._btn_start)
        row2.addWidget(self._btn_stop)
        row2.addStretch(1)
        lay.addLayout(row2)

        return w

    # ------------- Génération Raw one-shot -------------
    def _generate_raw(self):
        raw = self._build_synthetic_raw()  # met aussi à jour self._data
        self.outputs["raw"].on_next(raw)
        info = {
            "sfreq": self._sfreq,
            "ch_names": self._ch_names,
            "name": "SyntheticLR",
            "type": "EEG",
            "uid": "synthetic-lr",
            "n_channels": len(self._ch_names),
        }
        self.outputs["info"].on_next(info)
        if self._label:
            self._label.setText(f"Synthetic Raw generated ({len(self._ch_names)} ch, Fs={self._sfreq:.1f} Hz)")
        print("[SyntheticLR] Raw generated and pushed.")

    def _build_synthetic_raw(self):
        sfreq = int(self._sfreq)
        duration_s = self._duration_s
        block_s = self._block_s
        ch_names = list(self._ch_names)
        n_ch = len(ch_names)
        n_samp = sfreq * duration_s
        t = np.arange(n_samp) / sfreq

        rng = np.random.default_rng(42)
        noise = 8e-6 * rng.normal(size=(n_ch, n_samp))     # ~8 µV
        mu_hz = 10.0
        amp_mu = 15e-6                                     # ~15 µV
        data = noise.copy()

        samples_per_block = sfreq * block_s
        n_blocks = duration_s // block_s
        annotations = []
        i_c3 = ch_names.index("EEG C3")
        i_c4 = ch_names.index("EEG C4")

        for b in range(n_blocks):
            start = b * samples_per_block
            end = start + samples_per_block
            cls = "Left" if (b % 2 == 0) else "Right"
            mu = amp_mu * np.sin(2*np.pi*mu_hz*t[start:end])
            if cls == "Left":
                data[i_c4, start:end] += mu  # accentue C4
            else:
                data[i_c3, start:end] += mu  # accentue C3
            annotations.append((b*block_s, block_s, cls))

        info = mne.create_info(ch_names=ch_names, sfreq=sfreq, ch_types="eeg")
        raw = mne.io.RawArray(data, info)
        raw.set_annotations(mne.Annotations(
            onset=[a[0] for a in annotations],
            duration=[a[1] for a in annotations],
            description=[a[2] for a in annotations],
        ))

        # cache pour streaming
        self._data = data.astype(np.float32, copy=False)
        self._n_times = int(self._data.shape[1])

        return raw

    # ------------- Streaming (Start/Stop) -------------
    def _on_params_changed(self, *a):
        self._win_s = float(self._spn_win.value()) if self._spn_win else self._win_s
        self._overlap = max(0.0, min(0.95, (self._spn_ov.value() if self._spn_ov else int(self._overlap*100)) / 100.0))
        self._loop = bool(self._chk_loop.isChecked()) if self._chk_loop else self._loop
        self._recompute_sizes()
        self._recompute_timer()

    def _start_stream(self):
        if self._data is None or self._n_times <= 0:
            self._build_synthetic_raw()

        self._idx = 0
        self._streaming = True
        if self._btn_start: self._btn_start.setEnabled(False)
        if self._btn_stop:  self._btn_stop.setEnabled(True)

        # émettre meta info (pour downstream)
        info = {
            "sfreq": float(self._sfreq),
            "ch_names": list(self._ch_names),
            "name": "SyntheticLR",
            "type": "EEG",
            "uid": "synthetic-lr",
            "n_channels": len(self._ch_names),
        }
        self.outputs["info"].on_next(info)

        # Piloter le slicer/aval
        self.outputs["run"].on_next(True)   # play

        self._recompute_sizes()
        self._recompute_timer()
        if self._label:
            self._label.setText(f"Streaming... Fs={self._sfreq:.1f} Hz | win={self._n_win} | step={self._step}")

    def _stop_stream(self):
        self._streaming = False
        self._timer.stop()
        if self._btn_start: self._btn_start.setEnabled(True)
        if self._btn_stop:  self._btn_stop.setEnabled(False)
        if self._label:     self._label.setText("Stopped.")

        # Stop aval + reset position
        self.outputs["run"].on_next(False)   # pause
        self.outputs["reset"].on_next(True)  # pulse reset

    def _recompute_sizes(self):
        if self._sfreq <= 0:
            self._n_win = 0
            self._step = 0
            return
        self._n_win = int(max(1, round(self._win_s * self._sfreq)))
        self._step = int(max(1, round(self._n_win * (1.0 - self._overlap))))

    def _recompute_timer(self):
        if not self._streaming or self._sfreq <= 0 or self._step <= 0:
            self._timer.stop()
            return
        period_ms = max(10, int(round(1000.0 * self._step / self._sfreq)))
        self._timer.start(period_ms)

    def _on_tick(self):
        if not self._streaming or self._data is None or self._n_times <= 0:
            return

        start = self._idx
        end_step = min(start + self._step, self._n_times)

        # fenêtre alignée: taille fixe _n_win
        wnd_end = min(end_step, self._n_times)
        wnd_start = max(0, wnd_end - self._n_win)
        if wnd_end <= wnd_start:
            if self._loop:
                self._idx = 0
                return
            else:
                self._stop_stream()
                return

        seg = self._data[:, wnd_start:wnd_end]  # (n_ch, n_samples), Volts
        self.outputs["segment"].on_next(seg)

        self._idx = end_step
        if self._idx >= self._n_times and not self._loop:
            self._stop_stream()
