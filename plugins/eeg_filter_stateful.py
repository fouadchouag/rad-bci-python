# plugins/eeg_filter_stateful.py
# -*- coding: utf-8 -*-
"""
EEGFilterStateful — bandpass IIR à état (streaming)
Entrées: segment, sfreq, ch_names
Sortie: segment filtré (même orientation)
"""
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    from scipy.signal import butter, sosfilt, sosfilt_zi
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

class EEGFilterStateful(BasePlugin):
    name = "EEGFilterStateful"
    language = "Python"
    category = "Processing Nodes"

    def setup(self):
        self.inputs = {
            "segment": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }
        self.outputs = {
            "segment": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }

        # paramètres
        self.low = 1.0      # Hz
        self.high = 40.0    # Hz
        self.order = 4
        self.notch_50 = False  # simple: non implémenté ici pour rester léger

        # état
        self._sos = None
        self._zi = None            # (n_ch, n_sections, 2)
        self._fs = 0.0
        self._nch_state = 0

    def _design(self, fs: float):
        if not HAVE_SCIPY or fs <= 0:
            self._sos = None
            self._zi = None
            self._fs = fs
            return
        ny = 0.5 * fs
        lo = max(0.001, float(self.low)) / ny
        hi = min(0.999, float(self.high)) / ny
        if hi <= lo:
            hi = min(0.99, lo + 0.01)
        self._sos = butter(self.order, [lo, hi], btype='bandpass', output='sos')
        self._zi = None
        self._fs = fs
        self._nch_state = 0

    def _ensure_state(self, n_ch: int):
        if not HAVE_SCIPY or self._sos is None:
            return
        n_sections = self._sos.shape[0]
        if self._zi is None or self._nch_state != n_ch:
            base_zi = sosfilt_zi(self._sos)   # (n_sections, 2)
            self._zi = np.tile(base_zi[None, :, :], (n_ch, 1, 1)).astype(np.float32)
            self._nch_state = n_ch

    def _filter_chunk(self, seg: np.ndarray, fs: float) -> np.ndarray:
        if seg is None or seg.size == 0:
            return seg
        arr = np.asarray(seg)
        # orientation -> (n_ch, n_s)
        transposed = False
        if arr.ndim == 1:
            arr = arr[None, :]
        if arr.shape[0] < arr.shape[1]:
            data = arr  # (n_ch, n_s)
        else:
            data = arr.T; transposed = True

        n_ch, n_s = data.shape
        if fs != self._fs or self._sos is None:
            self._design(fs)
        self._ensure_state(n_ch)

        if not HAVE_SCIPY or self._sos is None or self._zi is None:
            out = data  # pass-through
        else:
            out = np.empty_like(data, dtype=np.float32)
            # filtrage canal par canal (préserve l’état)
            for i in range(n_ch):
                y, self._zi[i] = sosfilt(self._sos, data[i].astype(np.float32, copy=False), zi=self._zi[i])
                out[i] = y

        # restitue orientation d’origine
        if transposed:
            return out.T
        return out

    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        fs = args.get("sfreq", self._fs)
        try:
            fs = float(fs) if fs is not None else self._fs
        except Exception:
            fs = self._fs

        seg = args.get("segment", None)
        if seg is not None and fs and fs > 0:
            y = self._filter_chunk(seg, fs)
            self.outputs["segment"].on_next(y)
            self.outputs["sfreq"].on_next(fs)
            self.outputs["ch_names"].on_next(args.get("ch_names", None))
            return {"segment": y, "sfreq": fs, "ch_names": args.get("ch_names", None)}

        # pas de segment: repasse les méta si présentes
        if "sfreq" in args:
            self.outputs["sfreq"].on_next(fs)
        if "ch_names" in args:
            self.outputs["ch_names"].on_next(args.get("ch_names"))
        return {}
