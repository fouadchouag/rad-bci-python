# -*- coding: utf-8 -*-
"""
EEGChannelRMSPlugin — Convert Raw/segment to per-channel scalar values (RMS)

Inputs (reactive):
  - raw: mne.Raw | None
  - segment: np.ndarray | None   # shape (n_channels, n_samples) or (n_samples, n_channels)
  - ch_names: list[str] | None   # if provided, will order/output using this list
  - window_s: float | None       # optional, window length (seconds) for Raw

Outputs:
  - values: dict[str, float]     # per-channel RMS
  - ch_names: list[str]          # names corresponding to values order
  - status: str

Notes:
  - If both `segment` and `raw` are present, `segment` takes precedence.
  - For Raw, if `window_s` is not set, uses the last window or full data if 0.
  - Designed as a simple driver for ScalpTopomap3D which expects scalars per channel.

Author: RBciAD project
"""
from typing import Dict, List, Optional, Tuple

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QDoubleSpinBox, QHBoxLayout, QToolButton
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne  # noqa: F401
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


class CollapsibleSection(QWidget):
    def __init__(self, title: str, start_collapsed: bool = False, parent: QWidget = None):
        super().__init__(parent)
        self._btn = QToolButton(text=title)
        self._btn.setCheckable(True)
        self._btn.setChecked(not start_collapsed)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow if self._btn.isChecked() else Qt.RightArrow)
        self._btn.setStyleSheet("QToolButton{font-weight:600;}")
        self._container = QWidget(); self.body = QVBoxLayout(self._container)
        self.body.setContentsMargins(8, 6, 8, 6); self.body.setSpacing(6)
        self._container.setVisible(self._btn.isChecked())
        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(2)
        lay.addWidget(self._btn); lay.addWidget(self._container)
        self._btn.toggled.connect(self._on_toggled)
    def _on_toggled(self, checked: bool):
        self._container.setVisible(checked)
        self._btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.adjustSize()


class EEGChannelRMSPlugin(BasePlugin):
    name = "EEGChannelRMS"
    language = "Python"
    category = "Processing"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["window_s"] = BehaviorSubject(1.0)

        self.outputs["values"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")

        self._widget: Optional[QWidget] = None
        self._win_s = 1.0

    def build_widget(self) -> QWidget:
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(6,6,6,6); root.setSpacing(6)
        title = QLabel("EEG Channel RMS (→ scalars)"); title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)
        sec = CollapsibleSection("Paramètres", start_collapsed=False); root.addWidget(sec)
        row = QHBoxLayout(); row.addWidget(QLabel("Fenêtre (s):"))
        self._spw = QDoubleSpinBox(); self._spw.setDecimals(3); self._spw.setRange(0.0, 3600.0); self._spw.setValue(self._win_s); self._spw.setSingleStep(0.1)
        self._spw.valueChanged.connect(self._on_win_changed)
        row.addWidget(self._spw, 1); sec.body.addLayout(row)
        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#666"); root.addWidget(self._lbl)
        self._widget = w; return w

    def _on_win_changed(self, val: float):
        self._win_s = float(val)
        # trigger recompute if we have Raw
        self.execute(self.inputs)

    def execute(self, *call_args, **call_kwargs):
        """Robustly handle BehaviorSubjects, raw values, kwargs, or a plain dict."""
        try:
            # --- Normalize inputs
            if call_kwargs:
                inps = call_kwargs
            elif call_args and isinstance(call_args[0], dict):
                inps = call_args[0]
            else:
                inps = self.inputs

            def _v(x):
                try:
                    return x.value
                except Exception:
                    return x

            seg = _v(inps.get("segment")) if isinstance(inps, dict) else None
            raw = _v(inps.get("raw")) if isinstance(inps, dict) else None
            names_hint = _v(inps.get("ch_names")) if isinstance(inps, dict) else None
            win_s_in = _v(inps.get("window_s")) if isinstance(inps, dict) else None

            if isinstance(win_s_in, (int, float)):
                self._win_s = float(win_s_in)
                if getattr(self, "_spw", None) is not None:
                    self._spw.blockSignals(True); self._spw.setValue(self._win_s); self._spw.blockSignals(False)

            values_dict = None; out_names = None

            if seg is not None:
                arr = np.asarray(seg)
                if arr.ndim != 2:
                    raise ValueError("segment must be 2D")
                # shape to (n_channels, n_samples)
                if arr.shape[0] < arr.shape[1]:
                    data_ch_samp = arr
                else:
                    data_ch_samp = arr.T
                rms = np.sqrt(np.mean(np.asarray(data_ch_samp, dtype=float)**2, axis=1))
                if names_hint is not None and len(names_hint) == rms.size:
                    out_names = list(names_hint)
                else:
                    out_names = [f"Ch{i}" for i in range(rms.size)]
                values_dict = {out_names[i]: float(rms[i]) for i in range(len(out_names))}

            elif raw is not None:
                data, used_names = self._get_raw_window(raw, self._win_s, names_hint)
                if data.size == 0:
                    raise ValueError("Raw empty window")
                rms = np.sqrt(np.mean(np.asarray(data, dtype=float)**2, axis=1))
                out_names = list(used_names)
                values_dict = {out_names[i]: float(rms[i]) for i in range(len(out_names))}

            if values_dict is None:
                self._set_status("En attente de segment/raw…")
                return

            self.outputs["values"].on_next(values_dict)
            self.outputs["ch_names"].on_next(out_names)
            self._set_status(f"RMS: {len(out_names)} canaux")
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    def _get_raw_window(self, raw, win_s: float, names_hint: Optional[List[str]]):
        # picks from hint else EEG channels else all
        try:
            import mne as _mne
            if names_hint:
                picks = [raw.ch_names.index(n) for n in names_hint if n in raw.ch_names]
            else:
                picks = _mne.pick_types(raw.info, eeg=True, seeg=True, meg=False, stim=False, eog=False, ecg=False, misc=False)
                picks = picks if len(picks) > 0 else np.arange(len(raw.ch_names))
        except Exception:
            picks = np.arange(len(raw.ch_names))
        n_samp = raw.n_times
        sfreq = float(raw.info["sfreq"]) if hasattr(raw, "info") and isinstance(raw.info, dict) and "sfreq" in raw.info else float(getattr(raw.info, "sfreq", 0.0)) if hasattr(raw, "info") else 0.0
        if win_s and sfreq > 0.0:
            n_win = int(max(1, round(win_s * sfreq)))
            start = max(0, n_samp - n_win); stop = n_samp
        else:
            start, stop = 0, n_samp
        data = raw.get_data(picks=picks, start=start, stop=stop)
        used_names = [raw.ch_names[i] for i in picks]
        return data, used_names

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)
