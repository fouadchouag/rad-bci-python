# plugins/eeg_universal_reader.py
# -*- coding: utf-8 -*-
"""
EEGUniversalReader — MNE only
- Ouvre les formats MNE (edf/bdf/gdf/fif/brainvision/eeglab/ctf/…)
- Sorties:
    raw      : mne.io.BaseRaw
    segment  : np.ndarray float32 (n_ch, n_samples)
    ch_names : list[str]            [émis au reset UNIQUEMENT]
    sfreq    : float                [émis au reset UNIQUEMENT]
    info     : dict {path, n_channels, sfreq, n_samples, units, reset}
    event    : dict (annotations visibles dans la fenêtre)
- Autoplay: dès qu’un fichier est choisi, le flux `segment` démarre (thread).
"""
import os
from typing import Optional, List, Tuple
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import QTimer, QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QFileDialog, QComboBox, QLayout, QSizePolicy,
    QStyle
)

from core.node_base import BasePlugin
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
        ((".fif", ".fif.gz"), "read_raw_fif"),
        ((".edf", ".bdf"), "read_raw_edf"),
        ((".gdf",), "read_raw_gdf"),
        ((".vhdr",), "read_raw_brainvision"),
        ((".set",), "read_raw_eeglab"),
        ((".mff",), "read_raw_mff"),
        ((".raw",), "read_raw_egi"),
        ((".cnt",), "read_raw_cnt"),
        ((".ds",), "read_raw_ctf"),
        ((".sqd", ".con"), "read_raw_kit"),
        ((".trc",), "read_raw_micromed"),
        ((".eeg", ".hdr"), "read_raw_nicolet"),
        ((".eeg",), "read_raw_nihon"),
        ((".lay", ".dat"), "read_raw_persyst"),
        ((".dat",), "read_raw_bci2000"),
    ]
    for exts, fn in MAP:
        if _has(fn):
            groups.append(f"{fn} ({' '.join('*'+e for e in exts)})")
            all_ext.extend(exts)
    all_pat = " ".join(sorted(set('*'+e for e in all_ext))) if all_ext else "*"
    s = f"All supported ({all_pat})"
    if groups:
        s += ";;" + ";;".join(groups)
    s += ";;All files (*)"
    return s


# ---------- worker de streaming (hors thread UI) ----------
class _EEGReadWorker(QObject):
    segReady = pyqtSignal(object)                  # np.ndarray float32 (n_ch, n_s)
    eventReady = pyqtSignal(object)                # dict | None
    metaReset = pyqtSignal(object, list, float)    # info(dict), ch_names, sfreq
    finished = pyqtSignal()

    def __init__(self, raw, units="V", chunk_s=1.0, overlap_s=0.0, loop=False):
        super().__init__()
        self.raw = raw
        self.units = str(units)
        self.chunk_s = float(chunk_s)
        self.overlap_s = float(overlap_s)
        self.loop = bool(loop)
        self._running = True
        self._idx = 0

    def configure(self, *, units=None, chunk_s=None, overlap_s=None, loop=None):
        if units is not None:
            self.units = str(units)
        if chunk_s is not None:
            self.chunk_s = float(chunk_s)
        if overlap_s is not None:
            self.overlap_s = float(overlap_s)
        if loop is not None:
            self.loop = bool(loop)

    def stop(self):
        self._running = False

    def run(self):
        try:
            import time
            raw = self.raw
            sf = float(raw.info["sfreq"])
            n_tot = int(raw.n_times)
            names = list(raw.ch_names)

            info = {
                "path": None,
                "n_channels": len(names),
                "sfreq": sf,
                "n_samples": n_tot,
                "units": self.units,
                "reset": True,
            }
            self.metaReset.emit(info, names, sf)

            while self._running and sf > 0 and n_tot > 0:
                n = max(1, int(round(self.chunk_s * sf)))
                step = max(1, int(round((self.chunk_s - self.overlap_s) * sf)))

                start = self._idx
                stop = min(start + n, n_tot)
                if stop <= start:
                    if self.loop:
                        self._idx = 0
                        info = {
                            "path": None,
                            "n_channels": len(names),
                            "sfreq": sf,
                            "n_samples": n_tot,
                            "units": self.units,
                            "reset": True,
                        }
                        self.metaReset.emit(info, names, sf)
                        continue
                    break

                if self.units == "uV":
                    try:
                        data = raw.get_data(start=start, stop=stop, units="uV")
                    except TypeError:
                        data = raw.get_data(start=start, stop=stop) * 1e6
                else:
                    data = raw.get_data(start=start, stop=stop)

                if data.ndim == 1:
                    data = data[None, :]
                if data.shape[0] > data.shape[1]:
                    data = data.T
                self.segReady.emit(np.asarray(data, dtype=np.float32, order="C"))

                if getattr(raw, "annotations", None):
                    t0 = start / sf
                    t1 = stop / sf
                    items = []
                    for a in raw.annotations:
                        # même schéma que le code d’origine (indexation dict-like)
                        on = float(a["onset"])
                        if t0 <= on < t1:
                            items.append(
                                {
                                    "type": str(a["description"]),
                                    "onset_s": on,
                                    "duration_s": float(a["duration"]),
                                }
                            )
                    if items:
                        self.eventReady.emit(
                            {"type": "annotations", "items": items, "t0_s": t0, "t1_s": t1}
                        )

                self._idx = start + step
                # cadence soft temps-réel
                time.sleep(max(self.chunk_s - self.overlap_s, 0.001))
        except Exception:
            pass
        self.finished.emit()


class EEGUniversalReader(BasePlugin):
    name = "EEGUniversalReader"
    language = "Python"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True

    # -------------- lifecycle --------------
    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["segment"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"] = BehaviorSubject(None)
        self.outputs["info"] = BehaviorSubject(None)
        self.outputs["event"] = BehaviorSubject(None)

        self._raw: Optional["mne.io.BaseRaw"] = None
        self._path: Optional[str] = None
        self._names: List[str] = []
        self._sf: float = 0.0
        self._n_samp: int = 0

        self._units = "V"          # V or uV
        self._chunk_s = 1.0
        self._overlap_s = 0.0
        self._loop = False
        self._resample_hz = 0

        self._eeg_only = True
        self._incl_eog = False
        self._incl_emg = False
        self._incl_stim = False

        # worker thread
        self._thr: Optional[QThread] = None
        self._worker: Optional[_EEGReadWorker] = None

        # UI refs
        self._status = None
        self._sp_chunk = None
        self._sp_overlap = None
        self._sp_resample = None
        self._cb_units = None
        self._cb_loop = None
        self._chk_eeg = self._chk_eog = self._chk_emg = self._chk_stim = None

    def build_widget(self):
        w = QWidget()
        UiKit.apply_node_style(w)
        v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        pv.setSpacing(8)

        r1 = QHBoxLayout()
        btn_open = UiKit.make_btn("Open EEG…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_open.clicked.connect(self._on_open)
        r1.addWidget(btn_open)
        self._cb_loop = QCheckBox("Loop")
        self._cb_loop.stateChanged.connect(lambda s: self._set_loop(bool(s)))
        r1.addWidget(self._cb_loop)
        r1.addStretch(1)
        pv.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("chunk (s):"))
        self._sp_chunk = QDoubleSpinBox()
        self._sp_chunk.setRange(0.05, 30.0)
        self._sp_chunk.setSingleStep(0.05)
        self._sp_chunk.setValue(self._chunk_s)
        self._sp_chunk.valueChanged.connect(lambda v: self._set_chunk(float(v)))
        r2.addWidget(self._sp_chunk)

        r2.addWidget(QLabel("overlap (s):"))
        self._sp_overlap = QDoubleSpinBox()
        self._sp_overlap.setRange(0, 29.9)
        self._sp_overlap.setSingleStep(0.05)
        self._sp_overlap.setValue(self._overlap_s)
        self._sp_overlap.valueChanged.connect(lambda v: self._set_overlap(float(v)))
        r2.addWidget(self._sp_overlap)

        r2.addWidget(QLabel("resample (Hz, 0=off):"))
        self._sp_resample = QSpinBox()
        self._sp_resample.setRange(0, 4096)
        self._sp_resample.setValue(self._resample_hz)
        self._sp_resample.valueChanged.connect(lambda v: self._set_resample(int(v)))
        r2.addWidget(self._sp_resample)

        r2.addSpacing(8)
        r2.addWidget(QLabel("units:"))
        self._cb_units = QComboBox()
        self._cb_units.addItems(["V", "uV"])
        self._cb_units.setCurrentText(self._units)
        self._cb_units.currentTextChanged.connect(lambda t: self._set_units(t))
        r2.addWidget(self._cb_units)
        r2.addStretch(1)
        pv.addLayout(r2)

        r3 = QHBoxLayout()
        self._chk_eeg = QCheckBox("EEG only")
        self._chk_eeg.setChecked(True)
        self._chk_eeg.stateChanged.connect(lambda s: self._set_eeg_only(bool(s)))
        r3.addWidget(self._chk_eeg)
        self._chk_eog = QCheckBox("EOG")
        self._chk_eog.stateChanged.connect(lambda s: setattr(self, "_incl_eog", bool(s)))
        r3.addWidget(self._chk_eog)
        self._chk_emg = QCheckBox("EMG")
        self._chk_emg.stateChanged.connect(lambda s: setattr(self, "_incl_emg", bool(s)))
        r3.addWidget(self._chk_emg)
        self._chk_stim = QCheckBox("STIM")
        self._chk_stim.stateChanged.connect(lambda s: setattr(self, "_incl_stim", bool(s)))
        r3.addWidget(self._chk_stim)
        r3.addStretch(1)
        pv.addLayout(r3)

        self._status = QLabel("No file" if HAVE_MNE else f"Install mne (err: {_MNE_ERR})")
        pv.addWidget(self._status)

        v.addWidget(CollapsibleSection("Paramètres lecteur", panel, collapsed=True))
        w.destroyed.connect(lambda *a: self._stop_worker())
        return w

    # -------------- config i/o --------------
    def export_config(self) -> dict:
        return {
            "units": self._units,
            "chunk_s": float(self._chunk_s),
            "overlap_s": float(self._overlap_s),
            "loop": bool(self._loop),
            "resample_hz": int(self._resample_hz),
            "eeg_only": bool(self._eeg_only),
            "incl_eog": bool(self._incl_eog),
            "incl_emg": bool(self._incl_emg),
            "incl_stim": bool(self._incl_stim),
            "path": self._path or "",
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        self._units = str(cfg.get("units", self._units))
        self._chunk_s = float(cfg.get("chunk_s", self._chunk_s))
        self._overlap_s = float(cfg.get("overlap_s", self._overlap_s))
        self._loop = bool(cfg.get("loop", self._loop))
        self._resample_hz = int(cfg.get("resample_hz", self._resample_hz))
        self._eeg_only = bool(cfg.get("eeg_only", self._eeg_only))
        self._incl_eog = bool(cfg.get("incl_eog", self._incl_eog))
        self._incl_emg = bool(cfg.get("incl_emg", self._incl_emg))
        self._incl_stim = bool(cfg.get("incl_stim", self._incl_stim))

        if self._cb_units:
            self._cb_units.blockSignals(True)
            self._cb_units.setCurrentText(self._units)
            self._cb_units.blockSignals(False)
        for sp, val in [
            (self._sp_chunk, self._chunk_s),
            (self._sp_overlap, self._overlap_s),
            (self._sp_resample, self._resample_hz),
        ]:
            if sp is not None:
                sp.blockSignals(True)
                sp.setValue(val)
                sp.blockSignals(False)
        if self._cb_loop:
            self._cb_loop.blockSignals(True)
            self._cb_loop.setChecked(self._loop)
            self._cb_loop.blockSignals(False)
        if self._chk_eeg:
            self._chk_eeg.blockSignals(True)
            self._chk_eeg.setChecked(self._eeg_only)
            self._chk_eeg.blockSignals(False)
        if self._chk_eog:
            self._chk_eog.blockSignals(True)
            self._chk_eog.setChecked(self._incl_eog)
            self._chk_eog.blockSignals(False)
        if self._chk_emg:
            self._chk_emg.blockSignals(True)
            self._chk_emg.setChecked(self._incl_emg)
            self._chk_emg.blockSignals(False)
        if self._chk_stim:
            self._chk_stim.blockSignals(True)
            self._chk_stim.setChecked(self._incl_stim)
            self._chk_stim.blockSignals(False)

        self._reconfigure_worker()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "units": {"enum": ["V", "uV"], "labels": ["volts", "microvolts"]},
                "chunk_s": {"type": "float", "min": 0.05, "max": 30.0, "step": 0.05},
                "overlap_s": {"type": "float", "min": 0.0, "max": 29.9, "step": 0.05},
                "loop": {"type": "bool"},
                "resample_hz": {"type": "int", "min": 0, "max": 4096},
                "eeg_only": {"type": "bool"},
                "incl_eog": {"type": "bool"},
                "incl_emg": {"type": "bool"},
                "incl_stim": {"type": "bool"},
                "path": {"type": "str", "help": "dernier chemin ouvert (lecture seule)"},
            }
        }

    # -------------- setters (maj worker live) --------------
    def _set_chunk(self, v):
        self._chunk_s = float(v)
        self._reconfigure_worker()

    def _set_overlap(self, v):
        self._overlap_s = float(v)
        self._reconfigure_worker()

    def _set_units(self, t):
        self._units = str(t)
        self._reconfigure_worker()

    def _set_loop(self, b):
        self._loop = bool(b)
        self._reconfigure_worker()

    def _set_resample(self, hz):
        self._resample_hz = int(hz)

    def _set_eeg_only(self, b):
        self._eeg_only = bool(b)

    def _reconfigure_worker(self):
        if self._worker:
            try:
                self._worker.configure(
                    units=self._units,
                    chunk_s=self._chunk_s,
                    overlap_s=self._overlap_s,
                    loop=self._loop,
                )
            except Exception:
                pass

    # -------------- runtime --------------
    def execute(self, **_):
        return {}

    def _stop_worker(self):
        try:
            if self._worker:
                self._worker.stop()
        except Exception:
            pass
        try:
            if self._thr and self._thr.isRunning():
                self._thr.quit()
                self._thr.wait(3000)
        except Exception:
            pass
        self._worker = None
        self._thr = None

    # ------- open / read -------
    def _on_open(self):
        if not HAVE_MNE:
            if self._status:
                self._status.setText(f"Install mne (err: {_MNE_ERR})")
            return
        path, _ = QFileDialog.getOpenFileName(None, "Open EEG file", os.getcwd(), _filters())
        if not path:
            return

        low = path.lower()
        if ".ds" in low and not low.endswith(".ds"):
            p = path[: low.find(".ds") + 3]
            if os.path.isdir(p):
                path = p

        ok, msg = self._load(path)
        if self._status:
            self._status.setText(msg)
        if ok:
            self.outputs["raw"].on_next(self._raw)
            self._start_stream_worker()

    def _start_stream_worker(self):
        self._stop_worker()
        if self._raw is None:
            return
        self._thr = QThread()
        self._worker = _EEGReadWorker(
            self._raw,
            units=self._units,
            chunk_s=self._chunk_s,
            overlap_s=self._overlap_s,
            loop=self._loop,
        )
        self._worker.moveToThread(self._thr)
        self._thr.started.connect(self._worker.run)
        self._worker.segReady.connect(lambda arr: self.outputs["segment"].on_next(arr))
        self._worker.eventReady.connect(lambda ev: self.outputs["event"].on_next(ev))
        self._worker.metaReset.connect(self._on_meta_reset)
        self._worker.finished.connect(self._thr.quit)
        self._thr.finished.connect(self._thr.deleteLater)
        self._thr.start()

    def _on_meta_reset(self, info, ch_names, sfreq):
        self._names = list(ch_names or [])
        self._sf = float(sfreq or 0.0)
        self._n_samp = int(info.get("n_samples", 0)) if isinstance(info, dict) else 0
        info2 = dict(info or {})
        info2["units"] = self._units
        self.outputs["info"].on_next(info2)
        self.outputs["ch_names"].on_next(list(self._names))
        self.outputs["sfreq"].on_next(float(self._sf) if self._sf else None)

    def _load(self, path: str) -> Tuple[bool, str]:
        try:
            raw = self._try_read(path)
            if self._eeg_only:
                picks = mne.pick_types(raw.info, eeg=True, eog=False, emg=False, stim=False).tolist()
            else:
                picks = mne.pick_types(
                    raw.info,
                    eeg=True,
                    eog=self._incl_eog,
                    emg=self._incl_emg,
                    stim=self._incl_stim,
                ).tolist()
            if not picks:
                return False, "No channels selected"
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
        if low.endswith((".fif", ".fif.gz")) and _has("read_raw_fif"):
            return m.read_raw_fif(path, preload=True, verbose="ERROR")
        if low.endswith((".edf", ".bdf")) and _has("read_raw_edf"):
            return m.read_raw_edf(path, preload=True, verbose="ERROR")
        if low.endswith(".gdf") and _has("read_raw_gdf"):
            return m.read_raw_gdf(path, preload=True, verbose="ERROR")
        if low.endswith(".vhdr") and _has("read_raw_brainvision"):
            return m.read_raw_brainvision(path, preload=True, verbose="ERROR")
        if low.endswith(".set") and _has("read_raw_eeglab"):
            return m.read_raw_eeglab(path, preload=True, verbose="ERROR")
        if low.endswith(".mff") and _has("read_raw_mff"):
            return m.read_raw_mff(path, preload=True, verbose="ERROR")
        if low.endswith(".raw") and _has("read_raw_egi"):
            return m.read_raw_egi(path, preload=True, verbose="ERROR")
        if low.endswith(".cnt") and _has("read_raw_cnt"):
            return m.read_raw_cnt(path, preload=True, verbose="ERROR")
        if low.endswith(".ds") and _has("read_raw_ctf"):
            return m.read_raw_ctf(path, preload=True, verbose="ERROR")
        if low.endswith((".sqd", ".con")) and _has("read_raw_kit"):
            return m.read_raw_kit(path, preload=True, verbose="ERROR")
        if low.endswith(".trc") and _has("read_raw_micromed"):
            return m.read_raw_micromed(path, preload=True, verbose="ERROR")
        if low.endswith((".eeg", ".hdr")) and _has("read_raw_nicolet"):
            return m.read_raw_nicolet(path, preload=True, verbose="ERROR")
        if low.endswith(".eeg") and _has("read_raw_nihon"):
            return m.read_raw_nihon(path, preload=True, verbose="ERROR")
        if low.endswith((".lay", ".dat")) and _has("read_raw_persyst"):
            return m.read_raw_persyst(path, preload=True, verbose="ERROR")
        if low.endswith(".dat") and _has("read_raw_bci2000"):
            return m.read_raw_bci2000(path, preload=True, verbose="ERROR")
        # fallbacks
        if _has("read_raw_edf"):
            return m.read_raw_edf(path, preload=True, verbose="ERROR")
        if _has("read_raw_fif"):
            return m.read_raw_fif(path, preload=True, verbose="ERROR")
        raise RuntimeError("No suitable MNE reader for this file")
