# plugins/eeg_mat_reader.py
# -*- coding: utf-8 -*-
"""
EEGMatReader — lecteur .mat (BBCI/BCI Competition)
Sorties:
  - segment  : np.ndarray float32 shape (n_ch, n_samples)
  - ch_names : list[str] (émis au reset)
  - sfreq    : float      (émis au reset)
  - info     : dict {path, n_channels, sfreq, n_samples, style, units, reset, mode}

Fonctionne avec:
  - BBCI Toolbox style: cnt (continu), nfo.fs, nfo.clab, mrk (optionnel)
  - BCI Comp (époques): X (trials×samples×channels) ou permuté

Dépendances:
  pip install scipy h5py numpy
"""

import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QComboBox, QDoubleSpinBox, QSpinBox, QCheckBox, QLayout, QSizePolicy, QStyle
)
from PyQt5.QtCore import QTimer

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# -------- .mat loaders --------
try:
    from scipy.io import loadmat as _scipy_loadmat
except Exception:
    _scipy_loadmat = None

try:
    import h5py as _h5py
except Exception:
    _h5py = None


def _safe_to_list(obj) -> List[str]:
    """Convertit cellstr ou array de strings (scipy/h5py) -> list[str]."""
    if obj is None:
        return []
    if isinstance(obj, (list, tuple)):
        out = []
        for x in obj:
            if isinstance(x, bytes):
                out.append(x.decode("utf-8", "ignore"))
            elif isinstance(x, str):
                out.append(x)
            else:
                try:
                    s = str(x)
                    out.append(s)
                except Exception:
                    pass
        return out
    arr = np.asarray(obj)
    if arr.dtype.kind in ("U", "S", "O"):
        try:
            return [str(x if not isinstance(x, bytes) else x.decode("utf-8", "ignore")) for x in arr.ravel().tolist()]
        except Exception:
            pass
    try:
        return [str(obj)]
    except Exception:
        return []


def _try_load_scipy(path: str) -> Optional[Dict[str, Any]]:
    if _scipy_loadmat is None:
        return None
    try:
        d = _scipy_loadmat(path, squeeze_me=True, struct_as_record=False)
        # remove meta keys
        return {k: v for k, v in d.items() if not k.startswith("__")}
    except NotImplementedError:
        # v7.3 HDF5 -> handled by h5py
        return None
    except Exception:
        return None


def _try_load_h5(path: str) -> Optional[Dict[str, Any]]:
    if _h5py is None:
        return None
    try:
        out: Dict[str, Any] = {}
        with _h5py.File(path, "r") as h5:
            def get(k):
                if k not in h5:
                    return None
                obj = h5[k]
                if isinstance(obj, _h5py.Dataset):
                    v = obj[()]
                    return np.array(v)
                elif isinstance(obj, _h5py.Group):
                    return obj
                return None
            # lecture clés haut niveau utiles
            for key in ("X", "cnt", "nfo", "mrk", "fs", "Fs", "srate", "channels", "chanlocs"):
                if key in h5:
                    out[key] = h5[key]
            # fallback: lister toutes les datasets top-level
            for k in list(h5.keys()):
                if k not in out:
                    out[k] = h5[k]
        return out
    except Exception:
        return None


def _h5_read_nfo(h5_nfo) -> Tuple[Optional[float], List[str]]:
    """Extrait fs + clab depuis group nfo (h5py)."""
    fs = None
    clab = []
    if not isinstance(h5_nfo, _h5py.Group):
        return fs, clab
    # fs
    for key in ("fs", "Fs", "srate"):
        if key in h5_nfo:
            try:
                v = h5_nfo[key][()]
                fs = float(np.array(v).squeeze())
                break
            except Exception:
                pass
    # clab
    if "clab" in h5_nfo:
        node = h5_nfo["clab"]
        try:
            if isinstance(node, _h5py.Dataset):
                v = node[()]
                clab = _safe_to_list(v)
            elif isinstance(node, _h5py.Group):
                # cell array stockée comme objets
                tmp = []
                for k in node.keys():
                    tmp.extend(_safe_to_list(node[k][()]))
                clab = tmp
        except Exception:
            pass
    return fs, clab


def _auto_channels(n: int) -> List[str]:
    return [f"Ch{i+1}" for i in range(int(max(0, n)))]


class EEGMatReader(BasePlugin):
    name = "EEGMatReader"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True

    # ---------- lifecycle ----------
    def setup(self):
        self.outputs["segment"]  = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"]    = BehaviorSubject(None)
        self.outputs["info"]     = BehaviorSubject(None)

        # Etat fichier
        self._path: Optional[str] = None
        self._style: Optional[str] = None  # "bbci" | "trials" | "unknown"
        self._units = "V"   # on suppose Volts par défaut (nombreux .mat BBCI: µV -> tu peux ajouter une case à cocher)
        self._sf = 0.0
        self._ch_names: List[str] = []
        self._n_samples = 0

        # Données
        self._cnt: Optional[np.ndarray] = None          # (n_samples, n_ch) en CONTINU
        self._trials: Optional[np.ndarray] = None       # (n_trials, n_samples, n_ch)
        self._labels: Optional[np.ndarray] = None       # (n_trials,) ou (n_trials, n_classes)

        # UI et streaming
        self._mode = "Trials"         # "Trials" | "Continuous"
        self._chunk_s = 1.0
        self._overlap_s = 0.0
        self._auto_play = True
        self._loop = False

        self._timer = QTimer(); self._timer.timeout.connect(self._tick)
        self._idx = 0          # pour Trials: index trial ; pour Continu: index échantillon
        self._seg_len = 0
        self._hop = 0

        self.widget = self.build_widget()

    def execute(self, inputs=None):
        return {}  # source

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root = QVBoxLayout(w); root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # Ligne open
        r0 = QHBoxLayout()
        btn_open = UiKit.make_btn("Open .mat…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_open.clicked.connect(self._on_open)
        r0.addWidget(btn_open)
        self._lbl_status = QLabel("No file"); r0.addWidget(self._lbl_status, 1)
        root.addLayout(r0)

        # Section Mode & streaming
        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Mode:"))
        self._cmb_mode = QComboBox(); self._cmb_mode.addItems(["Trials","Continuous"])
        self._cmb_mode.currentTextChanged.connect(lambda s: self._on_mode_changed(s))
        r1.addWidget(self._cmb_mode)
        r1.addSpacing(12)
        self._chk_autoplay = QCheckBox("Autoplay"); self._chk_autoplay.setChecked(self._auto_play)
        self._chk_autoplay.stateChanged.connect(lambda s: setattr(self,"_auto_play", bool(s)))
        r1.addWidget(self._chk_autoplay)
        self._chk_loop = QCheckBox("Loop"); self._chk_loop.setChecked(self._loop)
        self._chk_loop.stateChanged.connect(lambda s: setattr(self,"_loop", bool(s)))
        r1.addWidget(self._chk_loop)
        r1.addStretch(1)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("chunk (s):"))
        self._sp_chunk = QDoubleSpinBox(); self._sp_chunk.setRange(0.05, 30.0); self._sp_chunk.setSingleStep(0.05); self._sp_chunk.setValue(self._chunk_s)
        self._sp_chunk.valueChanged.connect(lambda x: setattr(self,"_chunk_s", float(x))); r2.addWidget(self._sp_chunk)
        r2.addWidget(QLabel("overlap (s):"))
        self._sp_ov = QDoubleSpinBox(); self._sp_ov.setRange(0.0, 29.9); self._sp_ov.setSingleStep(0.05); self._sp_ov.setValue(self._overlap_s)
        self._sp_ov.valueChanged.connect(lambda x: setattr(self,"_overlap_s", float(x))); r2.addWidget(self._sp_ov)
        r2.addStretch(1)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        btn_start = UiKit.make_btn("Start", role="success", icon_sp=QStyle.SP_MediaPlay)
        btn_stop  = UiKit.make_btn("Stop",  role="danger",  icon_sp=QStyle.SP_MediaStop)
        btn_start.clicked.connect(self._start)
        btn_stop.clicked.connect(self._stop)
        r3.addWidget(btn_start); r3.addWidget(btn_stop); r3.addStretch(1)
        v.addLayout(r3)

        root.addWidget(CollapsibleSection("Paramètres lecture", panel, collapsed=True))
        w.destroyed.connect(lambda *a: self._timer.stop())
        return w

    # ---------- OPEN ----------
    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(None, "Open EEG .mat", os.getcwd(), "MAT files (*.mat);;All files (*)")
        if not path:
            return
        ok, msg = self._load_mat(path)
        self._lbl_status.setText(msg)
        if ok and self._auto_play:
            self._start()

    def _on_mode_changed(self, mode: str):
        self._mode = mode or "Trials"
        # rien d'autre; appliqué au prochain Start

    # ---------- LOAD ----------
    def _load_mat(self, path: str) -> Tuple[bool,str]:
        self._timer.stop()
        self._path = None; self._style = None; self._sf = 0.0; self._ch_names = []
        self._cnt = None; self._trials = None; self._labels = None; self._idx = 0

        d = _try_load_scipy(path)
        if d is None:
            d = _try_load_h5(path)
        if d is None:
            return False, "Load error: scipy/h5py indisponible ou fichier illisible"

        # --- BBCI style ?
        cnt = None; nfo = None
        if "cnt" in d:
            try:
                if _h5py and isinstance(d["cnt"], _h5py.Dataset):
                    cnt = np.array(d["cnt"][()])
                else:
                    cnt = np.array(d["cnt"])
            except Exception:
                cnt = None
            if "nfo" in d:
                nfo = d["nfo"]

        if cnt is not None:
            # cnt: (n_samples, n_ch) ou (n_ch, n_samples)
            arr = np.array(cnt)
            if arr.ndim == 1: arr = arr[:, None]
            if arr.shape[0] < arr.shape[1]:  # on préfère (n_samples, n_ch)
                if arr.shape[1] > 8 and arr.shape[1] > arr.shape[0]:
                    arr = arr  # déjà (samples, ch)
                else:
                    # heuristique inverse
                    pass
            else:
                # si (n_ch, n_samples) -> transpose
                if arr.shape[0] <= 512 and arr.shape[1] >= arr.shape[0]:
                    arr = arr.T
            sf = None; clab = []
            if nfo is not None:
                if _h5py and isinstance(nfo, _h5py.Group):
                    sf, clab = _h5_read_nfo(nfo)
                else:
                    # scipy struct
                    try:
                        sf = float(np.array(getattr(nfo, "fs", None)).squeeze())
                    except Exception:
                        for k in ("Fs","srate","SF","sf"):
                            try:
                                sf = float(np.array(getattr(nfo, k, None)).squeeze()); break
                            except Exception:
                                pass
                    try:
                        clab = _safe_to_list(getattr(nfo, "clab", []))
                    except Exception:
                        pass
            if not sf:
                # essais fallback haut-niveau
                for k in ("fs","Fs","srate"):
                    if k in d:
                        try:
                            node = d[k]
                            sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze())
                            break
                        except Exception:
                            pass
            if not clab or len(clab) != arr.shape[1]:
                clab = _auto_channels(arr.shape[1])
            self._cnt = np.asarray(arr, dtype=np.float32, order="C")
            self._sf = float(sf or 250.0)
            self._ch_names = list(clab)
            self._n_samples = int(self._cnt.shape[0])
            self._style = "bbci"
            self._emit_meta(path, reset=True, mode="Continuous")
            return True, f"Loaded BBCI cnt | {self._cnt.shape[1]} ch @ {self._sf:.2f} Hz, {self._cnt.shape[0]} samples"

        # --- Trials style ?
        X = None
        for key in ("X", "x", "data", "signals"):
            if key in d:
                try:
                    node = d[key]
                    X = node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node
                    X = np.array(X)
                    break
                except Exception:
                    pass
        if X is None:
            return False, "Format inconnu (.mat) — ni 'cnt' (continu) ni 'X' (trials) trouvés"

        # TROUVER dims (trials, samples, channels)
        arr = np.array(X)
        if arr.ndim == 2:
            # (samples, channels) -> on le traite en 'continuous'
            if arr.shape[0] >= arr.shape[1]:
                self._cnt = arr.astype(np.float32, copy=False)
            else:
                self._cnt = arr.T.astype(np.float32, copy=False)
            # meta
            sf = None
            for k in ("fs","Fs","srate"):
                if k in d:
                    try:
                        node = d[k]
                        sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze())
                        break
                    except Exception:
                        pass
            self._sf = float(sf or 250.0)
            self._ch_names = _auto_channels(self._cnt.shape[1])
            self._style = "trials-2d"
            self._n_samples = int(self._cnt.shape[0])
            self._emit_meta(path, reset=True, mode="Continuous")
            return True, f"Loaded 2D data as continuous | {self._cnt.shape[1]} ch @ {self._sf:.2f} Hz"

        # 3D -> réordonner en (trials, samples, channels)
        t, s, c = None, None, None
        shape = tuple(arr.shape)
        if len(shape) == 3:
            # heuristique: l'axe 'channels' est celui dans [8..512]
            candidates = [i for i, n in enumerate(shape) if 1 < n <= 512]
            if candidates:
                ch_axis = candidates[-1]
            else:
                ch_axis = 2  # fallback
            # l'axe 'samples' est celui > 10 et souvent le plus grand
            sizes = list(shape)
            smp_axis = max(range(3), key=lambda i: sizes[i])
            # trials = le troisième axe restant
            axes = [0, 1, 2]; axes.remove(ch_axis); axes.remove(smp_axis)
            tr_axis = axes[0]

            arr = np.moveaxis(arr, [tr_axis, smp_axis, ch_axis], [0, 1, 2])  # -> (trials, samples, channels)
            # meta
            sf = None
            for k in ("fs","Fs","srate"):
                if k in d:
                    try:
                        node = d[k]
                        sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze())
                        break
                    except Exception:
                        pass
            self._sf = float(sf or 250.0)
            # ch_names
            ch_names = None
            for k in ("chanlocs","channels","clab","ch_names"):
                if k in d:
                    try:
                        node = d[k]
                        if _h5py and isinstance(node, (_h5py.Dataset, _h5py.Group)):
                            try:
                                val = node[()] if isinstance(node, _h5py.Dataset) else node
                            except Exception:
                                val = None
                            ch_names = _safe_to_list(val)
                        else:
                            ch_names = _safe_to_list(node)
                        break
                    except Exception:
                        pass
            if not ch_names or len(ch_names) != arr.shape[2]:
                ch_names = _auto_channels(arr.shape[2])

            self._trials = arr.astype(np.float32, copy=False)
            self._ch_names = list(ch_names)
            self._n_samples = int(self._trials.shape[1])
            self._style = "trials-3d"

            # labels si présents
            y = None
            for k in ("y","labels","Y"):
                if k in d:
                    try:
                        node = d[k]
                        y = node[()] if (_h5py and isinstance(node, _h5py.Dataset)) else node
                        y = np.array(y).squeeze()
                        break
                    except Exception:
                        pass
            if y is not None:
                self._labels = y

            self._emit_meta(path, reset=True, mode="Trials")
            return True, f"Loaded Trials | {self._trials.shape[0]} trials × {self._trials.shape[1]} samples × {self._trials.shape[2]} ch @ {self._sf:.2f} Hz"

        return False, f"Forme inconnue: {shape}"

    def _emit_meta(self, path: str, reset: bool, mode: str):
        # ch_names + sfreq en premier (reset)
        if self._sf > 0:
            self.outputs["sfreq"].on_next(float(self._sf))
        if self._ch_names:
            self.outputs["ch_names"].on_next(list(self._ch_names))
        info = {
            "path": path, "n_channels": len(self._ch_names), "sfreq": float(self._sf or 0.0),
            "n_samples": int(self._n_samples), "style": self._style, "units": self._units,
            "mode": mode, "reset": bool(reset)
        }
        self.outputs["info"].on_next(info)

    # ---------- START / STOP ----------
    def _start(self):
        if self._sf <= 0 or (self._cnt is None and self._trials is None):
            self._lbl_status.setText("No data loaded"); return

        self._idx = 0
        if self._mode == "Continuous":
            # fenêtre = chunk_s, hop = chunk - overlap
            sf = float(self._sf)
            seg_len = max(1, int(round(self._chunk_s * sf)))
            hop = max(1, int(round((self._chunk_s - self._overlap_s) * sf)))
            self._seg_len = seg_len; self._hop = hop
        else:
            self._seg_len = 0; self._hop = 0

        self._timer.stop()
        # cadence timer: ~ chunk (s) ou 50 ms
        if self._mode == "Continuous":
            step = max(20, int(1000.0 * max(0.02, self._chunk_s * 0.9)))
        else:
            step = 100  # défilement essai par essai
        self._timer.start(step)
        self._lbl_status.setText(f"Playing ({self._mode})")

    def _stop(self):
        self._timer.stop()
        self.outputs["segment"].on_next(None)
        self._lbl_status.setText("Stopped")

    # ---------- TICK ----------
    def _tick(self):
        if self._mode == "Continuous":
            self._tick_continuous()
        else:
            self._tick_trials()

    def _tick_continuous(self):
        if self._cnt is None or self._sf <= 0:
            return
        n = self._cnt.shape[0]; nch = self._cnt.shape[1]
        L = int(self._seg_len or max(1, int(round(self._chunk_s * self._sf))))
        H = int(self._hop or max(1, int(round((self._chunk_s - self._overlap_s) * self._sf))))
        if self._idx + L > n:
            if self._loop:
                self._idx = 0
            else:
                self._stop(); return
        seg = self._cnt[self._idx:self._idx+L, :]     # (L, nch)
        self._idx += H
        self.outputs["segment"].on_next(np.asarray(seg.T, dtype=np.float32, order="C"))

    def _tick_trials(self):
        if self._trials is None or self._sf <= 0:
            return
        T = self._trials.shape[0]
        if self._idx >= T:
            if self._loop:
                self._idx = 0
            else:
                self._stop(); return
        seg = self._trials[self._idx, :, :]           # (samples, nch)
        self._idx += 1
        self.outputs["segment"].on_next(np.asarray(seg.T, dtype=np.float32, order="C"))

    # ---------- cleanup ----------
    def on_remove(self):
        try:
            self._timer.stop()
        except Exception:
            pass
