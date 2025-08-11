# plugins/raw_window_slicer_plugin.py
# Découpe un mne.io.Raw en fenêtres glissantes (segments) pour le pipeline:
# EEGReader(raw) -> RawWindowSlicer(segment, info[, sfreq, ch_names, times]) -> EEGFilter/ML/Display
# Rejoue en temps réel avec overlap et loop.
# Ajouts:
#  - "Honor ext run" (ignore les commandes run/reset si décoché)
#  - Auto-unpause à l'arrivée d'un nouveau raw (relance le timer)

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QSpinBox, QCheckBox, QPushButton
)
from PyQt5.QtCore import QTimer
from core.node_base import BasePlugin

class RawWindowSlicerPlugin(BasePlugin):
    name = "RawWindowSlicer"
    category = "Processing Nodes"

    def setup(self):
        self.inputs = {
            "raw": BehaviorSubject(None),     # mne.io.Raw
            "run": BehaviorSubject(None),     # bool: True=play, False=pause
            "reset": BehaviorSubject(None),   # bool: True -> reset position
        }
        self.outputs = {
            "segment": BehaviorSubject(None),   # np.ndarray (n_ch, n_samples), Volts
            "info": BehaviorSubject(None),      # dict {"sfreq","ch_names", ...}
            "sfreq": BehaviorSubject(None),     # float (compat ML)
            "ch_names": BehaviorSubject(None),  # list[str] (compat ML)
            "times": BehaviorSubject(None),     # np.ndarray (n_samples,) (compat ML)
        }

        # état
        self._raw = None
        self._sfreq = 0.0
        self._ch_names = []
        self._n_times = 0

        # params lecture
        self._win_s = 2.0
        self._overlap = 0.5   # [0..0.95]
        self._loop = True
        self._paused = False

        # contrôle externe
        self._honor_ext_run = True  # <— nouveau

        # index
        self._idx = 0

        # timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)

        # cache tailles
        self._n_win = 0
        self._step = 0

        # UI refs
        self._spn_win = None
        self._spn_overlap = None
        self._chk_loop = None
        self._chk_pause = None
        self._chk_honor_run = None
        self._lbl = None

    # ---------------- UI ----------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        row = QHBoxLayout()
        row.addWidget(QLabel("Window (s):"))
        self._spn_win = QDoubleSpinBox()
        self._spn_win.setRange(0.1, 30.0)
        self._spn_win.setSingleStep(0.1)
        self._spn_win.setValue(self._win_s)
        self._spn_win.valueChanged.connect(self._on_params_changed)
        row.addWidget(self._spn_win)

        row.addWidget(QLabel("Overlap (%):"))
        self._spn_overlap = QSpinBox()
        self._spn_overlap.setRange(0, 95)
        self._spn_overlap.setSingleStep(5)
        self._spn_overlap.setValue(int(self._overlap * 100))
        self._spn_overlap.valueChanged.connect(self._on_params_changed)
        row.addWidget(self._spn_overlap)

        self._chk_loop = QCheckBox("Loop")
        self._chk_loop.setChecked(self._loop)
        self._chk_loop.stateChanged.connect(self._on_params_changed)
        row.addWidget(self._chk_loop)

        self._chk_pause = QCheckBox("Pause")
        self._chk_pause.setChecked(self._paused)
        self._chk_pause.stateChanged.connect(self._on_params_changed)
        row.addWidget(self._chk_pause)

        # nouveau: honorer (ou pas) le run externe
        self._chk_honor_run = QCheckBox("Honor ext run")
        self._chk_honor_run.setChecked(self._honor_ext_run)
        self._chk_honor_run.stateChanged.connect(self._on_params_changed)
        row.addWidget(self._chk_honor_run)

        btn_reset = QPushButton("Reset pos")
        btn_reset.clicked.connect(self._reset_pos)
        row.addWidget(btn_reset)

        row.addStretch(1)
        v.addLayout(row)

        self._lbl = QLabel("Idle")
        v.addWidget(self._lbl)

        return w

    # ------------- Runtime / Logic -------------
    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        # ----- Contrôle externe -----
        run_val = args.get("run", None)
        if isinstance(run_val, bool) and self._honor_ext_run:
            if run_val is False:
                self._paused = True
                self._timer.stop()
                if self._chk_pause:
                    self._chk_pause.blockSignals(True)
                    self._chk_pause.setChecked(True)
                    self._chk_pause.blockSignals(False)
                if self._lbl: self._lbl.setText("Paused (ext)")
            else:  # True
                self._paused = False
                if self._chk_pause:
                    self._chk_pause.blockSignals(True)
                    self._chk_pause.setChecked(False)
                    self._chk_pause.blockSignals(False)
                self._recompute_timer()

        if args.get("reset", None) is True and self._honor_ext_run:
            self._idx = 0
            self._recompute_timer()

        # ----- Raw handling -----
        raw = args.get("raw", None)
        if raw is not None and raw is not self._raw:
            self._raw = raw
            # métadonnées
            try:
                self._sfreq = float(raw.info.get("sfreq", 0.0))
            except Exception:
                self._sfreq = 0.0
            try:
                self._ch_names = list(raw.ch_names) if getattr(raw, "ch_names", None) else list(raw.info.get("ch_names", []))
            except Exception:
                self._ch_names = []
            try:
                self._n_times = int(raw.n_times)
            except Exception:
                self._n_times = 0

            # fallback ch_names si vide
            if not self._ch_names or len(self._ch_names) == 0:
                try:
                    n_ch = int(raw.get_data(start=0, stop=1).shape[0])
                except Exception:
                    n_ch = 0
                if n_ch > 0:
                    self._ch_names = [f"ch{i+1}" for i in range(n_ch)]

            # émet info + rétro-compat
            info = {
                "sfreq": self._sfreq,
                "ch_names": self._ch_names,
                "name": getattr(raw, "filenames", ["Raw"])[0] if hasattr(raw, "filenames") else "Raw",
                "type": "EEG",
                "uid": "raw-slicer",
                "n_channels": len(self._ch_names),
            }
            self.outputs["info"].on_next(info)
            self.outputs["sfreq"].on_next(self._sfreq)
            self.outputs["ch_names"].on_next(self._ch_names)

            # reset lecture
            self._idx = 0

            # >>> Auto-unpause à l'arrivée d'un nouveau raw <<<
            self._paused = False
            if self._chk_pause:
                self._chk_pause.blockSignals(True)
                self._chk_pause.setChecked(False)
                self._chk_pause.blockSignals(False)

            # timers
            self._recompute_sizes()
            self._recompute_timer()

        # label statut
        if self._lbl:
            if self._raw is None or self._sfreq <= 0 or len(self._ch_names) == 0:
                self._lbl.setText("Idle (no raw)")
            else:
                state = "paused" if self._paused else "play"
                self._lbl.setText(f"{state} | Fs={self._sfreq:.1f} Hz | win={self._n_win} | step={self._step} | idx={self._idx}/{self._n_times}")

        return {}

    def _on_params_changed(self, *a):
        self._win_s = float(self._spn_win.value()) if self._spn_win else self._win_s
        self._overlap = max(0.0, min(0.95, (self._spn_overlap.value() if self._spn_overlap else int(self._overlap*100)) / 100.0))
        self._loop = bool(self._chk_loop.isChecked()) if self._chk_loop else self._loop
        self._paused = bool(self._chk_pause.isChecked()) if self._chk_pause else self._paused
        self._honor_ext_run = bool(self._chk_honor_run.isChecked()) if self._chk_honor_run else self._honor_ext_run
        self._recompute_sizes()
        self._recompute_timer()

    def _recompute_sizes(self):
        if self._sfreq <= 0:
            self._n_win = 0
            self._step = 0
            return
        self._n_win = max(1, int(round(self._win_s * self._sfreq)))
        self._step  = max(1, int(round(self._n_win * (1.0 - self._overlap))))

    def _recompute_timer(self):
        if self._raw is None or self._sfreq <= 0 or self._step <= 0 or self._paused:
            self._timer.stop()
            return
        period_ms = max(10, int(round(1000.0 * self._step / self._sfreq)))
        self._timer.start(period_ms)

    def _reset_pos(self):
        self._idx = 0
        self._recompute_timer()

    def _on_tick(self):
        if self._paused or self._raw is None or self._sfreq <= 0 or self._n_win <= 0 or self._step <= 0:
            return

        start = self._idx
        end_step = min(start + self._step, self._n_times)

        # Fenêtre à renvoyer: taille fixe _n_win, alignée sur la fin du pas
        wnd_end = min(end_step, self._n_times)
        wnd_start = max(0, wnd_end - self._n_win)

        if wnd_end <= wnd_start:
            if self._loop:
                self._idx = 0
                return
            else:
                self._timer.stop()
                return

        try:
            data, times = self._raw[:, wnd_start:wnd_end]  # Volts
        except Exception:
            return

        # Normalise en (n_ch, n_samples)
        if data.ndim == 1:
            data = data[None, :]
        if data.shape[0] > data.shape[1]:
            data = data.T

        # Fallback ch_names si jamais vide/mismatch
        if not self._ch_names or len(self._ch_names) != int(data.shape[0]):
            self._ch_names = [f"ch{i+1}" for i in range(int(data.shape[0]))]
            self.outputs["ch_names"].on_next(self._ch_names)

        # Émet
        self.outputs["segment"].on_next(data.astype(np.float32, copy=False))
        self.outputs["times"].on_next(np.asarray(times, dtype=np.float64))
        # (info/sfreq/ch_names ont déjà été émis)

        # avance
        self._idx = end_step
        if self._idx >= self._n_times and not self._loop:
            self._timer.stop()
