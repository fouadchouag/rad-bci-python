# plugins/eeg_saver.py
# -*- coding: utf-8 -*-
"""
EEGSaver — sauvegarde EEG (Raw MNE ou segment numpy) en plusieurs formats.
→ Section “Paramètres” pliable, fermée par défaut, sans espace gris au repli.
"""

from typing import Optional, List, Tuple
import os, time
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QComboBox, QCheckBox, QLineEdit, QDoubleSpinBox, QSizePolicy, QFrame, QLayout
)
from PyQt5.QtCore import QTimer, pyqtSignal
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

# ---------------------- CollapsibleSection robuste (anti "rectangle gris") ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parent.
    """
    collapsedChanged = pyqtSignal(bool)  # True si fermé

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._base_title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # unchecked => fermé au démarrage (on gère nous-mêmes l’état)
        self._btn.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding:6px 8px; font-weight:600;"
            " border:1px solid #ccc; border-radius:6px; background:#f7f7f7;"
            "}"
        )
        self._btn.toggled.connect(self._on_toggled)
        root.addWidget(self._btn)

        self._content = QWidget()
        self._content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 8, 10, 8)
        self._content_layout.setSpacing(6)
        self._content_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._apply_collapsed_state(True)  # fermé sans espace
        self._update_btn_text()

    def add_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def content_layout(self):
        return self._content_layout

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)  # checked => ouvert
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    def _on_toggled(self, checked: bool):
        collapsed = (not checked)
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    def _apply_collapsed_state(self, collapsed: bool):
        if collapsed:
            self._content.setMaximumHeight(0)
            self._content.setMinimumHeight(0)
            self._content.setVisible(False)
            self._line.setVisible(False)
        else:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            self._content.setMinimumHeight(0)
            self._line.setVisible(True)

    def _update_btn_text(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._base_title
        if base.startswith(("▼ ", "▶ ")):
            base = base[2:]
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry()
        self.updateGeometry()
        p = self.parentWidget()
        if p is not None:
            if p.layout():
                p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._delayed_adjust)

    def _delayed_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout():
                    w.layout().activate()
                w.adjustSize()
                w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()

# ---------------------- EEGSaver ----------------------
# MNE (optionnel)
try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

# SciPy pour .mat (optionnel)
try:
    from scipy.io import savemat as _savemat
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

# MNE export (optionnel)
_HAVE_EXPORT = False
if HAVE_MNE:
    try:
        from mne.export import export_raw as _mne_export_raw
        _HAVE_EXPORT = True
    except Exception:
        _HAVE_EXPORT = False


class EEGSaver(BasePlugin):
    help = {
        'summary': 'Save EEG data (MNE Raw or numpy segments) to disk in multiple formats.',
        'usage': 'Connect raw/segment data and set an output path via the UI. Supports snapshot save and continuous recording with auto-increment.',
        'inputs': {
            'raw': 'mne.io.Raw — continuous EEG object; saved directly to FIF/EDF/BDF/BrainVision',
            'segment': '2D float [channels x samples] — numpy array segments (accumulated during recording)',
            'ch_names': 'list[str] — channel names (used when saving numpy segments)',
            'sfreq': 'float — sampling frequency (Hz); used when saving numpy segments',
            'markers': 'dict or list — event markers (keys: t/time, label, dur, mode)',
        },
        'outputs': {
            'status': 'str — save status/error message',
            'saved_path': 'str — path of the last successfully saved file',
        },
        'parameters': [
            {'name': 'format', 'type': 'str', 'default': 'FIF', 'desc': 'Output format: FIF, BrainVision, EDF, BDF, CSV, NPZ, or MAT'},
            {'name': 'max_buffer_sec', 'type': 'float', 'default': 300.0, 'desc': 'Maximum recording buffer duration (seconds) before oldest data is dropped'},
            {'name': 'auto_increment', 'type': 'bool', 'default': True, 'desc': 'Auto-increment filename suffix (_001, _002, …) to avoid overwrites'},
        ],
        'gotchas': [
            'MNE is required for FIF/EDF/BDF/BrainVision formats; CSV/NPZ/MAT work without it.',
            'SciPy is required for MAT (Matlab) format.',
            'When saving numpy segments, sfreq and ch_names inputs must be connected or data will have dummy names.',
            'µV input checkbox: if checked, data is multiplied by 1e-6 before saving (converts µV to V for MNE).',
            'Markers are embedded as MNE Annotations for FIF/EDF formats, or saved as separate .markers.csv for CSV format.',
            'Recording buffer accumulates segment input only (not raw); raw is saved as-is on "Save now".',
        ],
    }

    name = "EEGSaver"
    category = "Output Nodes"
    language = "Python"

    def setup(self):
        # Entrées
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["sfreq"] = BehaviorSubject(None)
        self.inputs["markers"] = BehaviorSubject(None)

        # Sorties
        self.outputs["status"] = BehaviorSubject("")
        self.outputs["saved_path"] = BehaviorSubject("")

        # État courant
        self._raw = None
        self._seg = None
        self._names: List[str] = []
        self._sf: float = 0.0

        # Recording buffer
        self._recording = False
        self._buf: List[np.ndarray] = []
        self._buf_samples = 0
        self._max_sec = 300.0

        # Marqueurs
        self._mark_buf: List[Tuple[float, str, float, str]] = []  # (t, val, dur, mode)
        self._rec_t0: Optional[float] = None

        # UI état
        self._fmt = "FIF"
        self._units_uV = False
        self._with_time = True
        self._auto_inc = True
        self._ch_type = "eeg"

        # Cible fichier
        self._target = ""

        # Abonnement marqueurs
        try:
            self.inputs["markers"].subscribe(lambda v: self._on_markers(v))
        except Exception:
            pass

        self.widget = self.build_widget()

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._lbl_head = QLabel("EEGSaver — prêt")
        root.addWidget(self._lbl_head)

        # -------- Zone Paramètres pliable (fermée par défaut) --------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)
        # Recalcule la taille du node quand on ouvre/ferme
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Ligne Format + options
        row_fmt = QWidget()
        r1 = QHBoxLayout(row_fmt); r1.setContentsMargins(0, 0, 0, 0); r1.setSpacing(6)

        r1.addWidget(QLabel("Format:"))
        self._cmb_fmt = QComboBox()
        self._cmb_fmt.addItems(["FIF", "BrainVision", "EDF", "BDF", "CSV", "NPZ", "MAT"])
        self._cmb_fmt.currentTextChanged.connect(self._on_fmt)
        r1.addWidget(self._cmb_fmt)

        r1.addWidget(QLabel("Ch. type:"))
        self._cmb_type = QComboBox()
        self._cmb_type.addItems(["eeg", "eog", "ecg", "emg", "misc"])
        self._cmb_type.currentTextChanged.connect(lambda s: setattr(self, "_ch_type", s))
        r1.addWidget(self._cmb_type)

        self._chk_uV = QCheckBox("Input = µV")
        self._chk_uV.toggled.connect(lambda b: setattr(self, "_units_uV", bool(b)))
        r1.addWidget(self._chk_uV)

        self._chk_time = QCheckBox("CSV: colonne temps")
        self._chk_time.setChecked(True)
        self._chk_time.toggled.connect(lambda b: setattr(self, "_with_time", bool(b)))
        r1.addWidget(self._chk_time)

        self._sp_max = QDoubleSpinBox()
        self._sp_max.setRange(5.0, 3600.0)
        self._sp_max.setDecimals(0)
        self._sp_max.setValue(self._max_sec)
        self._sp_max.setSuffix(" s buffer")
        self._sp_max.valueChanged.connect(lambda v: setattr(self, "_max_sec", float(v)))
        r1.addWidget(self._sp_max)
        r1.addStretch(1)

        # Cible
        row_path = QWidget()
        r2 = QHBoxLayout(row_path); r2.setContentsMargins(0, 0, 0, 0); r2.setSpacing(6)
        self._le_path = QLineEdit()
        self._le_path.setPlaceholderText("Chemin de sauvegarde…")
        r2.addWidget(self._le_path, 1)
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self._choose_target)
        r2.addWidget(btn_browse)
        self._chk_inc = QCheckBox("Auto-incr.")
        self._chk_inc.setChecked(True)
        self._chk_inc.toggled.connect(lambda b: setattr(self, "_auto_inc", bool(b)))
        r2.addWidget(self._chk_inc)

        # Boutons actions
        row_btns = QWidget()
        r3 = QHBoxLayout(row_btns); r3.setContentsMargins(0, 0, 0, 0); r3.setSpacing(6)
        btn_save = QPushButton("Save now…")
        btn_save.clicked.connect(self._save_snapshot)
        r3.addWidget(btn_save)
        self._btn_rec = QPushButton("Start Rec")
        self._btn_rec.clicked.connect(self._toggle_rec)
        r3.addWidget(self._btn_rec)
        btn_clear = QPushButton("Clear buffer")
        btn_clear.clicked.connect(self._clear_buffer)
        r3.addWidget(btn_clear)
        r3.addStretch(1)

        # Injecter dans la section pliable
        sec.add_content_widget(row_fmt)
        sec.add_content_widget(row_path)
        sec.add_content_widget(row_btns)

        # Résumé & Status (toujours visibles)
        self._lbl_info = QLabel("Aucune donnée")
        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl_info)
        root.addWidget(self._lbl_status)

        # Contraintes pour supprimer tout résidu d’espace
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        return w

    # ---------- Reactive ----------
    def execute(self, *args, **kwargs):
        inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)

        def _v(x):
            try:
                return x.value
            except Exception:
                return x

        raw = _v(inps.get("raw"))
        seg = _v(inps.get("segment"))
        names = _v(inps.get("ch_names"))
        sf = _v(inps.get("sfreq"))

        changed = False

        if raw is None and seg is None:
            if self._raw is not None or self._seg is not None:
                self._raw = None; self._seg = None
                self._set_status("Aucune donnée")
            self._lbl_info.setText("Aucune donnée")
            return

        if raw is not None and raw is not self._raw:
            self._raw = raw; self._seg = None; changed = True
            try: self._sf = float(raw.info.get('sfreq', 0.0) or 0.0)
            except Exception: pass
            try: self._names = list(raw.ch_names)
            except Exception: pass

        if seg is not None and self._raw is None:
            arr = np.asarray(seg)
            if arr.ndim == 1: arr = arr.reshape(1, -1)
            self._seg = arr; changed = True
            try: self._sf = float(sf or self._sf or 0.0)
            except Exception: pass
            try:
                self._names = list(names or [f"Ch{i+1}" for i in range(arr.shape[0])])
            except Exception:
                pass

            # Enregistrement continu ? accumuler
            if self._recording and arr.size > 0:
                self._append_to_buffer(arr, self._sf)

        if changed:
            self._update_info_label()

    # ---------- Markers ----------
    def _on_markers(self, val):
        if val is None:
            return

        def _push(t, lab, dur=None, mode=None):
            self._mark_buf.append((float(t), str(lab), 0.0 if dur is None else float(dur), mode or "auto"))

        if isinstance(val, dict):
            _push(val.get("t", val.get("time", 0.0)), val.get("label", "MARK"),
                  val.get("dur", 0.0), val.get("mode"))
        elif isinstance(val, (tuple, list)) and val and isinstance(val[0], (tuple, list, dict)):
            for it in val:
                if isinstance(it, dict):
                    _push(it.get("t", it.get("time", 0.0)), it.get("label", "MARK"),
                          it.get("dur", 0.0), it.get("mode"))
                else:
                    t = it[0]; lab = it[1]
                    dur = it[2] if len(it) > 2 else 0.0
                    mode = it[3] if len(it) > 3 else "auto"
                    _push(t, lab, dur, mode)
        elif isinstance(val, (tuple, list)) and len(val) >= 2:
            _push(val[0], val[1], val[2] if len(val) > 2 else 0.0, val[3] if len(val) > 3 else "auto")
        else:
            return

        self._update_info_label()

    def _normalized_markers_for_save(self, fs: float):
        onsets, durations, labels = [], [], []
        for t, lab, dur, mode in list(self._mark_buf):
            m = mode or "auto"
            if m == "auto":
                if self._rec_t0 and t > 1e3:
                    m = "abs"
                elif fs > 0 and t > 10 * fs:
                    m = "sample"
                else:
                    m = "rel"
            if m == "abs":
                if self._rec_t0 is None:
                    continue
                onset = float(t - self._rec_t0)
            elif m == "sample":
                onset = float(t) / (fs if fs > 0 else 1.0)
            else:
                onset = float(t)
            if onset < 0:
                continue
            onsets.append(onset)
            durations.append(float(dur or 0.0))
            labels.append(str(lab))
        return onsets, durations, labels

    # ---------- UI slots ----------
    def _on_fmt(self, s: str):
        self._fmt = s or "FIF"
        self._chk_time.setEnabled(self._fmt == "CSV")

    def _choose_target(self):
        ext = {
            "FIF": "fif", "BrainVision": "vhdr", "EDF": "edf", "BDF": "bdf",
            "CSV": "csv", "NPZ": "npz", "MAT": "mat",
        }.get(self._fmt, "fif")
        path, _ = QFileDialog.getSaveFileName(None, "Choisir un fichier de sortie", os.getcwd(), f"*.{ext}")
        if path:
            if not path.lower().endswith(f".{ext}"):
                path = path + f".{ext}"
            self._le_path.setText(path)

    # ---------- Helpers ----------
    def _update_info_label(self):
        data, fs, names = self._current_data()
        n, T = data.shape
        dur = (T / fs) if fs > 0 else T
        mode = "Raw" if (self._raw is not None) else "Segment"
        mark = f" | markers: {len(self._mark_buf)}"
        rec = f" | REC: {self._buf_samples} samples ({self._buf_dur_str(fs)})" if self._recording else ""
        self._lbl_info.setText(f"{mode} — {n} ch × {T} samples @ {fs:.2f} Hz (durée {dur:.2f}{'s' if fs>0 else ' samples'}){rec}{mark}")

    def _buf_dur_str(self, fs: float) -> str:
        if fs <= 0 or self._buf_samples <= 0:
            return "0 s"
        return f"{self._buf_samples / fs:.1f} s"

    def _current_data(self) -> Tuple[np.ndarray, float, List[str]]:
        if self._raw is not None and HAVE_MNE:
            try:
                with mne.use_log_level("ERROR"):
                    X = self._raw.get_data()
                fs = float(self._sf or self._raw.info.get('sfreq', 0.0) or 0.0)
                names = list(self._names or self._raw.ch_names)
                return X, fs, names
            except Exception:
                pass
        if self._seg is not None:
            X = np.asarray(self._seg)
            fs = float(self._sf or 0.0)
            names = list(self._names or [f"Ch{i+1}" for i in range(X.shape[0])])
            return X, fs, names
        return np.zeros((1, 0), float), 0.0, ["Ch1"]

    def _append_to_buffer(self, seg: np.ndarray, fs: float):
        if seg.ndim != 2 or seg.shape[1] == 0:
            return
        self._buf.append(np.asarray(seg, dtype=np.float32))
        self._buf_samples += seg.shape[1]
        if fs > 0 and self._max_sec > 0:
            max_samp = int(self._max_sec * fs)
            if self._buf_samples > max_samp:
                to_drop = self._buf_samples - max_samp
                while to_drop > 0 and self._buf:
                    s0 = self._buf[0].shape[1]
                    if s0 <= to_drop:
                        to_drop -= s0
                        self._buf_samples -= s0
                        self._buf.pop(0)
                    else:
                        self._buf[0] = self._buf[0][:, to_drop:]
                        self._buf_samples -= to_drop
                        to_drop = 0
        self._update_info_label()

    def _concat_buffer(self) -> Optional[np.ndarray]:
        if not self._buf:
            return None
        try:
            return np.concatenate(self._buf, axis=1)
        except Exception:
            L = min((s.shape[1] for s in self._buf), default=0)
            if L <= 0:
                return None
            parts = [s[:, :L] for s in self._buf]
            return np.concatenate(parts, axis=1)

    def _auto_path(self, path: str) -> str:
        if not self._auto_inc or not path:
            return path
        base, ext = os.path.splitext(path)
        k = 1
        p = f"{base}_{k:03d}{ext}"
        while os.path.exists(p):
            k += 1
            p = f"{base}_{k:03d}{ext}"
        return p

    def _to_raw(self, X: np.ndarray, fs: float, names: List[str]):
        if not HAVE_MNE:
            return None
        ch_types = [self._ch_type] * len(names)
        info = mne.create_info(names, sfreq=fs if fs > 0 else 1.0, ch_types=ch_types)
        data = X.astype(np.float64, copy=False)
        if self._units_uV:
            data = data * 1e-6  # µV -> V
        return mne.io.RawArray(data, info)

    def _write_annotations_into_raw(self, raw):
        if not self._mark_buf:
            return
        fs = float(raw.info.get("sfreq", 0.0) or 0.0)
        on, du, lab = self._normalized_markers_for_save(fs)
        if not on:
            return
        ann = mne.Annotations(onset=np.array(on), duration=np.array(du),
                              description=np.array(lab, dtype=object))
        raw.set_annotations(ann)

    def _save_snapshot(self):
        X, fs, names = self._current_data()
        if X.size == 0:
            self._set_status("Pas de données à sauvegarder"); return
        if not self._le_path.text().strip():
            self._choose_target()
            if not self._le_path.text().strip():
                self._set_status("Chemin non choisi"); return

        path = self._auto_path(self._le_path.text().strip())
        ok, msg = self._save_any(path, X, fs, names)
        self._set_status(msg)
        if ok:
            self.outputs["saved_path"].on_next(path)

    def _toggle_rec(self):
        if not self._recording:
            self._recording = True
            self._buf = []; self._buf_samples = 0
            self._mark_buf = []
            self._rec_t0 = time.time()
            self._btn_rec.setText("Stop & Save")
            self._set_status("REC démarré — accumulation des segments…")
        else:
            X = self._concat_buffer()
            if X is None or X.size == 0:
                self._set_status("REC stoppé — rien à sauver")
                self._recording = False; self._btn_rec.setText("Start Rec")
                return
            _, fs, names = self._current_data()
            if not self._le_path.text().strip():
                self._choose_target()
                if not self._le_path.text().strip():
                    self._set_status("Chemin non choisi")
                    self._recording = False; self._btn_rec.setText("Start Rec")
                    return
            path = self._auto_path(self._le_path.text().strip())
            ok, msg = self._save_any(path, X, fs, names)
            self._recording = False
            self._btn_rec.setText("Start Rec")
            self._set_status(msg)
            if ok:
                self.outputs["saved_path"].on_next(path)

    def _clear_buffer(self):
        self._buf = []; self._buf_samples = 0
        self._set_status("Buffer vidé")
        self._update_info_label()

    def _save_any(self, path: str, X: np.ndarray, fs: float, names: List[str]) -> Tuple[bool, str]:
        fmt = self._fmt
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        if fmt == "CSV":
            try:
                if fs > 0 and self._with_time:
                    t = np.arange(X.shape[1]) / fs
                    data = np.vstack([t[None, :], X])
                    header = "time," + ",".join(names)
                else:
                    data = X
                    header = ",".join(names)
                np.savetxt(path, data.T, delimiter=",", header=header, comments="")
                on, du, lab = self._normalized_markers_for_save(fs)
                if on:
                    side = os.path.splitext(path)[0] + ".markers.csv"
                    mk = np.column_stack([on, du, np.array(lab, dtype=object)])
                    np.savetxt(side, mk, delimiter=",", fmt=["%.6f","%.6f","%s"],
                               header="onset_s,duration_s,label", comments="")
                return True, f"CSV sauvegardé → {path}"
            except Exception as e:
                return False, f"CSV échec: {e}"

        if fmt == "NPZ":
            try:
                on, du, lab = self._normalized_markers_for_save(fs)
                np.savez_compressed(path, data=X, sfreq=float(fs),
                                    ch_names=np.array(names, dtype=object),
                                    markers_onset=np.array(on, float),
                                    markers_duration=np.array(du, float),
                                    markers_label=np.array(lab, dtype=object))
                return True, f"NPZ sauvegardé → {path}"
            except Exception as e:
                return False, f"NPZ échec: {e}"

        if fmt == "MAT":
            if not HAVE_SCIPY:
                return False, "SciPy indisponible pour .mat"
            try:
                on, du, lab = self._normalized_markers_for_save(fs)
                obj = {"data": X, "sfreq": float(fs), "ch_names": np.array(names, dtype=object),
                       "markers": {"onset_s": np.array(on, float),
                                   "duration_s": np.array(du, float),
                                   "label": np.array(lab, dtype=object)}}
                _savemat(path, obj)
                return True, f"MAT sauvegardé → {path}"
            except Exception as e:
                return False, f"MAT échec: {e}"

        if not HAVE_MNE:
            return False, "MNE indisponible — utilise CSV/NPZ/MAT"

        try:
            raw = self._to_raw(X, fs, names)
        except Exception as e:
            return False, f"Création RawArray échouée: {e}"
        if raw is None:
            return False, "Impossible de créer un Raw MNE"

        try:
            self._write_annotations_into_raw(raw)
        except Exception:
            pass

        try:
            if fmt == "FIF":
                if not path.lower().endswith(".fif"):
                    path = path + ".fif"
                raw.save(path, overwrite=True)
                return True, f"FIF sauvegardé → {path}"

            if fmt in ("EDF", "BDF", "BrainVision"):
                if not _HAVE_EXPORT:
                    return False, "mne.export.export_raw indisponible (MNE trop ancien ?)"
                if fmt == "EDF" and not path.lower().endswith(".edf"): path += ".edf"
                if fmt == "BDF" and not path.lower().endswith(".bdf"): path += ".bdf"
                if fmt == "BrainVision" and not path.lower().endswith(".vhdr"): path += ".vhdr"
                kind = {"EDF": "edf", "BDF": "bdf", "BrainVision": "brainvision"}[fmt]
                _mne_export_raw(path, raw, fmt=kind)
                return True, f"{fmt} sauvegardé → {path}"

            return False, f"Format inconnu: {fmt}"
        except Exception as e:
            return False, f"Export {fmt} échec: {e}"

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        try:
            self._lbl_head.setText(f"EEGSaver — {msg}")
            self._lbl_status.setText(msg)
        except Exception:
            pass
