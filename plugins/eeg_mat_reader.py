# plugins/eeg_mat_reader.py
# -*- coding: utf-8 -*-
"""
EEGMatReader — lecteur .mat (BBCI / BCI Competition / génériques)
• Panneau "Paramètres lecture" repliable (QToolButton) intégré → compatible avec NodeItem actuel.
• Start/Stop robustes, stop auto à la destruction.
"""

import os, json, re
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QComboBox, QDoubleSpinBox, QCheckBox, QLayout, QSizePolicy, QStyle,
    QDialog, QTextEdit, QTabWidget, QToolButton
)
from PyQt5.QtCore import QTimer, Qt

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

# ---------- UiKit (optionnel) ----------
try:
    from core.ui_kit import UiKit  # style + boutons
except Exception:
    class UiKit:
        @staticmethod
        def apply_node_style(w: QWidget): pass
        @staticmethod
        def make_btn(text, role="primary", icon_sp=None):
            b = QPushButton(text)
            if icon_sp is not None:
                try: b.setIcon(b.style().standardIcon(icon_sp))
                except Exception: pass
            return b

# ---------- Collapsible local ----------
class _CollapsibleSection(QWidget):
    """Section repliable simple (pas de dépendance externe)."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.RightArrow)
        self._btn.setChecked(not collapsed)

        self._wrap = QWidget()
        self._wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0); self._wrap_l.setSpacing(6)
        self._content = content or QWidget(); self._wrap_l.addWidget(self._content)

        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(6)
        root.addWidget(self._btn); root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._on_toggled(self._btn.isChecked())

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        # remonte l’info de taille jusqu’au proxy du NodeItem pour éviter les artefacts
        w = self
        while w is not None:
            if w.layout(): w.layout().invalidate()
            w.adjustSize(); w.updateGeometry()
            w = w.parentWidget()

# -------- .mat loaders --------
try:
    from scipy.io import loadmat as _scipy_loadmat
except Exception:
    _scipy_loadmat = None

try:
    import h5py as _h5py
except Exception:
    _h5py = None

# ---------- JSON helpers ----------
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
    if isinstance(obj, (list, tuple)):
        return [_jsonify(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    return str(obj)

def _dumps_json(obj) -> str:
    return json.dumps(_jsonify(obj), indent=2, ensure_ascii=False)

def _safe_to_list(obj) -> List[str]:
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
                try: out.append(str(x))
                except Exception: pass
        return out
    arr = np.asarray(obj)
    if arr.dtype.kind in ("U", "S", "O"):
        try:
            return [str(x if not isinstance(x, bytes) else x.decode("utf-8", "ignore")) for x in arr.ravel().tolist()]
        except Exception:
            pass
    try: return [str(obj)]
    except Exception: return []

def _try_load_scipy(path: str) -> Optional[Dict[str, Any]]:
    if _scipy_loadmat is None:
        return None
    try:
        d = _scipy_loadmat(path, squeeze_me=True, struct_as_record=False)
        return {k: v for k, v in d.items() if not k.startswith("__")}
    except NotImplementedError:
        return None
    except Exception:
        return None

def _try_load_h5(path: str) -> Optional[Dict[str, Any]]:
    if _h5py is None:
        return None
    try:
        out: Dict[str, Any] = {}
        with _h5py.File(path, "r") as h5:
            for key in ("X", "x", "data", "signals", "cnt", "nfo", "mrk", "fs", "Fs", "srate",
                        "channels", "chanlocs", "trial", "y", "Y", "labels", "pos"):
                if key in h5:
                    out[key] = h5[key]
            for k in list(h5.keys()):
                if k not in out:
                    out[k] = h5[k]
        return out
    except Exception:
        return None

def _h5_read_nfo(h5_nfo) -> Tuple[Optional[float], List[str]]:
    fs = None; clab = []
    if not (_h5py and isinstance(h5_nfo, _h5py.Group)):
        return fs, clab
    for key in ("fs", "Fs", "srate"):
        if key in h5_nfo:
            try:
                v = h5_nfo[key][()]
                fs = float(np.array(v).squeeze()); break
            except Exception:
                pass
    if "clab" in h5_nfo:
        node = h5_nfo["clab"]
        try:
            if isinstance(node, _h5py.Dataset):
                v = node[()]; clab = _safe_to_list(v)
            elif isinstance(node, _h5py.Group):
                tmp = []
                for k in node.keys():
                    tmp.extend(_safe_to_list(node[k][()]))
                clab = tmp
        except Exception:
            pass
    return fs, clab

def _extract_bbci_mrk(mrk_node) -> Dict[str, Any]:
    out = {"n": 0, "pos": None, "y": None, "class_name": []}
    try:
        if _h5py and isinstance(mrk_node, _h5py.Group):
            pos = mrk_node.get("pos", None)
            y = mrk_node.get("y", None)
            cn = mrk_node.get("className", None)
            if isinstance(pos, _h5py.Dataset):
                out["pos"] = np.array(pos[()]).astype(np.int64).ravel()
            if isinstance(y, _h5py.Dataset):
                out["y"] = np.array(y[()]).squeeze()
            if cn is not None:
                out["class_name"] = _safe_to_list(cn[()] if isinstance(cn, _h5py.Dataset) else cn)
        else:
            pos = getattr(mrk_node, "pos", None) if hasattr(mrk_node, "pos") else (mrk_node.get("pos", None) if isinstance(mrk_node, dict) else None)
            y   = getattr(mrk_node, "y", None)   if hasattr(mrk_node, "y")   else (mrk_node.get("y", None)   if isinstance(mrk_node, dict) else None)
            cn  = getattr(mrk_node, "className", None) if hasattr(mrk_node, "className") else (mrk_node.get("className", None) if isinstance(mrk_node, dict) else None)
            if pos is not None: out["pos"] = np.array(pos).astype(np.int64).ravel()
            if y   is not None: out["y"]   = np.array(y).squeeze()
            if cn  is not None: out["class_name"] = _safe_to_list(cn)
        if out["pos"] is not None:
            out["n"] = int(out["pos"].size)
    except Exception:
        pass
    return out

def _auto_channels(n: int) -> List[str]:
    return [f"Ch{i+1}" for i in range(int(max(0, n)))]

class EEGMatReader(BasePlugin):
    help = { 'gotchas': ['Large files: prefer windowed output.', 'Check montage and units.'],
      'inputs': {},
      'outputs': { 'ch_names': 'List[str]',
                   'events': 'array/list',
                   'raw': 'mne.Raw',
                   'segment': '2D float [ch x samples]',
                   'sfreq': 'float (Hz)'},
      'parameters': [ { 'default': '',
                        'desc': 'EDF/BDF/GDF/FIF/... file to load',
                        'name': 'filepath',
                        'type': 'path'},
                      { 'default': None,
                        'desc': 'Channels selection',
                        'name': 'picks',
                        'type': 'list|None'},
                      { 'default': 1.0,
                        'desc': 'Window length for streaming output',
                        'name': 'segment_len',
                        'type': 'float',
                        'unit': 's'}],
      'summary': 'EEGMatReader — lecteur .mat (BBCI / BCI Competition / génériques)',
      'usage': 'Place at pipeline start; connect `raw` to MNE ops or `segment` to streaming ops.'}

    name = "EEGMatReader"
    category = "Input Nodes"
    start_hidden = True
    supports_collapse = True
    language = "Python"

    def setup(self):
        # Sorties
        self.outputs["segment"]  = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"]    = BehaviorSubject(None)
        self.outputs["info"]     = BehaviorSubject(None)

        # État
        self._path: Optional[str] = None
        self._style: Optional[str] = None  # "bbci" | "trials-2d" | "trials-3d" | "unknown"
        self._units = "V"
        self._sf = 0.0
        self._ch_names: List[str] = []
        self._n_samples = 0

        self._cnt: Optional[np.ndarray] = None
        self._trials: Optional[np.ndarray] = None
        self._labels: Optional[np.ndarray] = None
        self._trial_onsets: Optional[np.ndarray] = None
        self._mrk_info: Dict[str, Any] = {}

        # Lecture
        self._mode = "Trials"
        self._chunk_s = 1.0
        self._overlap_s = 0.0
        self._auto_play = True
        self._loop = False

        # Compteur de segments
        self._seg_total = 0

        # Timer robuste
        self._timer = QTimer()
        self._timer.setSingleShot(False)
        self._timer.timeout.connect(self._tick)
        self._timer.stop()

        self._idx = 0
        self._seg_len = 0
        self._hop = 0

        self.widget = self.build_widget()

    def execute(self, inputs=None):
        return {}

    def build_widget(self) -> QWidget:
        from PyQt5.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
            QDoubleSpinBox, QCheckBox, QSizePolicy, QLayout, QStyle, QFileDialog
        )
        from core.ui_kit import UiKit
        from core.collapsible import CollapsibleSection

        w = QWidget(); UiKit.apply_node_style(w)
        # le proxy de node utilise sizeHint → on fixe la hauteur et on la met à jour au toggle
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(8)

        # ----- panneau interne (TOUT est dedans) -----
        panel = QWidget()
        v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        # Ligne 0: Open / Infos / statut
        r0 = QHBoxLayout()
        btn_open = UiKit.make_btn("Open .mat…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_open.clicked.connect(self._on_open)
        r0.addWidget(btn_open)

        btn_info = QPushButton("Infos fichier…")
        btn_info.clicked.connect(self._show_file_info)
        r0.addWidget(btn_info)

        self._lbl_status = QLabel("No file")
        r0.addWidget(self._lbl_status, 1)
        v.addLayout(r0)

        # Ligne 1: Mode + options
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Mode:"))
        self._cmb_mode = QComboBox(); self._cmb_mode.addItems(["Trials","Continuous"])
        self._cmb_mode.currentTextChanged.connect(self._on_mode_changed)
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

        # Ligne 2: chunk/overlap
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("chunk (s):"))
        self._sp_chunk = QDoubleSpinBox(); self._sp_chunk.setRange(0.05, 30.0)
        self._sp_chunk.setSingleStep(0.05); self._sp_chunk.setValue(self._chunk_s)
        self._sp_chunk.valueChanged.connect(lambda x: setattr(self,"_chunk_s", float(x)))
        r2.addWidget(self._sp_chunk)

        r2.addWidget(QLabel("overlap (s):"))
        self._sp_ov = QDoubleSpinBox(); self._sp_ov.setRange(0.0, 29.9)
        self._sp_ov.setSingleStep(0.05); self._sp_ov.setValue(self._overlap_s)
        self._sp_ov.valueChanged.connect(lambda x: setattr(self,"_overlap_s", float(x)))
        r2.addWidget(self._sp_ov)
        r2.addStretch(1)
        v.addLayout(r2)

        # Ligne 3: Start/Stop
        r3 = QHBoxLayout()
        btn_start = UiKit.make_btn("Start", role="success", icon_sp=QStyle.SP_MediaPlay)
        btn_stop  = UiKit.make_btn("Stop",  role="danger",  icon_sp=QStyle.SP_MediaStop)
        btn_start.clicked.connect(self._start)
        btn_stop.clicked.connect(self._stop)
        r3.addWidget(btn_start); r3.addWidget(btn_stop); r3.addStretch(1)
        v.addLayout(r3)

        # ----- section pliable (fermée par défaut) -----
        coll = CollapsibleSection("Paramètres lecture", panel, collapsed=True)
        root.addWidget(coll)

        # Hauteur = taille “pliée” (barre d'en-tête de la section).
        # Et on resynchronise la hauteur quand on plie/déplie pour éviter tout clipping.
        def _sync_height(*_):
            w.layout().activate()
            w.setFixedHeight(root.sizeHint().height() + 2)
            w.updateGeometry()
        _sync_height()
        try:
            coll._btn.toggled.connect(_sync_height)   # bouton de l’en-tête du CollapsibleSection
        except Exception:
            pass

        # Arrêt sûr du timer si le widget est détruit
        w.destroyed.connect(lambda *a: (getattr(self, "_timer", None) is not None) and self._timer.stop())
        return w



    # ---------- UI Callbacks ----------
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

    # ---------- LOAD ----------
    def _load_mat(self, path: str) -> Tuple[bool,str]:
        # reset complet
        self._timer.stop()
        self._path = None; self._style = None; self._sf = 0.0; self._ch_names = []
        self._cnt = None; self._trials = None; self._labels = None; self._trial_onsets = None; self._mrk_info = {}
        self._idx = 0

        d = _try_load_scipy(path)
        if d is None: d = _try_load_h5(path)
        if d is None:
            return False, "Load error: scipy/h5py indisponible ou fichier illisible"

        # BBCI continu ? (cnt / nfo)
        cnt = None; nfo = None
        if "cnt" in d:
            try:
                if _h5py and isinstance(d["cnt"], _h5py.Dataset): cnt = np.array(d["cnt"][()])
                else: cnt = np.array(d["cnt"])
            except Exception:
                cnt = None
            if "nfo" in d: nfo = d["nfo"]

        if cnt is not None:
            arr = np.array(cnt)
            if arr.ndim == 1: arr = arr[:, None]
            n0, n1 = arr.shape
            if (n0 <= 512 and n1 >= n0) and (n1 > n0): arr = arr.T
            sf = None; clab = []
            if nfo is not None:
                if _h5py and isinstance(nfo, _h5py.Group):
                    sf, clab = _h5_read_nfo(nfo)
                else:
                    for k in ("fs","Fs","srate","SF","sf"):
                        try:
                            v = getattr(nfo, k, None)
                            if v is not None:
                                sf = float(np.array(v).squeeze()); break
                        except Exception:
                            pass
                    try:
                        clab = _safe_to_list(getattr(nfo, "clab", []))
                    except Exception:
                        pass
            if not sf:
                for k in ("fs","Fs","srate"):
                    if k in d:
                        try:
                            node = d[k]
                            sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze()); break
                        except Exception:
                            pass
            if not clab or len(clab) != arr.shape[1]:
                clab = _auto_channels(arr.shape[1])

            if "mrk" in d:
                try:
                    node = d["mrk"]
                    node = node if not (_h5py and isinstance(node, _h5py.Dataset)) else node[()]
                    self._mrk_info = _extract_bbci_mrk(node)
                except Exception:
                    self._mrk_info = {}

            self._cnt = np.asarray(arr, dtype=np.float32, order="C")
            self._sf = float(sf or 250.0)
            self._ch_names = list(clab)
            self._n_samples = int(self._cnt.shape[0])
            self._style = "bbci"
            self._emit_meta(path, reset=True, mode="Continuous")
            return True, f"Loaded BBCI cnt | {self._cnt.shape[1]} ch @ {self._sf:.2f} Hz, {self._cnt.shape[0]} samples"

        # Trials / X ?
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

        arr = np.array(X)
        # 2D -> continu
        if arr.ndim == 2:
            n0, n1 = arr.shape
            if n0 >= n1: self._cnt = arr.astype(np.float32, copy=False)
            else:        self._cnt = arr.T.astype(np.float32, copy=False)
            sf = None
            for k in ("fs","Fs","srate"):
                if k in d:
                    try:
                        node = d[k]
                        sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze()); break
                    except Exception:
                        pass
            self._sf = float(sf or 250.0)
            self._ch_names = _auto_channels(self._cnt.shape[1])
            self._style = "trials-2d"
            self._n_samples = int(self._cnt.shape[0])
            for k in ("trial","pos"):
                if k in d:
                    try:
                        node = d[k]; self._trial_onsets = np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).astype(np.int64).ravel(); break
                    except Exception:
                        pass
            for k in ("y","Y","labels"):
                if k in d and self._labels is None:
                    try:
                        node = d[k]; self._labels = np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze(); break
                    except Exception:
                        pass
            self._emit_meta(path, reset=True, mode="Continuous")
            return True, f"Loaded 2D data as continuous | {self._cnt.shape[1]} ch @ {self._sf:.2f} Hz"

        # 3D -> trials (T,S,C)
        if len(arr.shape) == 3:
            shape = tuple(arr.shape)
            candidates = [i for i, n in enumerate(shape) if 1 < n <= 512]
            ch_axis = candidates[-1] if candidates else 2
            sizes = list(shape)
            smp_axis = max(range(3), key=lambda i: sizes[i])
            axes = [0, 1, 2]; axes.remove(ch_axis); axes.remove(smp_axis)
            tr_axis = axes[0]

            arr = np.moveaxis(arr, [tr_axis, smp_axis, ch_axis], [0, 1, 2])  # (T, S, C)
            sf = None
            for k in ("fs","Fs","srate"):
                if k in d:
                    try:
                        node = d[k]; sf = float(np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze()); break
                    except Exception:
                        pass
            self._sf = float(sf or 250.0)
            ch_names = None
            for k in ("chanlocs","channels","clab","ch_names"):
                if k in d:
                    try:
                        node = d[k]
                        if _h5py and isinstance(node, (_h5py.Dataset, _h5py.Group)):
                            try: val = node[()] if isinstance(node, _h5py.Dataset) else node
                            except Exception: val = None
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

            for k in ("y","Y","labels"):
                if k in d:
                    try:
                        node = d[k]; self._labels = np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).squeeze(); break
                    except Exception:
                        pass
            for k in ("trial","pos"):
                if k in d:
                    try:
                        node = d[k]; self._trial_onsets = np.array(node[()] if (_h5py and isinstance(node,_h5py.Dataset)) else node).astype(np.int64).ravel(); break
                    except Exception:
                        pass

            self._emit_meta(path, reset=True, mode="Trials")
            return True, f"Loaded Trials | {self._trials.shape[0]} trials × {self._trials.shape[1]} samples × {self._trials.shape[2]} ch @ {self._sf:.2f} Hz"

        return False, f"Forme inconnue: {arr.shape}"

    def _emit_meta(self, path: str, reset: bool, mode: str):
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

    # ---------- START/STOP ----------
    def _start(self):
        if self._sf <= 0 or (self._cnt is None and self._trials is None):
            self._lbl_status.setText("No data loaded"); return

        self._idx = 0
        if self._mode == "Continuous":
            sf = float(self._sf)
            seg_len = max(1, int(round(max(0.01, self._chunk_s) * sf)))
            hop = int(round((self._chunk_s - self._overlap_s) * sf))
            if hop <= 0:
                hop = max(1, int(round(0.1 * seg_len)))  # éviter stall
            self._seg_len = seg_len; self._hop = hop
            n = int(self._cnt.shape[0]) if self._cnt is not None else 0
            if n <= seg_len:
                self._seg_total = 1 if n > 0 else 0
            else:
                self._seg_total = 1 + max(0, (n - seg_len) // hop)
        else:
            self._seg_len = 0; self._hop = 0
            self._seg_total = int(self._trials.shape[0]) if self._trials is not None else 0

        self._timer.stop()
        step = 100 if self._mode != "Continuous" else max(20, int(1000.0 * max(0.02, self._chunk_s * 0.9)))
        self._timer.start(step)
        self._lbl_status.setText(f"Playing ({self._mode})")

    def _stop(self):
        self._timer.stop()
        try:
            self.outputs["segment"].on_next(None)
        except Exception:
            pass
        self._lbl_status.setText("Stopped")

    def _tick(self):
        if self._mode == "Continuous":
            self._tick_continuous()
        else:
            self._tick_trials()

    def _tick_continuous(self):
        if self._cnt is None or self._sf <= 0:
            return
        n = self._cnt.shape[0]
        L = int(self._seg_len or max(1, int(round(max(0.01, self._chunk_s) * self._sf))))
        H = int(self._hop or max(1, int(round(max(0.01, self._chunk_s - self._overlap_s) * self._sf))))
        if self._idx + L > n:
            if self._loop:
                self._idx = 0
            else:
                self._stop(); return

        seg_idx = (self._idx // max(1, H)) + 1  # 1-based
        seg = self._cnt[self._idx:self._idx+L, :]

        self.outputs["segment"].on_next(np.asarray(seg.T, dtype=np.float32, order="C"))
        try:
            self.outputs["info"].on_next({
                "segment_index": int(seg_idx),
                "segment_total": int(self._seg_total),
                "mode": "Continuous"
            })
        except Exception:
            pass

        self._idx += H

    def _tick_trials(self):
        if self._trials is None or self._sf <= 0:
            return
        T = self._trials.shape[0]
        if self._idx >= T:
            if self._loop:
                self._idx = 0
            else:
                self._stop(); return

        seg_idx = self._idx + 1  # 1-based
        seg = self._trials[self._idx, :, :]

        self.outputs["segment"].on_next(np.asarray(seg.T, dtype=np.float32, order="C"))
        try:
            self.outputs["info"].on_next({
                "segment_index": int(seg_idx),
                "segment_total": int(T),
                "mode": "Trials"
            })
        except Exception:
            pass

        self._idx += 1

    # ---------- Infos fichier (onglets + export) ----------
    def _show_file_info(self):
        if not (self._cnt is not None or self._trials is not None):
            self._lbl_status.setText("Aucun .mat chargé"); return

        info_dict, tabs_texts = self._collect_file_info()

        dlg = QDialog(getattr(self, "widget", None))
        dlg.setWindowTitle("Informations du fichier (.mat)")
        lay = QVBoxLayout(dlg)
        tabs = QTabWidget(dlg)

        def _mk_tab(title, text):
            te = QTextEdit(); te.setReadOnly(True)
            te.setFontFamily("Consolas")
            te.setText(text)
            tabs.addTab(te, title)

        _mk_tab("Résumé",           tabs_texts["summary"])
        _mk_tab("Canaux",           tabs_texts["channels"])
        _mk_tab("Marqueurs/Labels", tabs_texts["markers"])
        _mk_tab("Formes & dtypes",  tabs_texts["shapes"])
        _mk_tab("Inférence EOG/ECG/EMG", tabs_texts["inference"])
        _mk_tab("JSON",             _dumps_json(info_dict))

        lay.addWidget(tabs)

        row = QHBoxLayout()
        btn_txt  = QPushButton("Exporter TXT…")
        btn_json = QPushButton("Exporter JSON…")
        row.addWidget(btn_txt); row.addWidget(btn_json); row.addStretch(1)
        lay.addLayout(row)

        def _save_txt():
            fn, _ = QFileDialog.getSaveFileName(dlg, "Exporter TXT", "mat_file_info.txt", "Text (*.txt)")
            if fn:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(tabs_texts["summary"]+"\n\n"+tabs_texts["channels"]+"\n\n"+tabs_texts["markers"]+"\n\n"+tabs_texts["shapes"]+"\n\n"+tabs_texts["inference"])
        def _save_json():
            fn, _ = QFileDialog.getSaveFileName(dlg, "Exporter JSON", "mat_file_info.json", "JSON (*.json)")
            if fn:
                with open(fn, "w", encoding="utf-8") as f:
                    f.write(_dumps_json(info_dict))

        btn_txt.clicked.connect(_save_txt)
        btn_json.clicked.connect(_save_json)

        dlg.resize(900, 650)
        dlg.exec_()

    def _collect_file_info(self):
        if self._cnt is not None:
            dur = float(self._cnt.shape[0] / max(1.0, self._sf))
        else:
            dur = float(self._trials.shape[1] / max(1.0, self._sf))

        summary = {
            "path": self._path,
            "style": self._style,
            "sfreq_Hz": float(self._sf),
            "units": self._units,
            "n_channels": len(self._ch_names),
            "duration_s": dur,
            "mode_ui": self._mode,
        }

        names = list(self._ch_names)
        up = [n.upper() for n in names]
        is_eog = [bool(re.search(r"\b(EOG|HEOG|VEOG|EYE)\b", u)) for u in up]
        is_ecg = [bool(re.search(r"\b(ECG|EKG|CARD|HEART)\b", u)) for u in up]
        is_emg = [bool(re.search(r"\b(EMG|MUSC)\b", u)) for u in up]
        ch_types = {
            "eeg": [n for n, e1, e2, e3 in zip(names, is_eog, is_ecg, is_emg) if not (e1 or e2 or e3)],
            "eog": [n for n, b in zip(names, is_eog) if b],
            "ecg": [n for n, b in zip(names, is_ecg) if b],
            "emg": [n for n, b in zip(names, is_emg) if b],
        }

        markers = {"bbci": None, "trial_onsets": None, "n_labels": None}
        if self._mrk_info:
            markers["bbci"] = {
                "n": int(self._mrk_info.get("n", 0)),
                "has_pos": self._mrk_info.get("pos") is not None,
                "has_y":   self._mrk_info.get("y")   is not None,
                "class_name": self._mrk_info.get("class_name", []),
            }
        if self._trial_onsets is not None:
            markers["trial_onsets"] = int(self._trial_onsets.size)
        if self._labels is not None:
            try:
                markers["n_labels"] = int(np.asarray(self._labels).shape[0])
            except Exception:
                markers["n_labels"] = None

        shapes = {}
        if self._cnt is not None:
            shapes["continuous"] = {"shape": list(self._cnt.shape), "dtype": str(self._cnt.dtype)}
        if self._trials is not None:
            shapes["trials"] = {"shape": list(self._trials.shape), "dtype": str(self._trials.dtype)}

        inference = {
            "eog_channels": ch_types["eog"],
            "ecg_channels": ch_types["ecg"],
            "emg_channels": ch_types["emg"],
            "hint_if_missing": "Si EOG/ECG absents: créer EOGv=Fp1-Fp2 et ECGv=Cz (ou moyenne EEG) avant SSP.",
        }

        info_dict = {
            "summary": summary,
            "channels": {"names": names, "by_inferred_type": ch_types},
            "markers": markers,
            "shapes": shapes,
            "inference": inference,
        }

        def _fmt(d): return _dumps_json(d)
        tabs_texts = {
            "summary":   _fmt(summary),
            "channels":  _fmt({"counts": {k: len(v) for k, v in ch_types.items()}, "by_type": ch_types}),
            "markers":   _fmt(markers),
            "shapes":    _fmt(shapes),
            "inference": _fmt(inference),
        }
        return info_dict, tabs_texts

    def on_remove(self):
        try:
            if getattr(self, "_timer", None) is not None:
                self._timer.stop()
        except Exception:
            pass
        try:
            self.outputs["segment"].on_next(None)
        except Exception:
            pass
