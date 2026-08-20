# -*- coding: utf-8 -*-
"""
MNEDatasetLoader — MNE-only loader (EEGBCI) that outputs (pos, ch_names, values)
ready for viewers, **plus a 'band_values' output** (Delta/Theta/Alpha/Beta/Gamma).

Paramètres pliables:
- Section “Paramètres” fermée par défaut
- Aucun espace gris résiduel au repli (QGraphicsProxyWidget-friendly)
"""
from typing import Dict, List, Optional, Tuple
import re
import numpy as np

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QHBoxLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QPushButton, QSpinBox, QSizePolicy, QLayout, QFrame
)
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    from mne.datasets import eegbci
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


# ---------------------- CollapsibleSection robuste (anti "rectangle gris") ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parents.
    """
    collapsedChanged = pyqtSignal(bool)  # True si fermé

    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._base_title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # on applique l'état nous-mêmes (démarrage fermé)
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

    # API
    def content_layout(self):
        return self._content_layout

    def add_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)  # checked => ouvert
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Slots
    def _on_toggled(self, checked: bool):
        collapsed = (not checked)
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Implémentation
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


class MNEDatasetLoader(BasePlugin):
    name = "MNEDatasetLoader"
    language = "Python"
    category = "Input Nodes"

    help = {
        'gotchas': ['Requires MNE + mne.datasets.eegbci (downloads EEGBCI data on first use).',
               'Channel names are auto-remapped to standard 10-20/10-05 equivalents.',
               'Montage is auto-selected from best matching standard template.',
               'Only EEG channels are used (EOG/ECG/EMG excluded).'],
        'inputs': {},
        'outputs': {
            'pos': 'dict[str → tuple(x,y,z)] — 3D channel positions',
            'ch_names': 'list[str] — channel names with montage positions',
            'values': 'dict[str → float] — per-channel metric values (RMS or band power)',
            'band_values': 'dict[str → dict[str → float]] — per-band per-channel power',
            'status': 'str — load status message',
        },
        'parameters': [
            {'name': 'subject', 'type': 'int', 'default': 1, 'desc': 'EEGBCI subject ID (1–109)'},
            {'name': 'runs', 'type': 'str', 'default': '6',
             'desc': 'Run numbers (comma-separated, e.g. "6" or "3,7,11")'},
            {'name': 'duration_s', 'type': 'float', 'default': 15.0, 'unit': 's',
             'desc': 'Duration of data used for metric computation'},
            {'name': 'metric', 'type': 'str', 'default': 'RMS',
             'desc': 'Per-channel metric to compute',
             'enum': ['RMS', 'Alpha (8-12 Hz)', 'Beta (13-30 Hz)', 'Theta (4-7 Hz)']},
        ],
        'summary': 'Load EEGBCI dataset and compute per-channel metric + band powers for topomaps.',
        'usage': 'Click "Charger" after setting subject/runs; outputs channel positions and '
                 'values for topographic map visualization.'
    }

    def setup(self):
        self.outputs["pos"] = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["values"] = BehaviorSubject(None)
        self.outputs["band_values"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        self._widget: Optional[QWidget] = None
        self._subject = 1
        self._runs = "6"
        self._dur_s = 15.0
        self._metric = "RMS"

    # ---------------- UI ----------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("MNE Dataset Loader → Topomaps 2D/3D")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        if not HAVE_MNE:
            msg = QLabel("MNE n'est pas installé. `pip install mne`.")
            msg.setStyleSheet("color:#b00;")
            root.addWidget(msg)
            self._widget = w
            return w

        # -------- Paramètres (pliable, fermé par défaut) --------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)
        # Reflow du node quand on ouvre/ferme
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Row: Subject / Runs
        row_id = QHBoxLayout()
        row_id.addWidget(QLabel("Subject (1..109):"))
        self._sp_subj = QSpinBox()
        self._sp_subj.setRange(1, 109)
        self._sp_subj.setValue(self._subject)
        row_id.addWidget(self._sp_subj)
        row_id.addWidget(QLabel("Runs:"))
        self._ed_runs = QLineEdit(self._runs)
        self._ed_runs.setPlaceholderText("ex: 6 ou 3,7,11")
        row_id.addWidget(self._ed_runs, 1)
        sec.content_layout().addLayout(row_id)

        # Row: Durée / Métrique
        row_m = QHBoxLayout()
        row_m.addWidget(QLabel("Durée utilisée (s):"))
        self._sp_dur = QDoubleSpinBox()
        self._sp_dur.setRange(0.0, 600.0)
        self._sp_dur.setDecimals(1)
        self._sp_dur.setSingleStep(1.0)
        self._sp_dur.setValue(self._dur_s)
        row_m.addWidget(self._sp_dur)
        row_m.addWidget(QLabel("Métrique:"))
        self._cmb_metric = QComboBox()
        self._cmb_metric.addItems(["RMS", "Alpha (8-12 Hz)", "Beta (13-30 Hz)", "Theta (4-7 Hz)"])
        row_m.addWidget(self._cmb_metric, 1)
        sec.content_layout().addLayout(row_m)

        # Row: Bouton
        row_btn = QHBoxLayout()
        self._btn = QPushButton("Charger")
        self._btn.clicked.connect(self._on_load)
        row_btn.addWidget(self._btn)
        sec.content_layout().addLayout(row_btn)

        # Status
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

    # -------------- helpers --------------
    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    _re_non_alnum = re.compile(r"[^A-Z0-9]+")

    def _canon(self, n: str) -> str:
        s = str(n).upper().strip()
        for pref in ("EEG ", "EEG_", "EEG-"):
            if s.startswith(pref):
                s = s[len(pref):]
        for suf in ("-REF", "-LE", "-RE", "-A1", "-A2"):
            if s.endswith(suf):
                s = s[: -len(suf)]
        s = self._re_non_alnum.sub("", s)
        return s

    def _alias(self, c: str) -> str:
        return {
            "T9": "TP9",
            "T10": "TP10",
            "POZ": "POz",
            "FZ": "Fz",
            "CZ": "Cz",
            "PZ": "Pz",
            "OZ": "Oz",
            "FPZ": "Fpz",
        }.get(c, c)

    def _best_montage_and_mapping(self, raw) -> Tuple["mne.channels.Montage", Dict[str, str], int]:
        candidates = ["standard_1005", "standard_1020", "biosemi64", "easycap-M1"]
        best = None
        best_hits = -1
        best_map: Dict[str, str] = {}
        for cand in candidates:
            try:
                mont = mne.channels.make_standard_montage(cand)
            except Exception:
                continue
            canon_to_std = {self._canon(n): n for n in mont.ch_names}
            mapping = {}
            hits = 0
            for nm in raw.ch_names:
                c = self._canon(nm)
                c = self._alias(c)
                if c in canon_to_std:
                    mapping[nm] = canon_to_std[c]
                    hits += 1
            if hits > best_hits:
                best_hits = hits
                best = mont
                best_map = mapping
        if best is None:
            best = mne.channels.make_standard_montage("standard_1020")
            best_hits = 0
            best_map = {}
        return best, best_map, best_hits

    def _compute_metric(self, data: np.ndarray, sfreq: float, metric: str) -> np.ndarray:
        if data.ndim != 2:
            data = np.atleast_2d(data)
            if data.shape[0] > data.shape[1]:
                pass
            else:
                data = data.T
        if metric.startswith("RMS"):
            return np.sqrt(np.mean(data.astype(float) ** 2, axis=1))
        fmin, fmax = {
            "Alpha (8-12 Hz)": (8.0, 12.0),
            "Beta (13-30 Hz)": (13.0, 30.0),
            "Theta (4-7 Hz)": (4.0, 7.0),
        }.get(metric, (8.0, 12.0))
        try:
            from mne.time_frequency import psd_array_welch
            psd, freqs = psd_array_welch(data, sfreq=sfreq, fmin=fmin, fmax=fmax,
                                         average='mean', n_fft=min(1024, data.shape[1]))
            band_pow = np.trapz(psd, freqs, axis=1) / max(1.0, (fmax - fmin))
            return band_pow
        except Exception:
            n = data.shape[1]
            freqs = np.fft.rfftfreq(n, d=1.0 / sfreq)
            F = np.abs(np.fft.rfft(data, axis=1)) ** 2 / n
            sel = (freqs >= fmin) & (freqs <= fmax)
            return F[:, sel].mean(axis=1) if sel.any() else np.sqrt(np.mean(data ** 2, axis=1))

    def _compute_band_powers(self, data: np.ndarray, sfreq: float) -> Dict[str, np.ndarray]:
        bands = {
            "Delta (0-4 Hz)": (0.0, 4.0),
            "Theta (4-8 Hz)": (4.0, 8.0),
            "Alpha (8-12 Hz)": (8.0, 12.0),
            "Beta (12-30 Hz)": (12.0, 30.0),
            "Gamma (30-45 Hz)": (30.0, 45.0),
        }
        out: Dict[str, np.ndarray] = {}
        try:
            from mne.time_frequency import psd_array_welch
            n_fft = min(2048, data.shape[1])
            for label, (fmin, fmax) in bands.items():
                psd, freqs = psd_array_welch(
                    data, sfreq=sfreq, fmin=fmin, fmax=fmax, average='mean', n_fft=n_fft
                )
                out[label] = np.trapz(psd, freqs, axis=1) / max(1.0, (fmax - fmin))
        except Exception:
            n = data.shape[1]
            freqs = np.fft.rfftfreq(n, d=1.0 / sfreq)
            F = np.abs(np.fft.rfft(data, axis=1)) ** 2 / n
            for label, (fmin, fmax) in bands.items():
                sel = (freqs >= fmin) & (freqs <= fmax)
                out[label] = F[:, sel].mean(axis=1) if sel.any() else np.sqrt(np.mean(data ** 2, axis=1))
        return out

    # -------------- action --------------
    def _on_load(self):
        if not HAVE_MNE:
            self._set_status("MNE non dispo")
            return
        try:
            subj = int(self._sp_subj.value())
            runs = [int(x) for x in (self._ed_runs.text().strip() or "6").replace(";", ",").split(",") if x.strip()]
            dur = float(self._sp_dur.value())
            metric = self._cmb_metric.currentText()

            file_paths = eegbci.load_data(subj, runs)
            raws = [mne.io.read_raw_edf(fp, preload=True, stim_channel=None, verbose=False) for fp in file_paths]
            raw = mne.concatenate_raws(raws)

            montage, rename_map, hits = self._best_montage_and_mapping(raw)
            if rename_map:
                raw.rename_channels(rename_map)
            try:
                raw.set_montage(montage, match_case=False, on_missing='ignore', verbose=False)
            except TypeError:
                raw.set_montage(montage, match_case=False)

            picks = mne.pick_types(
                raw.info, eeg=True, meg=False, stim=False, eog=False, emg=False, ecg=False, seeg=False, misc=False
            )
            if len(picks) == 0:
                raise RuntimeError("Aucun canal EEG trouvé après renommage.")

            sf = float(raw.info['sfreq'])
            if dur > 0 and np.isfinite(sf) and sf > 0:
                n_win = max(1, int(round(dur * sf)))
                start = max(0, raw.n_times - n_win)
                stop = raw.n_times
            else:
                start, stop = 0, raw.n_times

            data = raw.get_data(picks=picks, start=start, stop=stop)
            used_names = [raw.ch_names[i] for i in picks]
            vals = self._compute_metric(data, sf, metric)

            # bands
            band_arrs = self._compute_band_powers(data, sf)  # dict[label] -> (n_ch,)

            pos_m = raw.get_montage() or montage
            ch_pos = pos_m.get_positions()['ch_pos'] if pos_m is not None else {}

            pos_dict: Dict[str, Tuple[float, float, float]] = {}
            values_dict: Dict[str, float] = {}
            ch_out: List[str] = []
            for nm, v in zip(used_names, vals):
                xyz = ch_pos.get(nm)
                if xyz is None or not np.all(np.isfinite(xyz)):
                    continue
                ch_out.append(nm)
                pos_dict[nm] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))
                values_dict[nm] = float(v)

            if len(ch_out) == 0:
                raise RuntimeError("Positions non trouvées après application du montage.")

            # band_values dict[str -> dict[name -> value]] aligné à ch_out
            band_values: Dict[str, Dict[str, float]] = {}
            name_to_idx = {n: i for i, n in enumerate(used_names)}
            for label, arr in band_arrs.items():
                band_dict: Dict[str, float] = {}
                for nm in ch_out:
                    idx = name_to_idx.get(nm, None)
                    if idx is None:
                        continue
                    band_dict[nm] = float(arr[idx])
                band_values[label] = band_dict

            self.outputs["pos"].on_next(pos_dict)
            self.outputs["ch_names"].on_next(ch_out)
            self.outputs["values"].on_next(values_dict)
            self.outputs["band_values"].on_next(band_values)
            info = (
                f"EEGBCI s{subj} runs {runs}: {len(ch_out)} canaux "
                f"(montage={getattr(montage,'kind',type(montage).__name__)}, "
                f"renamed={len(rename_map)}, hits={hits}, durée={dur}s, métrique={metric})."
            )
            self._set_status(info)
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    # --- reactive no-op ---
    def execute(self, *call_args, **call_kwargs):
        try:
            if getattr(self, "_lbl", None) is not None and self._lbl.text() == "":
                self._set_status("Prêt. Cliquez ‘Charger’.")
        except Exception:
            pass
