# plugins/eeg_universal_reader.py (final, métriques étendues)
# -*- coding: utf-8 -*-
"""
EEGUniversalReader — ultra-fast, tous formats MNE, avec métriques enrichies:
- FILE_OPEN/READY/ERROR, READ_START/STOP, META_RESET, EVENTS
- SAMPLES_PROCESSED (par chunk), READER_STATS (throughput ~1Hz)
"""
import os, atexit, json, time
import datetime as _dt
from typing import Optional, List
import numpy as np
from rx.subject import BehaviorSubject

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QDoubleSpinBox, QSpinBox, QFileDialog, QComboBox, QLayout, QSizePolicy,
    QStyle, QApplication, QDialog, QTextEdit, QTabWidget, QPushButton
)

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection
from core.metrics_logger import metrics

try:
    import mne
    HAVE_MNE = True
except Exception as e:
    HAVE_MNE = False
    _MNE_ERR = str(e)

# ------------ Utilitaires JSON-safe ------------
def _jsonify(obj):
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    try:
        import numpy as _np
        if isinstance(obj, (_np.integer, _np.floating, _np.bool_)):
            return obj.item()
        if isinstance(obj, _np.ndarray):
            return [_jsonify(x) for x in obj.tolist()]
    except Exception:
        pass
    if hasattr(os, "fspath"):
        try: return os.fspath(obj)
        except Exception: pass
    if isinstance(obj, (_dt.datetime, _dt.date)):
        try: return obj.isoformat()
        except Exception: return str(obj)
    if isinstance(obj, (list, tuple)):
        return [_jsonify(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    return str(obj)

def _dumps_json(obj) -> str:
    return json.dumps(_jsonify(obj), indent=2, ensure_ascii=False)

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

# ---------- Workers ----------
class _EEGReadWorker(QObject):
    segReady = pyqtSignal(object)
    eventReady = pyqtSignal(object)
    metaReset = pyqtSignal(object, list, float)
    finished = pyqtSignal()

    def __init__(self, raw, *, units="V", chunk_s=1.0, overlap_s=0.0, loop=False,
                 emit_annotations=True, stream_decim=1):
        super().__init__(parent=None)
        self.raw = raw
        self.units = str(units)
        self.chunk_s = float(chunk_s)
        self.overlap_s = float(overlap_s)
        self.loop = bool(loop)
        self.emit_annotations = bool(emit_annotations)
        self.stream_decim = max(1, int(stream_decim))
        self._running = True
        self._idx = 0
        # métriques
        self._samples_total = 0
        self._stat_last_t = time.time()

    def configure(self, *, units=None, chunk_s=None, overlap_s=None, loop=None,
                  emit_annotations=None, stream_decim=None):
        if units is not None: self.units = str(units)
        if chunk_s is not None: self.chunk_s = float(chunk_s)
        if overlap_s is not None: self.overlap_s = float(overlap_s)
        if loop is not None: self.loop = bool(loop)
        if emit_annotations is not None: self.emit_annotations = bool(emit_annotations)
        if stream_decim is not None: self.stream_decim = max(1, int(stream_decim))

    def stop(self): self._running = False

    def run(self):
        try:
            raw = self.raw
            sf = float(raw.info["sfreq"]) if hasattr(raw, "info") else 0.0
            n_tot = int(getattr(raw, "n_times", 0))
            names = list(getattr(raw, "ch_names", []) or [])

            info = {"path": None, "n_channels": len(names), "sfreq": sf, "n_samples": n_tot,
                    "units": self.units, "reset": True}
            self.metaReset.emit(info, names, sf)

            while self._running and sf > 0 and n_tot > 0:
                n = max(1, int(round(self.chunk_s * sf)))
                step = max(1, int(round((self.chunk_s - self.overlap_s) * sf)))

                start = self._idx
                stop = min(start + n, n_tot)
                if stop <= start:
                    if self.loop:
                        self._idx = 0
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

                if self.stream_decim > 1:
                    data = data[:, :: self.stream_decim]

                if data.ndim == 1:
                    data = data[None, :]
                if data.shape[0] > data.shape[1]:
                    data = data.T

                arr = np.asarray(data, dtype=np.float32, order="C")
                self.segReady.emit(arr)

                # ---- METRICS: samples & throughput (~1Hz) ----
                try:
                    n_samp = int(arr.shape[1])
                    self._samples_total += max(0, n_samp)
                    metrics().samples_processed(n=n_samp)
                    now = time.time()
                    if now - self._stat_last_t >= 1.0:
                        dt = max(1e-9, now - self._stat_last_t)
                        thr = (self._samples_total / dt)  # ~ "depuis dernière fenêtre"
                        metrics().reader_stats(throughput=thr)
                        self._samples_total = 0
                        self._stat_last_t = now
                except Exception:
                    pass

                # ---- annotations / events ----
                if self.emit_annotations and getattr(raw, "annotations", None):
                    t0 = start / sf
                    t1 = stop / sf
                    items = []
                    for a in raw.annotations:
                        on = float(a["onset"])
                        if t0 <= on < t1:
                            items.append({"type": str(a["description"]),
                                          "onset_s": on,
                                          "duration_s": float(a["duration"])})
                    if items:
                        self.eventReady.emit({"type": "annotations", "items": items, "t0_s": t0, "t1_s": t1})

                self._idx = start + step
                time.sleep(max(self.chunk_s - self.overlap_s, 0.001))
        except Exception:
            pass
        self.finished.emit()

class _EEGOpenWorker(QObject):
    """Ouvre le fichier en arrière-plan et renvoie (raw, message)."""
    ready = pyqtSignal(object, str)

    def __init__(self, path: str, cfg: dict):
        super().__init__(parent=None)
        self.path = path
        self.cfg = dict(cfg)

    def _preload_for_path(self, path: str, fast_open: bool):
        low = (path or "").lower()
        if not fast_open:
            return True
        if low.endswith((".fif", ".fif.gz")):
            return "memmap"
        return False

    def _call_reader(self, reader, path, *, preload, **kw):
        try:
            return reader(path, preload=preload, **kw)
        except TypeError:
            return reader(path, **kw)
        except Exception:
            if preload is False or preload == "memmap":
                try:
                    return reader(path, preload=True, **kw)
                except TypeError:
                    return reader(path, **kw)
            raise

    def _try_read(self, path: str, fast_open: bool, turbo_gdf: bool):
        import mne
        low = path.lower()
        m = mne.io
        pl = self._preload_for_path(path, fast_open)

        if low.endswith((".fif", ".fif.gz")) and hasattr(m, "read_raw_fif"):
            return self._call_reader(m.read_raw_fif, path, preload=pl, verbose="ERROR")
        if low.endswith((".edf", ".bdf")) and hasattr(m, "read_raw_edf"):
            return self._call_reader(m.read_raw_edf, path, preload=pl, verbose="ERROR")
        if low.endswith(".gdf") and hasattr(m, "read_raw_gdf"):
            stim = None if turbo_gdf else "auto"
            return self._call_reader(m.read_raw_gdf, path, preload=pl, stim_channel=stim, verbose="ERROR")
        if low.endswith(".vhdr") and hasattr(m, "read_raw_brainvision"):
            return self._call_reader(m.read_raw_brainvision, path, preload=pl, verbose="ERROR")
        if low.endswith(".set") and hasattr(m, "read_raw_eeglab"):
            return self._call_reader(m.read_raw_eeglab, path, preload=pl, verbose="ERROR")
        if low.endswith(".mff") and hasattr(m, "read_raw_mff"):
            return self._call_reader(m.read_raw_mff, path, preload=pl, verbose="ERROR")
        if low.endswith(".raw") and hasattr(m, "read_raw_egi"):
            return self._call_reader(m.read_raw_egi, path, preload=pl, verbose="ERROR")
        if low.endswith(".cnt") and hasattr(m, "read_raw_cnt"):
            return self._call_reader(m.read_raw_cnt, path, preload=pl, verbose="ERROR")
        if low.endswith(".ds") and hasattr(m, "read_raw_ctf"):
            return self._call_reader(m.read_raw_ctf, path, preload=pl, verbose="ERROR")
        if low.endswith((".sqd", ".con")) and hasattr(m, "read_raw_kit"):
            return self._call_reader(m.read_raw_kit, path, preload=pl, verbose="ERROR")
        if low.endswith(".trc") and hasattr(m, "read_raw_micromed"):
            return self._call_reader(m.read_raw_micromed, path, preload=pl, verbose="ERROR")
        if low.endswith((".eeg", ".hdr")) and hasattr(m, "read_raw_nicolet"):
            return self._call_reader(m.read_raw_nicolet, path, preload=pl, verbose="ERROR")
        if low.endswith(".eeg") and hasattr(m, "read_raw_nihon"):
            return self._call_reader(m.read_raw_nihon, path, preload=pl, verbose="ERROR")
        if low.endswith((".lay", ".dat")) and hasattr(m, "read_raw_persyst"):
            return self._call_reader(m.read_raw_persyst, path, preload=pl, verbose="ERROR")
        if low.endswith(".dat") and hasattr(m, "read_raw_bci2000"):
            return self._call_reader(m.read_raw_bci2000, path, preload=pl, verbose="ERROR")
        if hasattr(m, "read_raw_edf"):
            return self._call_reader(m.read_raw_edf, path, preload=pl, verbose="ERROR")
        if hasattr(m, "read_raw_fif"):
            return self._call_reader(m.read_raw_fif, path, preload=pl, verbose="ERROR")
        raise RuntimeError("No suitable MNE reader for this file")

    def run(self):
        try:
            import mne
            path = self.path
            cfg = self.cfg
            fast_open = bool(cfg.get("fast_open", True))
            turbo_gdf = bool(cfg.get("turbo_gdf", True))
            eeg_only = bool(cfg.get("eeg_only", True))
            incl_eog = bool(cfg.get("incl_eog", False))
            incl_emg = bool(cfg.get("incl_emg", False))
            incl_stim = bool(cfg.get("incl_stim", False))
            resample_hz = int(cfg.get("resample_hz", 0))
            smart_preview = bool(cfg.get("smart_preview", True))
            preview_s = float(cfg.get("preview_s", 0.0))
            bigfile_thr = float(cfg.get("bigfile_threshold_mb", 128.0))

            raw = self._try_read(path, fast_open, turbo_gdf)

            if eeg_only:
                picks = mne.pick_types(raw.info, eeg=True, eog=False, emg=False, stim=False).tolist()
            else:
                picks = mne.pick_types(raw.info, eeg=True, eog=incl_eog, emg=incl_emg, stim=incl_stim).tolist()
            if not picks:
                self.ready.emit(None, "No channels selected"); return
            raw.pick(picks)

            try:
                size_mb = os.path.getsize(path) / (1024 * 1024.0)
            except Exception:
                size_mb = 0.0

            do_preview = False
            if smart_preview and size_mb >= max(1.0, bigfile_thr):
                do_preview = True
                if preview_s <= 0:
                    preview_s = 30.0
            if preview_s > 0:
                do_preview = True
            if do_preview:
                tmax = max(0.01, float(preview_s))
                raw.crop(tmin=0.0, tmax=tmax, include_tmax=True)

            if resample_hz > 0:
                if not getattr(raw, "preload", False):
                    raw.load_data()
                raw.resample(int(resample_hz), npad="auto")

            sf = float(raw.info["sfreq"])
            msg = f"Loaded {os.path.basename(path)} | {len(raw.ch_names)} ch @ {sf:.2f} Hz"
            self.ready.emit(raw, msg)
        except Exception as ex:
            self.ready.emit(None, f"Load error: {ex}")

# ---------- Plugin ----------
class EEGUniversalReader(BasePlugin):
    name = "EEGUniversalReader"
    language = "Python"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True

    def __del__(self):
        try:
            self.on_remove()
        except Exception:
            pass

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

        self._units = "V"
        self._chunk_s = 1.0
        self._overlap_s = 0.0
        self._loop = False
        self._resample_hz = 0

        self._eeg_only = True
        self._incl_eog = False
        self._incl_emg = False
        self._incl_stim = False

        self._fast_open = True
        self._turbo_gdf = True
        self._emit_annotations = True

        self._open_async = True
        self._smart_preview = True
        self._preview_s = 0.0
        self._stream_decim = 1
        self._bigfile_threshold_mb = 128.0

        self._thr: Optional[QThread] = None
        self._worker: Optional[_EEGReadWorker] = None

        self._thr_open: Optional[QThread] = None
        self._worker_open: Optional[_EEGOpenWorker] = None

        self._status = None
        self._sp_chunk = self._sp_overlap = self._sp_resample = None
        self._cb_units = self._cb_loop = None
        self._chk_eeg = self._chk_eog = self._chk_emg = self._chk_stim = None
        self._chk_fast = self._chk_turbo_gdf = self._chk_emit_ann = None
        self._chk_open_async = None
        self._chk_smart_prev = None
        self._sp_preview_s = None
        self._sp_stream_decim = None
        self._sp_big_thr = None

        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self.on_remove)
        except Exception:
            pass
        atexit.register(self.on_remove)

    def _log_param(self, key, new, old=None):
        try:
            metrics().param_change(name=str(key), old=old, new=new)
        except Exception:
            pass

    def build_widget(self):
        w = QWidget()
        self._widget = w
        UiKit.apply_node_style(w)
        v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        panel = QWidget()
        pv = QVBoxLayout(panel); pv.setContentsMargins(8, 8, 8, 8); pv.setSpacing(8)

        # Ligne 1
        r1 = QHBoxLayout()
        btn_open = UiKit.make_btn("Open EEG…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_open.clicked.connect(self._on_open)
        r1.addWidget(btn_open)
        self._cb_loop = QCheckBox("Loop"); self._cb_loop.stateChanged.connect(lambda s: self._set_loop(bool(s)))
        r1.addWidget(self._cb_loop)
        btn_info = QPushButton("Infos fichier…")
        btn_info.clicked.connect(self._show_file_info)
        r1.addWidget(btn_info)
        r1.addStretch(1)
        pv.addLayout(r1)

        # Ligne 2
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("chunk (s):"))
        self._sp_chunk = QDoubleSpinBox(); self._sp_chunk.setRange(0.05, 30.0); self._sp_chunk.setSingleStep(0.05)
        self._sp_chunk.setValue(self._chunk_s); self._sp_chunk.valueChanged.connect(lambda v: self._set_chunk(float(v)))
        r2.addWidget(self._sp_chunk)
        r2.addWidget(QLabel("overlap (s):"))
        self._sp_overlap = QDoubleSpinBox(); self._sp_overlap.setRange(0, 29.9); self._sp_overlap.setSingleStep(0.05)
        self._sp_overlap.setValue(self._overlap_s); self._sp_overlap.valueChanged.connect(lambda v: self._set_overlap(float(v)))
        r2.addWidget(self._sp_overlap)
        r2.addWidget(QLabel("resample (Hz, 0=off):"))
        self._sp_resample = QSpinBox(); self._sp_resample.setRange(0, 4096); self._sp_resample.setValue(self._resample_hz)
        self._sp_resample.valueChanged.connect(lambda v: self._set_resample(int(v)))
        r2.addWidget(self._sp_resample)
        r2.addSpacing(8)
        r2.addWidget(QLabel("units:"))
        self._cb_units = QComboBox(); self._cb_units.addItems(["V", "uV"]); self._cb_units.setCurrentText(self._units)
        self._cb_units.currentTextChanged.connect(lambda t: self._set_units(t))
        r2.addWidget(self._cb_units)
        r2.addStretch(1)
        pv.addLayout(r2)

        # Ligne 3: types de canaux
        r3 = QHBoxLayout()
        self._chk_eeg = QCheckBox("EEG only"); self._chk_eeg.setChecked(True)
        self._chk_eeg.stateChanged.connect(lambda s: self._set_eeg_only(bool(s))); r3.addWidget(self._chk_eeg)
        self._chk_eog = QCheckBox("EOG"); self._chk_eog.stateChanged.connect(lambda s: self._set_incl_eog(bool(s))); r3.addWidget(self._chk_eog)
        self._chk_emg = QCheckBox("EMG"); self._chk_emg.stateChanged.connect(lambda s: self._set_incl_emg(bool(s))); r3.addWidget(self._chk_emg)
        self._chk_stim = QCheckBox("STIM"); self._chk_stim.stateChanged.connect(lambda s: self._set_incl_stim(bool(s))); r3.addWidget(self._chk_stim)
        r3.addStretch(1)
        pv.addLayout(r3)

        # Ligne 4
        r_fast = QHBoxLayout()
        self._chk_fast = QCheckBox("Fast open (lazy)"); self._chk_fast.setChecked(self._fast_open)
        self._chk_fast.setToolTip("Essaye preload=False/memmap et retombe sur True si besoin.")
        self._chk_fast.stateChanged.connect(lambda s: self._set_fast_open(bool(s))); r_fast.addWidget(self._chk_fast)
        self._chk_turbo_gdf = QCheckBox("Turbo GDF (skip STIM)"); self._chk_turbo_gdf.setChecked(self._turbo_gdf)
        self._chk_turbo_gdf.setToolTip("GDF uniquement: stim_channel=None à l'ouverture.")
        self._chk_turbo_gdf.stateChanged.connect(lambda s: self._set_turbo_gdf(bool(s))); r_fast.addWidget(self._chk_turbo_gdf)
        self._chk_emit_ann = QCheckBox("Emit annotations"); self._chk_emit_ann.setChecked(self._emit_annotations)
        self._chk_emit_ann.setToolTip("Désactive si trop d’annotations ralentissent la lecture.")
        self._chk_emit_ann.stateChanged.connect(lambda s: self._set_emit_annotations(bool(s))); r_fast.addWidget(self._chk_emit_ann)
        r_fast.addStretch(1)
        pv.addLayout(r_fast)

        # Ligne 5
        r_ultra = QHBoxLayout()
        self._chk_open_async = QCheckBox("Open asynchronously"); self._chk_open_async.setChecked(self._open_async)
        self._chk_open_async.setToolTip("Ouvre en arrière-plan (UI fluide).")
        self._chk_open_async.stateChanged.connect(lambda s: self._set_open_async(bool(s))); r_ultra.addWidget(self._chk_open_async)
        self._chk_smart_prev = QCheckBox("Smart preview"); self._chk_smart_prev.setChecked(self._smart_preview)
        self._chk_smart_prev.setToolTip("Gros fichiers: crop auto aux premières secondes.")
        self._chk_smart_prev.stateChanged.connect(lambda s: self._set_smart_preview(bool(s))); r_ultra.addWidget(self._chk_smart_prev)
        r_ultra.addWidget(QLabel("Preview seconds:"))
        self._sp_preview_s = QDoubleSpinBox(); self._sp_preview_s.setRange(0.0, 600.0); self._sp_preview_s.setSingleStep(1.0)
        self._sp_preview_s.setValue(self._preview_s); self._sp_preview_s.setToolTip("0=off; sinon crop(tmax) à l’ouverture.")
        self._sp_preview_s.valueChanged.connect(lambda v: self._set_preview_s(float(v))); r_ultra.addWidget(self._sp_preview_s)
        r_ultra.addWidget(QLabel("Bigfile threshold (MB):"))
        self._sp_big_thr = QDoubleSpinBox(); self._sp_big_thr.setRange(16.0, 16384.0); self._sp_big_thr.setDecimals(0)
        self._sp_big_thr.setValue(self._bigfile_threshold_mb)
        self._sp_big_thr.setToolTip("Seuil de taille pour déclencher le preview auto.")
        self._sp_big_thr.valueChanged.connect(lambda v: self._set_big_thr(float(v))); r_ultra.addWidget(self._sp_big_thr)
        r_ultra.addWidget(QLabel("Stream decim:"))
        self._sp_stream_decim = QSpinBox(); self._sp_stream_decim.setRange(1, 64); self._sp_stream_decim.setValue(self._stream_decim)
        self._sp_stream_decim.setToolTip("1=plein débit; >1: 1/k pour l’affichage.")
        self._sp_stream_decim.valueChanged.connect(lambda v: self._set_stream_decim(int(v))); r_ultra.addWidget(self._sp_stream_decim)
        r_ultra.addStretch(1)
        pv.addLayout(r_ultra)

        self._status = QLabel("No file" if HAVE_MNE else f"Install mne (err: {_MNE_ERR})")
        pv.addWidget(self._status)

        v.addWidget(CollapsibleSection("Paramètres lecteur", panel, collapsed=True))
        w.destroyed.connect(self.on_remove)
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
            "fast_open": bool(self._fast_open),
            "turbo_gdf": bool(self._turbo_gdf),
            "emit_annotations": bool(self._emit_annotations),
            "open_async": bool(self._open_async),
            "smart_preview": bool(self._smart_preview),
            "preview_s": float(self._preview_s),
            "stream_decim": int(self._stream_decim),
            "bigfile_threshold_mb": float(self._bigfile_threshold_mb),
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
        self._fast_open = bool(cfg.get("fast_open", self._fast_open))
        self._turbo_gdf = bool(cfg.get("turbo_gdf", self._turbo_gdf))
        self._emit_annotations = bool(cfg.get("emit_annotations", self._emit_annotations))
        self._open_async = bool(cfg.get("open_async", self._open_async))
        self._smart_preview = bool(cfg.get("smart_preview", self._smart_preview))
        self._preview_s = float(cfg.get("preview_s", self._preview_s))
        self._stream_decim = int(cfg.get("stream_decim", self._stream_decim))
        self._bigfile_threshold_mb = float(cfg.get("bigfile_threshold_mb", self._bigfile_threshold_mb))

        if self._cb_units:
            self._cb_units.blockSignals(True); self._cb_units.setCurrentText(self._units); self._cb_units.blockSignals(False)
        for sp, val in [(self._sp_chunk, self._chunk_s), (self._sp_overlap, self._overlap_s), (self._sp_resample, self._resample_hz),
                        (self._sp_preview_s, self._preview_s), (self._sp_stream_decim, self._stream_decim),
                        (self._sp_big_thr, self._bigfile_threshold_mb)]:
            if sp is not None:
                sp.blockSignals(True); sp.setValue(val); sp.blockSignals(False)
        for cb, val in [(self._cb_loop, self._loop), (self._chk_eeg, self._eeg_only),
                        (self._chk_fast, self._fast_open), (self._chk_turbo_gdf, self._turbo_gdf),
                        (self._chk_emit_ann, self._emit_annotations), (self._chk_open_async, self._open_async),
                        (self._chk_smart_prev, self._smart_preview), (self._chk_eog, self._incl_eog),
                        (self._chk_emg, self._incl_emg), (self._chk_stim, self._incl_stim)]:
            if cb is not None:
                cb.blockSignals(True); cb.setChecked(val); cb.blockSignals(False)

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
                "fast_open": {"type": "bool", "label": "Fast open (lazy)"},
                "turbo_gdf": {"type": "bool", "label": "Turbo GDF (skip STIM)"},
                "emit_annotations": {"type": "bool", "label": "Emit annotations"},
                "open_async": {"type": "bool", "label": "Open asynchronously"},
                "smart_preview": {"type": "bool", "label": "Smart preview"},
                "preview_s": {"type": "float", "min": 0, "max": 600, "step": 1.0},
                "stream_decim": {"type": "int", "min": 1, "max": 64},
                "bigfile_threshold_mb": {"type": "float", "min": 16, "max": 16384, "step": 1},
                "path": {"type": "str", "help": "dernier chemin ouvert (lecture seule)"},
            }
        }

    # -------------- setters / reconfig --------------
    def _set_chunk(self, v):
        old = self._chunk_s; self._chunk_s = float(v); self._log_param("chunk_s", self._chunk_s, old); self._reconfigure_worker()
    def _set_overlap(self, v):
        old = self._overlap_s; self._overlap_s = float(v); self._log_param("overlap_s", self._overlap_s, old); self._reconfigure_worker()
    def _set_units(self, t):
        old = self._units; self._units = str(t); self._log_param("units", self._units, old); self._reconfigure_worker()
    def _set_loop(self, b):
        old = self._loop; self._loop = bool(b); self._log_param("loop", int(self._loop), int(old)); self._reconfigure_worker()
    def _set_resample(self, hz):
        old = self._resample_hz; self._resample_hz = int(hz); self._log_param("resample_hz", self._resample_hz, old)
    def _set_eeg_only(self, b):
        old = getattr(self, "_eeg_only", True); self._eeg_only = bool(b); self._log_param("eeg_only", int(self._eeg_only), int(old))
    def _set_incl_eog(self, b):
        old = self._incl_eog; self._incl_eog = bool(b); self._log_param("incl_eog", int(self._incl_eog), int(old))
    def _set_incl_emg(self, b):
        old = self._incl_emg; self._incl_emg = bool(b); self._log_param("incl_emg", int(self._incl_emg), int(old))
    def _set_incl_stim(self, b):
        old = self._incl_stim; self._incl_stim = bool(b); self._log_param("incl_stim", int(self._incl_stim), int(old))
    def _set_fast_open(self, b):
        old = self._fast_open; self._fast_open = bool(b); self._log_param("fast_open", int(self._fast_open), int(old))
    def _set_turbo_gdf(self, b):
        old = self._turbo_gdf; self._turbo_gdf = bool(b); self._log_param("turbo_gdf", int(self._turbo_gdf), int(old))
    def _set_emit_annotations(self, b):
        old = self._emit_annotations; self._emit_annotations = bool(b); self._log_param("emit_annotations", int(self._emit_annotations), int(old)); self._reconfigure_worker()
    def _set_open_async(self, b):
        old = self._open_async; self._open_async = bool(b); self._log_param("open_async", int(self._open_async), int(old))
    def _set_smart_preview(self, b):
        old = self._smart_preview; self._smart_preview = bool(b); self._log_param("smart_preview", int(self._smart_preview), int(old))
    def _set_preview_s(self, v):
        old = self._preview_s; self._preview_s = float(v); self._log_param("preview_s", self._preview_s, old)
    def _set_stream_decim(self, v):
        old = self._stream_decim; self._stream_decim = int(v); self._log_param("stream_decim", self._stream_decim, old); self._reconfigure_worker()
    def _set_big_thr(self, v):
        old = self._bigfile_threshold_mb; self._bigfile_threshold_mb = float(v); self._log_param("bigfile_threshold_mb", self._bigfile_threshold_mb, old)

    def _reconfigure_worker(self):
        if self._worker:
            try:
                self._worker.configure(
                    units=self._units,
                    chunk_s=self._chunk_s,
                    overlap_s=self._overlap_s,
                    loop=self._loop,
                    emit_annotations=self._emit_annotations,
                    stream_decim=self._stream_decim,
                )
            except Exception:
                pass

    # -------------- runtime --------------
    def execute(self, **_):
        return {}

    def _stop_worker(self):
        try:
            if self._worker:
                try: self._worker.stop()
                except Exception: pass
        except Exception:
            pass
        th = self._thr
        if th is None:
            self._worker = None
            return
        try: th.requestInterruption()
        except Exception: pass
        try: th.quit()
        except Exception: pass
        try: th.wait(5000)
        except Exception: pass
        try: th.deleteLater()
        except Exception: pass
        try:
            if self._worker:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
        self._thr = None
        try: metrics().read_stop()
        except Exception: pass

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

        try:
            size_mb = os.path.getsize(path) / (1024 * 1024.0) if os.path.exists(path) else 0.0
        except Exception:
            size_mb = 0.0
        try:
            metrics().file_open(
                name=os.path.basename(path),
                is_async=int(self._open_async),
                fast_open=int(self._fast_open),
                smart_prev=int(self._smart_preview),
                preview_s=self._preview_s,
                big_thr_mb=int(self._bigfile_threshold_mb),
                stream_decim=int(self._stream_decim),
                resample_hz=int(self._resample_hz),
                eeg_only=int(self._eeg_only),
                eog=int(self._incl_eog),
                emg=int(self._incl_emg),
                stim=int(self._incl_stim),
                turbo_gdf=int(self._turbo_gdf),
                size_mb=int(size_mb),
            )
        except Exception:
            pass

        if self._open_async:
            self._start_open_worker(path)
            if self._status:
                self._status.setText("Opening… (background)")
        else:

            # ... juste avant self._open_async ?
            try:
                from core.metrics_logger import metrics
                metrics().ttfp()  # démarre le chrono TTFP ici (clic "Open EEG…")
            except Exception:
                pass

            self._open_sync(path)

    def _open_sync(self, path: str):
        cfg = self.export_config()
        worker = _EEGOpenWorker(path, cfg)
        worker.ready.connect(self._on_open_ready)
        worker.run()

    def _start_open_worker(self, path: str):
        self._stop_open_worker()
        cfg = self.export_config()
        self._thr_open = QThread(parent=None)
        self._thr_open.setObjectName(f"{self.name}:open")
        self._worker_open = _EEGOpenWorker(path, cfg)
        self._worker_open.moveToThread(self._thr_open)

        self._thr_open.started.connect(self._worker_open.run)
        self._worker_open.ready.connect(self._on_open_ready)
        self._worker_open.ready.connect(lambda *_: self._thr_open.quit())
        self._thr_open.finished.connect(self._worker_open.deleteLater)
        self._thr_open.finished.connect(self._thr_open.deleteLater)

        self._thr_open.start()

    def _stop_open_worker(self):
        th = self._thr_open
        if th is None:
            return
        try: th.requestInterruption()
        except Exception: pass
        try: th.quit()
        except Exception: pass
        try: th.wait(3000)
        except Exception: pass
        self._thr_open = None
        self._worker_open = None

    def _on_open_ready(self, raw, msg: str):
        if self._status:
            self._status.setText(msg)

        try:
            base = None
            if isinstance(raw, object) and hasattr(raw, "filenames"):
                fn = getattr(raw, "filenames", [None])
                base = os.path.basename(fn[0]) if isinstance(fn, (list, tuple)) and fn and fn[0] else None
            elif isinstance(self._path, str):
                base = os.path.basename(self._path)
            if raw is None:
                metrics().file_error(name=base or "", msg=str(msg))
            else:
                n_ch = len(getattr(raw, "ch_names", []) or [])
                fs = float(getattr(raw, "info", {}).get("sfreq", 0.0)) if hasattr(raw, "info") else 0.0
                n_samp = int(getattr(raw, "n_times", 0))
                preload = getattr(raw, "preload", None)
                metrics().file_ready(name=base or "", n_ch=n_ch, fs=fs, n_samples=n_samp, preload=preload)
        except Exception:
            pass

        if raw is None:
            self._raw = None
            return

        self._raw = raw
        self._path = getattr(raw, "filenames", [None])[0] if hasattr(raw, "filenames") else None
        self._names = list(raw.ch_names)
        self._sf = float(raw.info["sfreq"])
        self._n_samp = int(raw.n_times)

        self.outputs["raw"].on_next(self._raw)
        self._start_stream_worker()

    def _start_stream_worker(self):
        self._stop_worker()
        if self._raw is None:
            return
        try:
            metrics().read_start(
                units=self._units,
                chunk_s=float(self._chunk_s),
                overlap_s=float(self._overlap_s),
                loop=int(self._loop),
                stream_decim=int(self._stream_decim),
                emit_ann=int(self._emit_annotations),
            )
        except Exception:
            pass

        self._thr = QThread(parent=None)
        self._thr.setObjectName(f"{self.name}:reader")
        self._worker = _EEGReadWorker(
            self._raw,
            units=self._units,
            chunk_s=self._chunk_s,
            overlap_s=self._overlap_s,
            loop=self._loop,
            emit_annotations=self._emit_annotations,
            stream_decim=self._stream_decim,
        )
        self._worker.moveToThread(self._thr)

        self._thr.started.connect(self._worker.run)
        self._worker.segReady.connect(lambda arr: self.outputs["segment"].on_next(arr))
        self._worker.eventReady.connect(self._on_event)
        self._worker.metaReset.connect(self._on_meta_reset)

        self._worker.finished.connect(self._thr.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thr.finished.connect(self._thr.deleteLater)

        
        
        from core.metrics_logger import is_active, metrics

        # ... juste avant self._thr.start():
        try:
            if is_active():
                metrics().start_ttfp()  # démarre la mesure TTFP au début du streaming
        except Exception:
            pass

        self._thr.start()

    def _on_event(self, ev):
        try:
            n = len(ev.get("items", [])) if isinstance(ev, dict) else 0
            metrics().events(n=n)
        except Exception:
            pass
        try:
            self.outputs["event"].on_next(ev)
        except Exception:
            pass

    def _on_meta_reset(self, info, ch_names, sfreq):
        self._names = list(ch_names or [])
        self._sf = float(sfreq or 0.0)
        self._n_samp = int(info.get("n_samples", 0)) if isinstance(info, dict) else 0
        info2 = dict(info or {}); info2["units"] = self._units
        self.outputs["info"].on_next(info2)
        self.outputs["ch_names"].on_next(list(self._names))
        self.outputs["sfreq"].on_next(float(self._sf) if self._sf else None)
        try:
            metrics().meta_reset(n_ch=len(self._names), fs=self._sf, n_samples=self._n_samp, units=self._units)
        except Exception:
            pass

    # ---------- Infos fichier ----------
    def _show_file_info(self):
        raw = self._raw
        path = self._path
        if raw is None:
            if self._status:
                self._status.setText("Aucun Raw chargé")
            return

        info_dict, txt_summary, txt_channels, txt_ann, txt_proj, txt_mont = self._collect_file_info(raw, path)

        dlg = QDialog(getattr(self, "_widget", None))
        dlg.setWindowTitle("Informations du fichier")
        lay = QVBoxLayout(dlg)

        tabs = QTabWidget(dlg)

        def _mk_tab(text, title):
            te = QTextEdit(); te.setReadOnly(True)
            te.setFontFamily("Consolas")
            te.setText(text)
            tabs.addTab(te, title)

        _mk_tab(txt_summary, "Résumé")
        _mk_tab(txt_channels, "Canaux")
        _mk_tab(txt_ann,      "Marqueurs/Labels")
        _mk_tab(txt_proj,     "Projecteurs")
        _mk_tab(txt_mont,     "Formes & dtypes / Montage")
        _mk_tab(_dumps_json(info_dict), "JSON")

        lay.addWidget(tabs)

        row = QHBoxLayout()
        btn_save_txt = QPushButton("Exporter TXT…"); btn_save_json = QPushButton("Exporter JSON…")
        row.addWidget(btn_save_txt); row.addWidget(btn_save_json)
        row.addStretch(1)
        lay.addLayout(row)

        def _save_txt():
            fn, _ = QFileDialog.getSaveFileName(dlg, "Exporter TXT", "file_info.txt", "Text (*.txt)")
            if fn:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(txt_summary+"\n\n"+txt_channels+"\n\n"+txt_ann+"\n\n"+txt_proj+"\n\n"+txt_mont)

        def _save_json():
            fn, _ = QFileDialog.getSaveFileName(dlg, "Exporter JSON", "file_info.json", "JSON (*.json)")
            if fn:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(_dumps_json(info_dict))

        btn_save_txt.clicked.connect(_save_txt)
        btn_save_json.clicked.connect(_save_json)

        dlg.resize(900, 650)
        dlg.exec_()

    def _collect_file_info(self, raw, path):
        file_list_raw = getattr(raw, "filenames", None)
        if file_list_raw:
            try:
                file_list = [os.fspath(p) if hasattr(os, "fspath") else str(p) for p in list(file_list_raw)]
            except Exception:
                file_list = [str(p) for p in list(file_list_raw)]
        elif path:
            try:
                file_list = [os.fspath(path)]
            except Exception:
                file_list = [str(path)]
        else:
            file_list = []

        try:
            dur = raw.n_times / raw.info['sfreq']
        except Exception:
            dur = float('nan')
        meas_date = raw.info.get("meas_date", None)
        meas_date_str = str(meas_date) if meas_date else "—"
        proj_list = raw.info.get("projs", []) or []
        line_freq = raw.info.get("line_freq", None)
        hp = raw.info.get("highpass", None)
        lp = raw.info.get("lowpass", None)
        bads = list(raw.info.get("bads", []) or [])

        summary = {
            "file_paths": file_list,
            "format": type(raw).__name__,
            "n_channels": len(raw.ch_names),
            "sfreq_Hz": float(raw.info["sfreq"]),
            "n_times": int(raw.n_times),
            "duration_s": float(dur) if dur == dur else None,
            "preload": bool(getattr(raw, "preload", False)),
            "meas_date": meas_date_str,
            "line_freq_Hz": line_freq,
            "highpass_Hz": hp,
            "lowpass_Hz": lp,
            "bads": bads,
        }

        uniq_types = raw.get_channel_types(unique=True)
        ch_by_type = {}

        def _pick(t):
            try:
                kwargs = dict(eeg=False, meg=False, eog=False, ecg=False, emg=False, misc=False, stim=False,
                              seeg=False, ecog=False, dbs=False, fnirs=False, resp=False)
                if t in kwargs:
                    kwargs[t] = True
                elif t == "meg":
                    kwargs["meg"] = True
                else:
                    kwargs[t] = True
                idx = mne.pick_types(raw.info, **kwargs)
                return [raw.ch_names[i] for i in idx]
            except Exception:
                return [n for n, tt in zip(raw.ch_names, raw.get_channel_types()) if tt == t]

        for t in uniq_types:
            ch_by_type[t] = _pick(t)

        channels = {
            "types": uniq_types,
            "counts": {t: len(ch_by_type.get(t, [])) for t in uniq_types},
            "by_type": ch_by_type,
        }

        ann = raw.annotations
        ann_list = []
        if ann is not None and len(ann) > 0:
            for on, duri, desc in zip(ann.onset, ann.duration, ann.description):
                ann_list.append({"onset_s": float(on), "duration_s": float(duri), "desc": str(desc)})
        try:
            events, ev_map = mne.events_from_annotations(raw, verbose="ERROR")
            events_info = {"n_events": int(len(events)), "codes": {k: int(v) for k, v in (ev_map or {}).items()}}
        except Exception:
            events_info = {"n_events": 0, "codes": {}}

        markers = {
            "n_annotations": len(ann) if ann is not None else 0,
            "items": ann_list[:200],
            "events_from_annotations": events_info,
        }

        projs = [{"kind": getattr(p, "kind", None), "desc": getattr(p, "desc", None), "active": bool(getattr(p, "active", False))}
                 for p in proj_list]
        projections = {"count": len(proj_list), "items": projs}

        # positions
        has_pos = False
        n_pos = 0
        try:
            for ch in raw.info.get("chs", []):
                loc = ch.get("loc", None)
                if loc is not None and np.any(np.isfinite(loc[:3])) and not np.allclose(loc[:3], 0.0):
                    has_pos = True; n_pos += 1
        except Exception:
            pass
        montage_info = {
            "has_positions": has_pos,
            "n_channels_with_pos": n_pos,
        }

        info_dict = {
            "summary": summary,
            "channels": channels,
            "markers": markers,
            "projections": projections,
            "montage": montage_info,
        }

        def _fmt(d): return _dumps_json(d)
        txt_summary = _fmt(summary)
        txt_channels = _fmt(channels)
        txt_ann = _fmt(markers)
        txt_proj = _fmt(projections)
        txt_mont = _fmt(montage_info)

        return info_dict, txt_summary, txt_channels, txt_ann, txt_proj, txt_mont

    def on_remove(self):
        self._stop_open_worker()
        self._stop_worker()
        try:
            self.outputs["segment"].on_next(None)
            self.outputs["raw"].on_next(None)
        except Exception:
            pass
        self._raw = None
        self._names = []
        self._sf = 0.0
        self._n_samp = 0
        try:
            metrics().file_closed()
        except Exception:
            pass

    
