# -*- coding: utf-8 -*-
"""
MAT → MNE Raw (BNCI/BCI-Compatible Loader)

Lis un fichier .mat (BNCI/BCI/BBCl) et produit un mne.io.Raw prêt pour MNE Viewer 2D.
- Schémas supportés (auto-détection):
  (A) BBCI/BCI Comp: 'cnt' (time×chan), 'mrk.pos', 'mrk.y', 'nfo.clab', 'nfo.fs'
  (B) BNCI-like: 'X' (samples×channels ou trials×channels×samples), 'trial'/'pos', 'y'/'labels', 'fs'
  (C) fallback: 'data'/'signals'/'s' → inférence minimale

- Echelle: int16 'cnt' → 0.1 µV/count (converti en Volts); sinon heuristique µV→V
- Types de canaux: détection par nom ('EOG','ECG','EMG' → eog/ecg/emg, sinon eeg)
- Annotations: événements depuis mrk.pos ou trial/pos
- Montage optionnel: standard_1020 / standard_1005 / easycap-M1 / biosemi64 / (none)

Câblage simple:
  MAT → MNE Raw  ──▶  (optionnel) MNE Set Montage (robuste)  ──▶  (optionnel) MNE Compute SSP Projs  ──▶  MNE Viewer 2D

"""
from typing import Optional, Dict, Any, Tuple, List
import os
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QLineEdit, QFileDialog, QCheckBox
)
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


class MATToMNERaw(BasePlugin):
    name = "MAT → MNE Raw"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        # Outputs
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        # UI state
        self._widget: Optional[QWidget] = None
        self._path: str = ""
        self._montage: str = "standard_1020"
        self._force_uV: bool = False  # forcer µV → V

    # -------------------- UI --------------------
    def build_widget(self) -> QWidget:
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(6,6,6,6); root.setSpacing(6)

        title = QLabel("MAT → MNE Raw (BNCI/BCI)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        if not HAVE_MNE:
            warn = QLabel("MNE non installé. `pip install mne`. ")
            warn.setStyleSheet("color:#b00"); warn.setWordWrap(True)
            root.addWidget(warn)
        if not (HAVE_SCIPY or HAVE_H5PY):
            warn = QLabel("Installez au moins l'un: `pip install scipy` (MAT v7.2) ou `pip install h5py` (MAT v7.3).")
            warn.setStyleSheet("color:#b00"); warn.setWordWrap(True)
            root.addWidget(warn)

        # Path chooser
        path_row = QHBoxLayout()
        self._ed_path = QLineEdit(self._path)
        self._ed_path.setPlaceholderText("Chemin du fichier .mat …")
        btn_browse = QPushButton("Parcourir…")
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self._ed_path, 1); path_row.addWidget(btn_browse)
        root.addLayout(path_row)

        # Options row
        opt = QHBoxLayout()
        opt.addWidget(QLabel("Montage"))
        self._cmb_mont = QComboBox(); self._cmb_mont.addItems(["standard_1020","standard_1005","easycap-M1","biosemi64","(none)"])
        self._cmb_mont.setCurrentText(self._montage)
        self._cmb_mont.currentTextChanged.connect(self._on_mont)
        opt.addWidget(self._cmb_mont)
        self._chk_force = QCheckBox("Forcer µV → V")
        self._chk_force.setChecked(self._force_uV)
        self._chk_force.toggled.connect(self._on_force_uv)
        opt.addWidget(self._chk_force)
        root.addLayout(opt)

        # Controls
        ctr = QHBoxLayout()
        btn_load = QPushButton("Charger → Raw")
        btn_load.clicked.connect(self._load)
        ctr.addWidget(btn_load)
        root.addLayout(ctr)

        self._lbl = QLabel(""); self._lbl.setStyleSheet("color:#666"); root.addWidget(self._lbl)
        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def _browse(self):
        dlg = QFileDialog()
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
                self._set_status("Chemin invalide."); return
            raw = self._read_mat_to_raw(self._path)
            if raw is None:
                self._set_status("Échec de lecture MAT → Raw."); return
            # Optional montage
            mont_name = self._montage
            if mont_name and mont_name != "(none)":
                try:
                    mont = mne.channels.make_standard_montage(mont_name)
                    raw.set_montage(mont, match_case=False, on_missing='ignore')
                except Exception:
                    pass
            self.outputs["raw"].on_next(raw)
            dur = raw.n_times / raw.info['sfreq']
            self._set_status(f"RAW prêt: {len(raw.ch_names)} ch | sf={raw.info['sfreq']:.1f} Hz | durée={dur:.1f}s | path={os.path.basename(self._path)}")
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
        if x is None: return []
        if isinstance(x, (list, tuple)):
            return [str(xx) for xx in x]
        a = np.atleast_1d(np.array(x, dtype=object))
        return [str(xx) for xx in a.tolist()]

    def _guess_ch_types(self, names: List[str]) -> List[str]:
        types = []
        for n in names:
            u = str(n).upper()
            if 'EOG' in u: types.append('eog')
            elif 'ECG' in u or 'EKG' in u: types.append('ecg')
            elif 'EMG' in u: types.append('emg')
            else: types.append('eeg')
        return types

    def _scale_to_volts(self, X: np.ndarray, int16_hint: bool) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self._force_uV:
            return X * 1e-6
        if int16_hint:
            # BBCI cnt int16 → 0.1 µV per count
            return X * 0.1e-6
        # heuristic: typical EEG in µV has large magnitudes (hundreds)
        maxabs = np.nanmax(np.abs(X)) if X.size else 0.0
        if maxabs > 1e-1:  # >0.1 V improbable for EEG → probably µV
            return X * 1e-6
        return X  # assume already Volts

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
            if isinstance(cnt, dict) and 'x' in cnt:  # sometimes nested as struct
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
                    try: sfreq = float(np.asarray(fs).ravel()[0])
                    except Exception: pass
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
            # ch names if available
            ch_names = self._to_list_str(D.get('clab') or D.get('chan') or D.get('channels'))
            if X.ndim == 3:
                # assume (trials, channels, samples) or (channels, samples, trials)
                shape = X.shape
                # pick channels axis as the one matching len(ch_names) or the middle
                if ch_names and any(len(ch_names) == s for s in shape):
                    ch_ax = [i for i,s in enumerate(shape) if s == len(ch_names)][0]
                else:
                    ch_ax = 1  # heuristic
                # move to (trials, samples, channels)
                # determine samples axis as the largest non-channel axis
                axes = list(range(3))
                axes.remove(ch_ax)
                other = axes
                samp_ax = other[0] if shape[other[0]] >= shape[other[1]] else other[1]
                trial_ax = other[1] if samp_ax == other[0] else other[0]
                X = np.moveaxis(X, (trial_ax, samp_ax, ch_ax), (0,1,2))  # (trials, samples, channels)
                # concat trials along time
                X = X.reshape(-1, X.shape[2])  # (samples_all, channels)
            elif X.ndim == 2:
                if X.shape[1] < X.shape[0]:
                    # often samples×channels → ok
                    pass
                else:
                    X = X.T  # time×chan
            else:
                raise RuntimeError("Format X inconnu (ni 2D ni 3D)")
            data = X  # time×chan
            # fs
            fs = D.get('fs') or D.get('sfreq') or D.get('srate')
            if fs is not None:
                try: sfreq = float(np.asarray(fs).ravel()[0])
                except Exception: pass
            # ch names
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
            for key in ('data','signals','s'):
                if key in D:
                    X = np.asarray(D[key])
                    if X.ndim == 2:
                        data = X
                        break
                    if X.ndim == 3:
                        # assume (trials, samples, channels)
                        if X.shape[-1] < X.shape[-2]:
                            X = np.transpose(X, (0,2,1))
                        data = X.reshape(-1, X.shape[-1])
                        break
            if data is None:
                # take first 2D plausible array
                for k, v in D.items():
                    arr = np.asarray(v)
                    if arr.ndim == 2 and min(arr.shape) >= 8:
                        data = arr; break
            if data is None:
                raise RuntimeError("Impossible d'identifier la matrice EEG dans ce .mat")
            # fs & names
            if sfreq is None:
                sfreq = 250.0
            ch_names = self._to_list_str(D.get('clab') or D.get('chan') or D.get('channels')) \
                       or [f'Ch{i+1}' for i in range(data.shape[1])]
            ch_types = self._guess_ch_types(ch_names)

        if sfreq is None:
            sfreq = 250.0

        # Ensure time×chan then convert to Volts
        X = np.asarray(data)
        if X.shape[0] < X.shape[1]:
            X = X.T  # ensure time×chan
        XV = self._scale_to_volts(X, int16_hint)

        info = mne.create_info(ch_names=ch_names, sfreq=float(sfreq), ch_types=ch_types)
        raw = mne.io.RawArray(XV.T, info)  # MNE expects (n_channels, n_times)

        if annotations is not None:
            raw.set_annotations(annotations)
        return raw
