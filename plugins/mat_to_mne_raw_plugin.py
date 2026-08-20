# -*- coding: utf-8 -*-
"""
MAT → MNE Raw (BNCI/BCI-Compatible Loader) — avec zone Paramètres pliable (fermée par défaut)
"""
from typing import Optional, Dict, Any, List
import os
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QFileDialog, QCheckBox, QFrame, QSizePolicy, QLayout
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

# Optional MAT readers
try:
    from scipy.io import loadmat as _scipy_loadmat
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False

try:
    import h5py as _h5py
    HAVE_H5PY = True
except Exception:
    HAVE_H5PY = False


# ---------------------- CollapsibleSection robuste (anti "rectangle gris") ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parents (QGraphicsProxyWidget friendly).
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
        self._btn.setChecked(False)  # unchecked => fermé (on applique l'état nous-mêmes)
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


class MATToMNERaw(BasePlugin):
    help = {
        'gotchas': ['Requires MNE (pip install mne) plus scipy (v7.2) or h5py (v7.3).',
               'Auto-detects BBCI (cnt/mrk/nfo), BNCI (X/y/trial), and generic formats.',
               '"Forcer µV → V" multiplies all data by 1e-6; use if data is in microvolts.',
               'Int16 data (common in BBCI) is auto-scaled at 0.1 µV per count.',
               'Montage is applied after loading; non-matching channel names are ignored.'],
        'inputs': {},
        'outputs': {
            'raw': 'mne.io.RawArray — loaded and scaled recording',
            'status': 'str — load status message',
        },
        'parameters': [
            {'name': 'filepath', 'type': 'path', 'default': '', 'desc': 'MAT file to load'},
            {'name': 'montage', 'type': 'str', 'default': 'standard_1020',
             'desc': 'Standard montage to apply',
             'enum': ['standard_1020', 'standard_1005', 'easycap-M1', 'biosemi64', '(none)']},
            {'name': 'force_uV', 'type': 'bool', 'default': False,
             'desc': 'Force µV → V scaling'},
        ],
        'summary': 'Load .mat EEG files (BBCI/BCI-Compatible) and convert to MNE Raw.',
        'usage': 'Browse and load a .mat file; connects `raw` to downstream MNE-compatible nodes.'
    }

    name = "MAT → MNE Raw"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        # Sorties
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")

        # État UI
        self._widget: Optional[QWidget] = None
        self._path: str = ""
        self._montage: str = "standard_1020"
        self._force_uV: bool = False  # forcer µV → V

    # -------------------- UI --------------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("MAT → MNE Raw (BNCI/BCI)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        # Avertissements
        if not HAVE_MNE:
            warn = QLabel("MNE non installé. `pip install mne`.")
            warn.setStyleSheet("color:#b00")
            warn.setWordWrap(True)
            root.addWidget(warn)
        if not (HAVE_SCIPY or HAVE_H5PY):
            warn = QLabel("Installez `scipy` (MAT v7.2) ou `h5py` (MAT v7.3).")
            warn.setStyleSheet("color:#b00")
            warn.setWordWrap(True)
            root.addWidget(warn)

        # --- Section pliable : Paramètres (fermée par défaut) ---
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)  # fermé au démarrage
        # Forcer le recalcul du node lors de l'ouverture/fermeture
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Ligne chemin + Parcourir…
        path_row = QWidget()
        hl = QHBoxLayout(path_row); hl.setContentsMargins(0, 0, 0, 0); hl.setSpacing(6)
        self._ed_path = QLineEdit(self._path)
        self._ed_path.setPlaceholderText("Chemin du fichier .mat …")
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self._browse)
        hl.addWidget(self._ed_path, 1)
        hl.addWidget(btn_browse)

        # Options (Montage + µV→V)
        opt_row = QWidget()
        opt = QHBoxLayout(opt_row); opt.setContentsMargins(0, 0, 0, 0); opt.setSpacing(8)
        lab_m = QLabel("Montage")
        self._cmb_mont = QComboBox()
        self._cmb_mont.addItems(["standard_1020", "standard_1005", "easycap-M1", "biosemi64", "(none)"])
        self._cmb_mont.setCurrentText(self._montage)
        self._cmb_mont.currentTextChanged.connect(self._on_mont)
        self._chk_force = QCheckBox("Forcer µV → V")
        self._chk_force.setChecked(self._force_uV)
        self._chk_force.toggled.connect(self._on_force_uv)
        opt.addWidget(lab_m)
        opt.addWidget(self._cmb_mont)
        opt.addStretch(1)
        opt.addWidget(self._chk_force)

        # Boutons d’action
        ctr_row = QWidget()
        ctr = QHBoxLayout(ctr_row); ctr.setContentsMargins(0, 0, 0, 0); ctr.setSpacing(6)
        btn_load = QPushButton("Charger → Raw")
        btn_load.clicked.connect(self._load)
        ctr.addStretch(1)
        ctr.addWidget(btn_load)

        # Ajouter les widgets dans la section pliable
        sec.add_content_widget(path_row)
        sec.add_content_widget(opt_row)
        sec.add_content_widget(ctr_row)

        # Status (toujours visible)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl)

        # Contraintes pour supprimer tout résidu d’espace
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def _browse(self):
        dlg = QFileDialog(self._widget)
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter("MAT files (*.mat)")
        if dlg.exec_():
            sel = dlg.selectedFiles()
            if sel:
                self._path = sel[0]
                self._ed_path.setText(self._path)

    def _on_mont(self, name: str):
        self._montage = name

    def _on_force_uv(self, on: bool):
        self._force_uV = bool(on)

    # ----------------- Exec -----------------
    def execute(self, *args, **kwargs):
        # Passive; only loads on button press
        pass

    # ----------------- Loader core -----------------
    def _load(self):
        try:
            self._path = self._ed_path.text().strip()
            if not self._path or not os.path.isfile(self._path):
                self._set_status("Chemin invalide.")
                return
            raw = self._read_mat_to_raw(self._path)
            if raw is None:
                self._set_status("Échec de lecture MAT → Raw.")
                return
            # Montage optionnel
            mont_name = self._montage
            if mont_name and mont_name != "(none)":
                try:
                    mont = mne.channels.make_standard_montage(mont_name)
                    raw.set_montage(mont, match_case=False, on_missing='ignore')
                except Exception:
                    pass
            self.outputs["raw"].on_next(raw)
            dur = raw.n_times / raw.info['sfreq']
            self._set_status(
                f"RAW prêt: {len(raw.ch_names)} ch | sf={raw.info['sfreq']:.1f} Hz | "
                f"durée={dur:.1f}s | path={os.path.basename(self._path)}"
            )
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    # ----------------- Utils -----------------
    def _load_mat_any(self, path: str) -> Dict[str, Any]:
        D = None
        if HAVE_SCIPY:
            try:
                D = _scipy_loadmat(path, squeeze_me=True, struct_as_record=False)
                D = {k: v for k, v in D.items() if not k.startswith('__')}
                return D
            except Exception:
                D = None
        if HAVE_H5PY:
            try:
                with _h5py.File(path, 'r') as f:
                    def h5_to_obj(obj):
                        import numpy as _np
                        import h5py as _h5
                        if isinstance(obj, _h5.Dataset):
                            arr = obj[()]
                            return _np.array(arr)
                        elif isinstance(obj, _h5.Group):
                            return {k: h5_to_obj(obj[k]) for k in obj.keys()}
                        return obj
                    out = {k: h5_to_obj(f[k]) for k in f.keys()}
                    return out
            except Exception:
                pass
        raise RuntimeError("Impossible de lire le .mat — installez scipy ou h5py.")

    def _to_list_str(self, x) -> List[str]:
        if x is None:
            return []
        if isinstance(x, (list, tuple)):
            return [str(xx) for xx in x]
        a = np.atleast_1d(np.array(x, dtype=object))
        return [str(xx) for xx in a.tolist()]

    def _guess_ch_types(self, names: List[str]) -> List[str]:
        types = []
        for n in names:
            u = str(n).upper()
            if 'EOG' in u:
                types.append('eog')
            elif 'ECG' in u or 'EKG' in u:
                types.append('ecg')
            elif 'EMG' in u:
                types.append('emg')
            else:
                types.append('eeg')
        return types

    def _scale_to_volts(self, X: np.ndarray, int16_hint: bool) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self._force_uV:
            return X * 1e-6
        if int16_hint:
            # BBCI cnt int16 → 0.1 µV per count
            return X * 0.1e-6
        maxabs = np.nanmax(np.abs(X)) if X.size else 0.0
        if maxabs > 1e-1:  # >0.1 V improbable pour EEG → probablement µV
            return X * 1e-6
        return X

    def _read_mat_to_raw(self, path: str):
        if not HAVE_MNE:
            raise RuntimeError("MNE non installé")
        D = self._load_mat_any(path)

        data = None
        sfreq = None
        ch_names: List[str] = []
        ch_types: List[str] = []
        annotations = None
        int16_hint = False

        # ---- Case A: BBCI/BCI: cnt, mrk, nfo ----
        if ('cnt' in D) or ('mrk' in D) or ('nfo' in D):
            cnt = D.get('cnt')
            if isinstance(cnt, dict) and 'x' in cnt:
                cnt = cnt['x']
            if cnt is None:
                raise RuntimeError("Fichier MAT: variable 'cnt' absente.")
            A = np.asarray(cnt)
            if A.ndim != 2:
                A = np.atleast_2d(A)
                if A.shape[0] < A.shape[1]:
                    A = A.T  # time×chan
            if A.dtype == np.int16:
                int16_hint = True
            # channel names + fs
            nfo = D.get('nfo') or D.get('info') or {}
            if isinstance(nfo, dict):
                clab = nfo.get('clab') or nfo.get('chan') or nfo.get('channels')
                ch_names = self._to_list_str(clab)
                fs = nfo.get('fs') or nfo.get('srate') or nfo.get('samplingrate')
                if fs is not None:
                    try:
                        sfreq = float(np.asarray(fs).ravel()[0])
                    except Exception:
                        pass
            if not ch_names:
                ch_names = [f'Ch{i+1}' for i in range(A.shape[1])]
            ch_types = self._guess_ch_types(ch_names)
            data = A  # time×chan
            # events
            mrk = D.get('mrk') or {}
            if isinstance(mrk, dict):
                pos = mrk.get('pos'); y = mrk.get('y')
                if pos is not None:
                    pos = np.atleast_1d(np.asarray(pos).astype(int))
                    if y is not None:
                        y = np.atleast_1d(np.asarray(y).squeeze())
                        desc = [f"class_{int(v)}" for v in y]
                    else:
                        desc = ["event"] * len(pos)
                    sf = float(sfreq or 1.0)
                    onset = pos / sf
                    durations = np.zeros_like(onset, dtype=float)
                    annotations = mne.Annotations(onset=onset, duration=durations, description=desc)

        # ---- Case B: BNCI-like: X, trial/pos, y/labels, fs ----
        elif ('X' in D) and (('y' in D) or ('labels' in D) or ('trial' in D) or ('pos' in D)):
            X = np.asarray(D['X'])
            ch_names = self._to_list_str(D.get('clab') or D.get('chan') or D.get('channels'))
            if X.ndim == 3:
                # Assumer (trials, channels, samples) → (samples_all, channels)
                shape = X.shape
                if ch_names and any(len(ch_names) == s for s in shape):
                    ch_ax = [i for i, s in enumerate(shape) if s == len(ch_names)][0]
                else:
                    ch_ax = 1
                axes = list(range(3))
                axes.remove(ch_ax)
                other = axes
                samp_ax = other[0] if shape[other[0]] >= shape[other[1]] else other[1]
                trial_ax = other[1] if samp_ax == other[0] else other[0]
                X = np.moveaxis(X, (trial_ax, samp_ax, ch_ax), (0, 1, 2))  # (trials, samples, channels)
                X = X.reshape(-1, X.shape[2])  # concat trials
            elif X.ndim == 2:
                if X.shape[1] >= X.shape[0]:
                    X = X.T  # time×chan
            else:
                raise RuntimeError("Format X inconnu (ni 2D ni 3D)")
            data = X
            # fs
            fs = D.get('fs') or D.get('sfreq') or D.get('srate')
            if fs is not None:
                try:
                    sfreq = float(np.asarray(fs).ravel()[0])
                except Exception:
                    pass
            if not ch_names:
                ch_names = [f'Ch{i+1}' for i in range(data.shape[1])]
            ch_types = self._guess_ch_types(ch_names)
            # events
            trial = D.get('trial') or D.get('trials') or D.get('pos')
            y = D.get('y') or D.get('labels')
            if trial is not None:
                trial = np.atleast_1d(np.asarray(trial).astype(int))
                if y is not None:
                    y = np.atleast_1d(np.asarray(y).squeeze())
                    desc = [f"class_{int(v)}" for v in y]
                else:
                    desc = ["event"] * len(trial)
                sf = float(sfreq or 1.0)
                onset = trial / sf
                durations = np.zeros_like(onset, dtype=float)
                annotations = mne.Annotations(onset=onset, duration=durations, description=desc)

        # ---- Case C: fallback ----
        else:
            for key in ('data', 'signals', 's'):
                if key in D:
                    X = np.asarray(D[key])
                    if X.ndim == 2:
                        data = X
                        break
                    if X.ndim == 3:
                        if X.shape[-1] < X.shape[-2]:
                            X = np.transpose(X, (0, 2, 1))
                        data = X.reshape(-1, X.shape[-1])
                        break
            if data is None:
                for k, v in D.items():
                    arr = np.asarray(v)
                    if arr.ndim == 2 and min(arr.shape) >= 8:
                        data = arr
                        break
            if data is None:
                raise RuntimeError("Impossible d'identifier la matrice EEG dans ce .mat")
            if sfreq is None:
                sfreq = 250.0
            ch_names = self._to_list_str(D.get('clab') or D.get('chan') or D.get('channels')) \
                       or [f'Ch{i+1}' for i in range(data.shape[1])]
            ch_types = self._guess_ch_types(ch_names)

        if sfreq is None:
            sfreq = 250.0

        # time×chan → Volts
        X = np.asarray(data)
        if X.shape[0] < X.shape[1]:
            X = X.T
        XV = self._scale_to_volts(X, int16_hint)

        info = mne.create_info(ch_names=ch_names, sfreq=float(sfreq), ch_types=ch_types)
        raw = mne.io.RawArray(XV.T, info)  # (n_channels, n_times)

        if annotations is not None:
            raw.set_annotations(annotations)
        return raw
