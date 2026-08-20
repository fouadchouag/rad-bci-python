# -*- coding: utf-8 -*-
"""
MNETFRMorletPlugin (safe v3)
- TFR Morlet depuis Epochs MNE, avec clamp auto correct (facteur 2),
  drop des fréquences trop basses si nécessaire, et n_jobs=None (compat).
"""
from typing import Optional, Tuple, Any
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.collapsible import CollapsibleSection

from PyQt5.QtWidgets import QWidget, QFormLayout, QDoubleSpinBox, QSpinBox, QCheckBox
from PyQt5.QtCore import Qt

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class MNETFRMorletPlugin(BasePlugin):
    help = help = {
        'summary': 'Compute time-frequency representation (TFR) using Morlet wavelets on mne.Epochs, with safe auto-clipping of cycles.',
        'usage': 'Connect mne.Epochs. Set frequency range, step, and wavelet cycles. Output TFR and freqs for visualization or further analysis.',
        'inputs': {
            'epochs': 'mne.Epochs — epoched data to compute TFR on',
            'fmin': 'float — minimum frequency in Hz (default 2.0)',
            'fmax': 'float — maximum frequency in Hz (default 40.0)',
            'fstep': 'float — frequency step in Hz (default 1.0)',
            'cycles': 'float — base number of wavelet cycles (default 2.0); clamped per-frequency when auto_clip is on',
            'average': 'bool — if True, return EvokedTFR (averaged across epochs); if False, return AverageTFR per epoch (default True)',
            'decim': 'int — decimation factor for the time axis (default 1, i.e. no decimation)',
            'picks_eeg_only': 'bool — restrict to EEG channels (default True)',
            'auto_clip_cycles': 'bool — automatically clamp cycles and drop frequencies that are too low for the epoch length (default True)',
            'min_cycles': 'float — minimum acceptable clamped cycle count; frequencies below this are dropped (default 0.25)',
            'safety_margin': 'float — safety margin < 1 applied to the max-cycles bound (default 0.98)',
        },
        'outputs': {
            'tfr': 'mne.time_frequency.AverageTFR or mne.time_frequency.EpochsTFR — the computed time-frequency representation',
            'freqs': 'np.ndarray — the actual frequencies used (after potential dropping)',
        },
        'parameters': [
            {'name': 'fmin', 'type': 'float', 'default': 2.0, 'desc': 'Minimum frequency (Hz)'},
            {'name': 'fmax', 'type': 'float', 'default': 40.0, 'desc': 'Maximum frequency (Hz)'},
            {'name': 'fstep', 'type': 'float', 'default': 1.0, 'desc': 'Frequency step (Hz)'},
            {'name': 'cycles', 'type': 'float', 'default': 2.0, 'desc': 'Base number of Morlet wavelet cycles'},
            {'name': 'average', 'type': 'bool', 'default': True, 'desc': 'Average across epochs (EvokedTFR)'},
            {'name': 'decim', 'type': 'int', 'default': 1, 'desc': 'Time-axis decimation factor'},
            {'name': 'picks_eeg_only', 'type': 'bool', 'default': True, 'desc': 'Restrict to EEG channels'},
            {'name': 'auto_clip_cycles', 'type': 'bool', 'default': True, 'desc': 'Clamp cycles and drop unsafe low frequencies automatically'},
            {'name': 'min_cycles', 'type': 'float', 'default': 0.25, 'desc': 'Minimum clamped cycle count to keep a frequency'},
            {'name': 'safety_margin', 'type': 'float', 'default': 0.98, 'desc': 'Safety margin for the max-cycles bound (< 1)'},
        ],
        'gotchas': [
            'The auto_clip_cycles feature enforces 2·(n_cycles·sfreq/f) < n_times to prevent edge artifacts; low frequencies may be dropped.',
            'n_jobs is hardcoded to None for MNE compatibility (no parallel execution).',
            'Uses n_jobs=None instead of "auto" to avoid compatibility issues with some MNE versions.',
            'If no valid frequencies survive the safety checks, outputs default to (None, None).',
            'Caching skips re-computation when the same epochs and all parameters match.',
        ],
    }

    name = "TFR (Morlet)"
    language = "Python"
    category = "Time-Frequency"
    supports_collapse = True
    start_hidden = True

    def setup(self):
        self.inputs = {
            "epochs": BehaviorSubject(None),
            "fmin": BehaviorSubject(2.0),
            "fmax": BehaviorSubject(40.0),
            "fstep": BehaviorSubject(1.0),
            "cycles": BehaviorSubject(2.0),            # base; clampé
            "average": BehaviorSubject(True),
            "decim": BehaviorSubject(1),
            "picks_eeg_only": BehaviorSubject(True),
            "auto_clip_cycles": BehaviorSubject(True),  # clamp + drop freqs trop basses
            "min_cycles": BehaviorSubject(0.25),       # cycle mini acceptable
            "safety_margin": BehaviorSubject(0.98),    # marge < 1 pour éviter ==
        }
        self.outputs = {
            "tfr": BehaviorSubject(None),
            "freqs": BehaviorSubject(None),
        }
        self._last_on_id: Optional[int] = None
        self._last_params: Optional[Tuple] = None
        self._widget: Optional[QWidget] = None

    # ---- UI ----
    def build_widget(self):
        if self._widget is not None:
            return self._widget
        panel = QWidget()
        lay = QFormLayout(panel)

        def _dspin(minv, maxv, step, val, cb):
            w = QDoubleSpinBox()
            w.setRange(minv, maxv)
            w.setDecimals(2)
            w.setSingleStep(step)
            w.setValue(val)
            w.valueChanged.connect(cb)
            return w

        sp_fmin = _dspin(0.1, 1e3, 0.1, float(self.inputs["fmin"].value),
                         lambda v: self.inputs["fmin"].on_next(float(v)))
        sp_fmax = _dspin(0.2, 2e3, 0.1, float(self.inputs["fmax"].value),
                         lambda v: self.inputs["fmax"].on_next(float(v)))
        sp_fstep = _dspin(0.1, 100.0, 0.1, float(self.inputs["fstep"].value),
                          lambda v: self.inputs["fstep"].on_next(float(v)))
        sp_cycles = _dspin(0.1, 20.0, 0.1, float(self.inputs["cycles"].value),
                           lambda v: self.inputs["cycles"].on_next(float(v)))

        chk_avg = QCheckBox("Average (EvokedTFR)")
        chk_avg.setChecked(bool(self.inputs["average"].value))
        chk_avg.stateChanged.connect(lambda s: self.inputs["average"].on_next(s == Qt.Checked))

        sp_decim = QSpinBox()
        sp_decim.setRange(1, 50)
        sp_decim.setValue(int(self.inputs["decim"].value))
        sp_decim.valueChanged.connect(lambda v: self.inputs["decim"].on_next(int(v)))

        chk_eeg = QCheckBox("EEG only")
        chk_eeg.setChecked(bool(self.inputs["picks_eeg_only"].value))
        chk_eeg.stateChanged.connect(lambda s: self.inputs["picks_eeg_only"].on_next(s == Qt.Checked))

        chk_clip = QCheckBox("Auto-clip & drop (safe)")
        chk_clip.setChecked(bool(self.inputs["auto_clip_cycles"].value))
        chk_clip.stateChanged.connect(lambda s: self.inputs["auto_clip_cycles"].on_next(s == Qt.Checked))

        lay.addRow("fmin (Hz)", sp_fmin)
        lay.addRow("fmax (Hz)", sp_fmax)
        lay.addRow("pas (Hz)", sp_fstep)
        lay.addRow("cycles (base)", sp_cycles)
        lay.addRow(chk_avg)
        lay.addRow("decim", sp_decim)
        lay.addRow(chk_eeg)
        lay.addRow(chk_clip)

        wrap = QWidget()
        from PyQt5.QtWidgets import QVBoxLayout
        v = QVBoxLayout(wrap); v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(CollapsibleSection("TFR (Morlet) – paramètres", panel, collapsed=True))
        self._widget = wrap
        return wrap

    # ---- helpers ----
    @staticmethod
    def _merge(kwargs: dict) -> dict:
        d = kwargs.get("in_data", {}) if "in_data" in kwargs else {}
        d.update(kwargs)
        return d

    @staticmethod
    def _freqs(fmin: float, fmax: float, fstep: float):
        if fmax <= fmin:
            fmax = fmin + max(0.1, abs(fstep))
        n = int(np.floor((fmax - fmin) / max(1e-6, fstep))) + 1
        return np.linspace(fmin, fmin + (n - 1) * fstep, n, dtype=float)

    @staticmethod
    def _safe_cycles_and_freqs(freqs, sfreq, n_times, base_cycles, min_cycles, margin):
        """
        Garantit 2 * (n_cycles * sfreq / f) < n_times  =>  n_cycles < n_times * f / (2*sfreq).
        - Clamp n_cycles à ce maximum * margin
        - Drop les fréquences où max_cycles < min_cycles (trop basses pour ce n_times)
        """
        freqs = np.array(freqs, dtype=float)
        max_cycles = (n_times * freqs) / (2.0 * float(sfreq))
        max_cycles = np.maximum(0.0, margin * max_cycles)

        mask = max_cycles >= float(min_cycles)
        if not np.all(mask):
            dropped = int(np.sum(~mask))
            kept = int(np.sum(mask))
            print(f"[TFRMorlet] Dropping {dropped} low freqs (keep {kept}) because n_cycles_max < {min_cycles}.")

        freqs_ok = freqs[mask]
        if freqs_ok.size == 0:
            return freqs_ok, np.array([], dtype=float)

        base = float(base_cycles)
        n_cycles = np.minimum(base, max_cycles[mask])
        return freqs_ok, n_cycles

    def _same(self, obj: Any, params: Tuple) -> bool:
        return (id(obj) == self._last_on_id) and (params == self._last_params)

    # ---- execute ----
    def execute(self, **kwargs):
        d = self._merge(kwargs)
        epochs = d.get("epochs", None)
        if epochs is None or not HAVE_MNE:
            return {"tfr": None, "freqs": None}

        # types sûrs
        fmin = float(d.get("fmin", self.inputs["fmin"].value))
        fmax = float(d.get("fmax", self.inputs["fmax"].value))
        fstep = float(d.get("fstep", self.inputs["fstep"].value))
        base_cycles = float(d.get("cycles", self.inputs["cycles"].value))
        average = bool(d.get("average", self.inputs["average"].value))
        try:
            decim = int(d.get("decim", self.inputs["decim"].value))
        except Exception:
            decim = 1
        if decim < 1:
            decim = 1
        eeg_only = bool(d.get("picks_eeg_only", self.inputs["picks_eeg_only"].value))
        auto_clip = bool(d.get("auto_clip_cycles", self.inputs["auto_clip_cycles"].value))
        min_cycles = float(d.get("min_cycles", self.inputs["min_cycles"].value))
        margin = float(d.get("safety_margin", self.inputs["safety_margin"].value))

        try:
            sf = float(epochs.info["sfreq"])
            n_times = int(len(epochs.times))
        except Exception:
            sf = 256.0
            n_times = 256

        freqs = self._freqs(fmin, fmax, fstep)

        if auto_clip:
            freqs_ok, n_cycles = self._safe_cycles_and_freqs(freqs, sf, n_times,
                                                             base_cycles, min_cycles, margin)
        else:
            freqs_ok = freqs
            n_cycles = np.full_like(freqs_ok, base_cycles, dtype=float)

        if freqs_ok.size == 0:
            print("[TFRMorlet] No valid frequencies after safety checks.")
            return {"tfr": None, "freqs": None}

        # picks
        picks = None
        try:
            if eeg_only and hasattr(epochs, "info"):
                picks = mne.pick_types(epochs.info, eeg=True, meg=False, eog=False, ecg=False,
                                       stim=False, misc=False, exclude=[])
        except Exception:
            picks = None

        params = (id(epochs), float(fmin), float(fmax), float(fstep), float(base_cycles),
                  bool(average), int(decim), bool(eeg_only),
                  tuple(np.round(n_cycles, 6)), tuple(np.round(freqs_ok, 6)))
        if self._same(epochs, params):
            return {"tfr": self.outputs["tfr"].value, "freqs": self.outputs["freqs"].value}

        # ---- compute TFR ----
        try:
            # IMPORTANT: n_jobs=None (pas "auto")
            if hasattr(epochs, "compute_tfr"):
                tfr = epochs.compute_tfr(method="morlet",
                                         freqs=freqs_ok, n_cycles=n_cycles,
                                         use_fft=True, return_itc=False,
                                         average=average, decim=decim,
                                         picks=picks, n_jobs=None, verbose=False)
            else:
                tfr = mne.time_frequency.tfr_morlet(
                    epochs, freqs=freqs_ok, n_cycles=n_cycles,
                    use_fft=True, return_itc=False, average=average,
                    decim=decim, picks=picks, n_jobs=None, verbose=False
                )
        except Exception as e:
            # Log détaillé pour traquer les types si souci
            print(f"[TFRMorlet] Error: {e}")
            print(f"  types: fmin={type(fmin)}, fmax={type(fmax)}, fstep={type(fstep)}, "
                  f"cycles={type(base_cycles)}, decim={type(decim)}, average={type(average)}, "
                  f"picks={'None' if picks is None else (type(picks), np.asarray(picks).dtype, np.asarray(picks).shape)}, "
                  f"freqs_ok dtype={np.asarray(freqs_ok).dtype}, n_cycles dtype={np.asarray(n_cycles).dtype}")
            return {"tfr": None, "freqs": None}

        self._last_on_id = id(epochs)
        self._last_params = params
        return {"tfr": tfr, "freqs": freqs_ok}