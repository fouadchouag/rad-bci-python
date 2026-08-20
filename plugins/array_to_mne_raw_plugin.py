# -*- coding: utf-8 -*-
"""
Array → MNE Raw (Adapter) — fixed v3 (collapsible)

- Idem v2 (coercions + robustesse sfreq)
- UI "Paramètres" repliable/clicable (QToolButton) compatible avec NodeItem.
"""
from typing import Optional
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QToolButton, QSizePolicy
)
from PyQt5.QtCore import Qt
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


# --- mini section repliable, autonome (aucune dépendance externe) ----------
class _CollapsibleSection(QWidget):
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.RightArrow)
        self._btn.setChecked(not collapsed)

        self._wrap = QWidget()
        self._wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0)
        self._wrap_l.setSpacing(6)

        self._content = content or QWidget()
        self._wrap_l.addWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._on_toggled(self._btn.isChecked())

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        w = self
        while w is not None:
            if w.layout():
                w.layout().invalidate()
            w.adjustSize()
            w.updateGeometry()
            w = w.parentWidget()


class ArrayToMNERaw(BasePlugin):
    help = {
        'gotchas': ['MNE required (pip install mne).',
               'Data must be numeric (2D/3D array or list of chunks).',
               'Unit scaling: input values are multiplied by the selected unit '
               '(default µV → V). Set to V if data is already in Volts.',
               'NaN/Inf values in data are replaced with 0.',
               'Montage is applied only for channels recognized by the standard template.',
               'Auto mode reconverts on every input change.'],
        'inputs': {
            'data': '2D/3D array or list of chunks [ch x samples]',
            'sfreq': 'float — sampling rate (Hz)',
            'ch_names': 'list[str] — channel names',
            'title': 'str — optional title (unused)',
        },
        'outputs': {
            'raw': 'mne.io.RawArray — constructed Raw object',
            'status': 'str — conversion status message',
        },
        'parameters': [
            {'name': 'units', 'type': 'str', 'default': 'µV', 'desc': 'Input data units',
             'enum': ['V', 'µV', 'mV', 'nV']},
            {'name': 'montage', 'type': 'str', 'default': 'standard_1020',
             'desc': 'Standard montage to apply',
             'enum': ['(none)', 'standard_1020', 'standard_1005', 'biosemi64', 'easycap-M1']},
            {'name': 'auto', 'type': 'bool', 'default': True,
             'desc': 'Automatically reconvert on input change'},
        ],
        'summary': 'Convert numeric arrays (segment/samples) to an MNE Raw object.',
        'usage': 'Provide data, sfreq, and ch_names; outputs an MNE Raw for downstream MNE nodes.'
    }

    # 🔹 Familles explicites pour la validation des connexions
    PIN_FAMILY_HINTS = {
        "data": "segment_or_raw",  # ← accepte "segment" (mat 2D) OU "raw" en entrée
        "sfreq": "sfreq",
        "ch_names": "ch_names",
        "raw": "raw",
        "status": "status",
    }

    name = "Array → MNE Raw"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        # Inputs
        self.inputs["data"] = BehaviorSubject(None)      # ndarray 2D/3D OU liste de chunks
        self.inputs["sfreq"] = BehaviorSubject(None)     # float (peut être numpy scalar)
        self.inputs["ch_names"] = BehaviorSubject(None)  # list[str]
        self.inputs["title"] = BehaviorSubject(None)
        # Outputs
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        # UI/state
        self._widget: Optional[QWidget] = None
        self._units = "µV"
        self._montage = "standard_1020"
        self._auto = True
        self._latest = (None, None, None)

    def build_widget(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        title = QLabel("Array → MNE Raw (Adapter)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        outer.addWidget(title)

        if not HAVE_MNE:
            warn = QLabel("MNE n'est pas installé. `pip install mne`.")
            warn.setStyleSheet("color:#b00")
            warn.setWordWrap(True)
            outer.addWidget(warn)

        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(6)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Units"))
        self._cmb_units = QComboBox()
        self._cmb_units.addItems(["V", "µV", "mV", "nV"])
        self._cmb_units.setCurrentText(self._units)
        self._cmb_units.currentTextChanged.connect(self._on_units)
        row1.addWidget(self._cmb_units)

        row1.addWidget(QLabel("Montage"))
        self._cmb_mont = QComboBox()
        self._cmb_mont.addItems(["(none)", "standard_1020", "standard_1005", "biosemi64", "easycap-M1"])
        self._cmb_mont.setCurrentText(self._montage)
        self._cmb_mont.currentTextChanged.connect(self._on_montage)
        row1.addWidget(self._cmb_mont, 1)

        self._chk_auto = QCheckBox("Auto")
        self._chk_auto.setChecked(self._auto)
        self._chk_auto.toggled.connect(self._on_auto)
        row1.addWidget(self._chk_auto)
        pv.addLayout(row1)

        row2 = QHBoxLayout()
        self._btn = QPushButton("Convertir → Raw")
        self._btn.clicked.connect(self._convert)
        row2.addWidget(self._btn)
        pv.addLayout(row2)

        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666")
        pv.addWidget(self._lbl)

        outer.addWidget(_CollapsibleSection("Paramètres", content=panel, collapsed=True))

        self._widget = w
        return w

    # ---------------- utils ----------------
    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def _on_units(self, u: str):
        self._units = u
        if self._auto:
            self._convert()

    def _on_montage(self, m: str):
        self._montage = m
        if self._auto:
            self._convert()

    def _on_auto(self, on: bool):
        self._auto = bool(on)

    def _as_float(self, x):
        try:
            return float(np.asarray(x).ravel()[0])
        except Exception:
            return float(x)

    # ------------- reactive entry -------------
    def execute(self, *call_args, **call_kwargs):
        try:
            inps = call_kwargs or (call_args[0] if call_args and isinstance(call_args[0], dict) else self.inputs)

            def _v(x):
                try:
                    return x.value
                except Exception:
                    return x

            def first_non_none(*keys):
                for k in keys:
                    if k in inps:
                        val = _v(inps.get(k))
                        if val is not None:
                            return val
                return None

            data = first_non_none("data", "samples", "chunk")
            sfreq = first_non_none("sfreq", "fs", "sampling_rate")
            ch_names = first_non_none("ch_names", "labels", "names")
            self._latest = (data, sfreq, ch_names)
            if self._auto:
                self._convert()
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    # -------- coercion helpers --------
    def _coerce_2d(self, data, n_ch_hint: Optional[int]):
        """Convertit tout format courant en matrice 2D (ch, n)."""
        if isinstance(data, np.ndarray) and data.ndim == 2 and data.dtype != object:
            return data.astype(float, copy=False)

        def to_array(x):
            try:
                a = np.asarray(x)
                if a.dtype == object:
                    raise ValueError
                return a
            except Exception:
                return np.array(x, dtype=float)

        if isinstance(data, np.ndarray):
            if data.ndim == 3:
                axes = list(data.shape)
                if n_ch_hint is not None and n_ch_hint in axes:
                    ch_ax = axes.index(n_ch_hint)
                else:
                    ch_ax = int(np.argmin(axes))
                X = np.moveaxis(data, ch_ax, 0).reshape((data.shape[ch_ax], -1))
                return X.astype(float)
            elif data.ndim == 1:
                items = [to_array(it) for it in list(data)]
                if all(a.ndim == 1 for a in items):
                    lens = [a.shape[0] for a in items]
                    if n_ch_hint is not None and len(items) == n_ch_hint:
                        L = int(np.min(lens))
                        X = np.stack([a[:L] for a in items], axis=0)
                    else:
                        n_ch = min(lens)
                        X = np.stack([a[:n_ch] for a in items], axis=0).T
                    return X.astype(float)
                if all(a.ndim == 2 for a in items):
                    chunks = []
                    for a in items:
                        if n_ch_hint is not None:
                            if a.shape[0] == n_ch_hint:
                                chunks.append(a)
                            elif a.shape[1] == n_ch_hint:
                                chunks.append(a.T)
                            else:
                                chunks.append(a if a.shape[0] < a.shape[1] else a.T)
                        else:
                            chunks.append(a if a.shape[0] < a.shape[1] else a.T)
                    L = int(np.min([c.shape[1] for c in chunks]))
                    X = np.concatenate([c[:, :L] for c in chunks], axis=1)
                    return X.astype(float)
            data = list(data)

        if isinstance(data, (list, tuple)):
            arrs = []
            for it in data:
                try:
                    a = to_array(it)
                except Exception:
                    continue
                arrs.append(a)
            if not arrs:
                raise ValueError("data list vide/non-numérique")
            nd = max(a.ndim for a in arrs)
            if nd == 1:
                lens = [a.shape[0] for a in arrs]
                if n_ch_hint is not None and len(arrs) == n_ch_hint:
                    L = int(np.min(lens))
                    X = np.stack([a[:L] for a in arrs], axis=0)
                else:
                    n_ch = int(np.min(lens))
                    X = np.stack([a[:n_ch] for a in arrs], axis=0).T
                return X.astype(float)
            else:
                chunks = []
                for a in arrs:
                    if a.ndim == 1:
                        a = a[None, :]
                    if n_ch_hint is not None:
                        if a.shape[0] == n_ch_hint:
                            chunks.append(a)
                        elif a.shape[1] == n_ch_hint:
                            chunks.append(a.T)
                        else:
                            chunks.append(a if a.shape[0] < a.shape[1] else a.T)
                    else:
                        chunks.append(a if a.shape[0] < a.shape[1] else a.T)
                L = int(np.min([c.shape[1] for c in chunks]))
                X = np.concatenate([c[:, :L] for c in chunks], axis=1)
                return X.astype(float)

        raise ValueError("Impossible de convertir en matrice 2D (ch×n)")

    def _convert(self):
        if not HAVE_MNE:
            self._set_status("MNE non dispo")
            return
        data, sfreq, ch_names = self._latest
        try:
            if data is None or sfreq is None or ch_names is None:
                self._set_status("Entrées incomplètes (data/sfreq/ch_names)")
                return

            n_ch_hint = int(len(ch_names)) if ch_names is not None else None
            X = self._coerce_2d(data, n_ch_hint)
            if n_ch_hint is not None:
                if X.shape[0] == n_ch_hint:
                    pass
                elif X.shape[1] == n_ch_hint:
                    X = X.T
                else:
                    X = X if X.shape[0] <= X.shape[1] else X.T
            else:
                X = X if X.shape[0] <= X.shape[1] else X.T

            ch_names = list(map(str, ch_names))
            if len(ch_names) != X.shape[0]:
                if len(ch_names) > X.shape[0]:
                    ch_names = ch_names[:X.shape[0]]
                else:
                    ch_names += [f"Ch{i+1}" for i in range(len(ch_names), X.shape[0])]

            # unités → Volts
            scale = {"V": 1.0, "µV": 1e-6, "mV": 1e-3, "nV": 1e-9}.get(self._units, 1e-6)
            X = X.astype(float) * scale
            X[~np.isfinite(X)] = 0.0

            sf = self._as_float(sfreq)
            info = mne.create_info(ch_names=ch_names, sfreq=sf, ch_types='eeg')
            raw = mne.io.RawArray(X, info)

            mont_name = self._montage
            if mont_name and mont_name != "(none)":
                try:
                    mont = mne.channels.make_standard_montage(mont_name)
                    mpos = mont.get_positions()['ch_pos']
                    sub = {nm: mpos[nm] for nm in raw.ch_names if nm in mpos}
                    if sub:
                        dig = mne.channels.make_dig_montage(ch_pos=sub, coord_frame='head')
                        try:
                            raw.set_montage(dig, match_case=False, on_missing='ignore')
                        except TypeError:
                            raw.set_montage(dig, match_case=False)
                except Exception:
                    pass

            self.outputs["raw"].on_next(raw)
            dur = raw.n_times / raw.info['sfreq']
            self._set_status(
                f"Raw prêt: {len(raw.ch_names)}ch @ {raw.info['sfreq']:.2f}Hz, {dur:.2f}s, "
                f"montage={mont_name}, shape={X.shape}"
            )
        except Exception as e:
            self._set_status(f"Erreur conversion: {e}")
