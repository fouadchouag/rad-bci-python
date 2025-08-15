# plugins/eeg_universal_reader.py
# -*- coding: utf-8 -*-
"""
EEGUniversalReader — MNE only
- Ouvre les formats MNE (edf/bdf/gdf/fif/brainvision/eeglab/ctf/…)
- Sorties:
    raw      : mne.io.BaseRaw
    segment  : np.ndarray float32 (n_ch, n_samples)  [flux auto]
    ch_names : list[str]            [émis au reset UNIQUEMENT]
    sfreq    : float                [émis au reset UNIQUEMENT]
    info     : dict {path, n_channels, sfreq, n_samples, units, reset}
    event    : dict (annotations visibles dans la fenêtre)
- Autoplay: dès qu’un fichier est choisi, le flux `segment` démarre.
- Pas de Pause/Stop ici (contrôle côté LiveDisplay).
"""
import os
from typing import Optional, List, Tuple
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QFileDialog, QComboBox, QLayout, QSizePolicy,
    QStyle
)

from core.node_base import BasePlugin
    # ^^^ garde ton import
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import mne
    HAVE_MNE = True
except Exception as e:
    HAVE_MNE = False
    _MNE_ERR = str(e)

def _has(io_name: str) -> bool:
    return HAVE_MNE and hasattr(mne.io, io_name)

def _filters() -> str:
    groups, all_ext = [], []
    MAP = [
        ((".fif",".fif.gz"), "read_raw_fif"),
        ((".edf",".bdf"),    "read_raw_edf"),
        ((".gdf",),          "read_raw_gdf"),
        ((".vhdr",),         "read_raw_brainvision"),
        ((".set",),          "read_raw_eeglab"),
        ((".mff",),          "read_raw_mff"),
        ((".raw",),          "read_raw_egi"),
        ((".cnt",),          "read_raw_cnt"),
        ((".ds",),           "read_raw_ctf"),
        ((".sqd",".con"),    "read_raw_kit"),
        ((".trc",),          "read_raw_micromed"),
        ((".eeg",".hdr"),    "read_raw_nicolet"),
        ((".eeg",),          "read_raw_nihon"),
        ((".lay",".dat"),    "read_raw_persyst"),
        ((".dat",),          "read_raw_bci2000"),
    ]
    for exts, fn in MAP:
        if _has(fn):
            groups.append(f"{fn} ({' '.join('*'+e for e in exts)})")
            all_ext.extend(exts)
    all_pat = " ".join(sorted(set('*'+e for e in all_ext))) if all_ext else "*"
    s = f"All supported ({all_pat})"
    if groups: s += ";;" + ";;".join(groups)
    s += ";;All files (*)"
    return s

class EEGUniversalReader(BasePlugin):
    name = "EEGUniversalReader"
    language = "Python"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True

    def setup(self):
        self.outputs["raw"]      = BehaviorSubject(None)
        self.outputs["segment"]  = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"]    = BehaviorSubject(None)
        self.outputs["info"]     = BehaviorSubject(None)
        self.outputs["event"]    = BehaviorSubject(None)

        self._raw: Optional["mne.io.BaseRaw"] = None
        self._path: Optional[str] = None
        self._names: List[str] = []
        self._sf: float = 0.0
        self._n_samp: int = 0
        self._idx: int = 0

        self._units = "V"          # V ou uV (affichées dans info)
        self._chunk_s = 1.0
        self._overlap_s = 0.0
        self._loop = False
        self._resample_hz = 0

        self._eeg_only = True
        self._incl_eog = False
        self._incl_emg = False
        self._incl_stim = False

        self._timer = QTimer(); self._timer.timeout.connect(self._tick)
        self._status = None

    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        v = QVBoxLayout(w); v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget(); pv = QVBoxLayout(panel); pv.setContentsMargins(8,8,8,8); pv.setSpacing(8)

        r1 = QHBoxLayout()
        btn_open = UiKit.make_btn("Open EEG…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_open.clicked.connect(self._on_open); r1.addWidget(btn_open)
        cb_loop = QCheckBox("Loop"); cb_loop.stateChanged.connect(lambda s: setattr(self,"_loop", bool(s))); r1.addWidget(cb_loop)
        r1.addStretch(1); pv.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("chunk (s):")); sp = QDoubleSpinBox(); sp.setRange(0.05,30.0); sp.setSingleStep(0.05); sp.setValue(self._chunk_s)
        sp.valueChanged.connect(lambda v: setattr(self,"_chunk_s", float(v))); r2.addWidget(sp)
        r2.addWidget(QLabel("overlap (s):")); ol = QDoubleSpinBox(); ol.setRange(0,29.9); ol.setSingleStep(0.05); ol.setValue(self._overlap_s)
        ol.valueChanged.connect(lambda v: setattr(self,"_overlap_s", float(v))); r2.addWidget(ol)
        r2.addWidget(QLabel("resample (Hz, 0=off):")); rs = QSpinBox(); rs.setRange(0,4096); rs.setValue(self._resample_hz)
        rs.valueChanged.connect(lambda v: setattr(self,"_resample_hz", int(v))); r2.addWidget(rs)
        r2.addSpacing(8); r2.addWidget(QLabel("units:"))
        cb_u = QComboBox(); cb_u.addItems(["V","uV"]); cb_u.currentTextChanged.connect(lambda t: setattr(self,"_units", t)); r2.addWidget(cb_u)
        r2.addStretch(1); pv.addLayout(r2)

        r3 = QHBoxLayout()
        eeg = QCheckBox("EEG only"); eeg.setChecked(True); eeg.stateChanged.connect(lambda s: setattr(self,"_eeg_only", bool(s))); r3.addWidget(eeg)
        eog = QCheckBox("EOG");  eog.stateChanged.connect(lambda s: setattr(self,"_incl_eog", bool(s))); r3.addWidget(eog)
        emg = QCheckBox("EMG");  emg.stateChanged.connect(lambda s: setattr(self,"_incl_emg", bool(s))); r3.addWidget(emg)
        st  = QCheckBox("STIM"); st.stateChanged.connect(lambda s: setattr(self,"_incl_stim", bool(s))); r3.addWidget(st)
        r3.addStretch(1); pv.addLayout(r3)

        self._status = QLabel("No file" if HAVE_MNE else f"Install mne (err: {_MNE_ERR})")
        pv.addWidget(self._status)

        v.addWidget(CollapsibleSection("Paramètres lecteur", panel, collapsed=True))
        w.destroyed.connect(lambda *a: self._timer.stop())
        return w

    def execute(self, **_):
        return {}

    # ------- open / read -------
    def _on_open(self):
        if not HAVE_MNE:
            if self._status: self._status.setText(f"Install mne (err: {_MNE_ERR})"); return
        path, _ = QFileDialog.getOpenFileName(None, "Open EEG file", os.getcwd(), _filters())
        if not path: return

        low = path.lower()
        if ".ds" in low and not low.endswith(".ds"):
            p = path[:low.find(".ds")+3]
            if os.path.isdir(p): path = p

        ok, msg = self._load(path)
        if self._status: self._status.setText(msg)
        if ok:
            self.outputs["raw"].on_next(self._raw)
            self._idx = 0
            self._emit_meta(reset=True)   # <-- émet ch_names + sfreq ici
            self._tick()                  # 1er segment immédiat
            self._apply_period(); self._timer.start()

    def _apply_period(self):
        step = max(self._chunk_s - self._overlap_s, 0.001)
        self._timer.setInterval(int(1000.0 * step))

    def _load(self, path: str) -> Tuple[bool,str]:
        try:
            raw = self._try_read(path)
            # picks
            if self._eeg_only:
                picks = mne.pick_types(raw.info, eeg=True, eog=False, emg=False, stim=False).tolist()
            else:
                picks = mne.pick_types(raw.info, eeg=True, eog=self._incl_eog, emg=self._incl_emg, stim=self._incl_stim).tolist()
            if not picks: return False, "No channels selected"
            raw.pick(picks)

            if self._resample_hz > 0:
                raw.resample(int(self._resample_hz), npad="auto")

            self._raw = raw
            self._path = path
            self._names = list(raw.ch_names)
            self._sf = float(raw.info["sfreq"])
            self._n_samp = int(raw.n_times)
            return True, f"Loaded {os.path.basename(path)} | {len(self._names)} ch @ {self._sf:.2f} Hz"
        except Exception as ex:
            self._raw = None
            return False, f"Load error: {ex}"

    def _try_read(self, path: str):
        low = path.lower()
        m = mne.io
        if low.endswith((".fif",".fif.gz")) and _has("read_raw_fif"): return m.read_raw_fif(path, preload=True, verbose="ERROR")
        if low.endswith((".edf",".bdf"))   and _has("read_raw_edf"): return m.read_raw_edf(path, preload=True, verbose="ERROR")
        if low.endswith(".gdf")            and _has("read_raw_gdf"): return m.read_raw_gdf(path, preload=True, verbose="ERROR")
        if low.endswith(".vhdr")           and _has("read_raw_brainvision"): return m.read_raw_brainvision(path, preload=True, verbose="ERROR")
        if low.endswith(".set")            and _has("read_raw_eeglab"): return m.read_raw_eeglab(path, preload=True, verbose="ERROR")
        if low.endswith(".mff")            and _has("read_raw_mff"): return m.read_raw_mff(path, preload=True, verbose="ERROR")
        if low.endswith(".raw")            and _has("read_raw_egi"): return m.read_raw_egi(path, preload=True, verbose="ERROR")
        if low.endswith(".cnt")            and _has("read_raw_cnt"): return m.read_raw_cnt(path, preload=True, verbose="ERROR")
        if low.endswith(".ds")             and _has("read_raw_ctf"): return m.read_raw_ctf(path, preload=True, verbose="ERROR")
        if low.endswith((".sqd",".con"))   and _has("read_raw_kit"): return m.read_raw_kit(path, preload=True, verbose="ERROR")
        if low.endswith(".trc")            and _has("read_raw_micromed"): return m.read_raw_micromed(path, preload=True, verbose="ERROR")
        if low.endswith((".eeg",".hdr"))   and _has("read_raw_nicolet"): return m.read_raw_nicolet(path, preload=True, verbose="ERROR")
        if low.endswith(".eeg")            and _has("read_raw_nihon"): return m.read_raw_nihon(path, preload=True, verbose="ERROR")
        if low.endswith((".lay",".dat"))   and _has("read_raw_persyst"): return m.read_raw_persyst(path, preload=True, verbose="ERROR")
        if low.endswith(".dat")            and _has("read_raw_bci2000"): return m.read_raw_bci2000(path, preload=True, verbose="ERROR")
        # fallback
        if _has("read_raw_edf"): return m.read_raw_edf(path, preload=True, verbose="ERROR")
        if _has("read_raw_fif"): return m.read_raw_fif(path, preload=True, verbose="ERROR")
        raise RuntimeError("No suitable MNE reader for this file")

    # ------- streaming -------
    def _tick(self):
        if self._raw is None: self._timer.stop(); return
        sf = self._sf
        n = int(round(self._chunk_s * sf))
        step = max(int(round((self._chunk_s - self._overlap_s) * sf)), 1)

        start = self._idx
        stop = min(start + n, self._n_samp)
        if stop <= start:
            if self._loop: self._idx = 0; self._emit_meta(reset=True)
            else: self._timer.stop()
            return

        try:
            if self._units == "uV":
                try: data = self._raw.get_data(start=start, stop=stop, units="uV")
                except TypeError: data = self._raw.get_data(start=start, stop=stop) * 1e6
            else:
                data = self._raw.get_data(start=start, stop=stop)
        except Exception:
            return
        if data.ndim == 1: data = data[None, :]
        if data.shape[0] > data.shape[1]: data = data.T

        # events (annotations dans la fenêtre)
        ann = None
        if getattr(self._raw, "annotations", None):
            t0 = start / sf; t1 = stop / sf
            items = []
            for a in self._raw.annotations:
                on = float(a["onset"])
                if t0 <= on < t1:
                    items.append({"type": str(a["description"]), "onset_s": on, "duration_s": float(a["duration"])})
            if items: ann = {"type":"annotations","items":items,"t0_s":t0,"t1_s":t1}

        # sorties (NE PAS renvoyer ch_names/sfreq ici)
        self.outputs["segment"].on_next(np.asarray(data, dtype=np.float32, order="C"))
        if ann: self.outputs["event"].on_next(ann)

        self._idx = start + step
        if self._idx >= self._n_samp:
            if self._loop: self._idx = 0; self._emit_meta(reset=True)
            else: self._timer.stop()

    def _emit_meta(self, reset=False):
        info = {"path": self._path, "n_channels": len(self._names), "sfreq": self._sf,
                "n_samples": self._n_samp, "units": self._units, "reset": bool(reset)}
        self.outputs["info"].on_next(info)
        # ch_names + sfreq envoyés au reset UNIQUEMENT
        self.outputs["ch_names"].on_next(list(self._names))
        self.outputs["sfreq"].on_next(float(self._sf) if self._sf else None)
