# plugins/mne_viewer2d_plugin.py
# -*- coding: utf-8 -*-
"""
MNE Viewer 2D — Montage-Free Plots (markers-ready)
Trace:
- Signal empilé
- PSD
- Spectrogramme (canal)
- Band-power
- Corrélation
- Cohérence A-B
+ Affichage de marqueurs verticaux optionnels (pin `markers`).
  Formats acceptés (relatifs à la fenêtre courante ou en échantillons):
    * (t, label)  ou (t, label, dur)
    * {"t":..., "label":..., "dur":..., "mode": "rel|sample"}
    * liste des éléments ci-dessus

→ Paramètres pliables (fermés par défaut) sans “zone grise” au repli.
"""
from typing import Optional, List, Tuple, Sequence
import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSpinBox, QDoubleSpinBox, QSizePolicy, QDialog,
    QVBoxLayout as QVBL, QLayout, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

import matplotlib
try:
    if 'qt' not in matplotlib.get_backend().lower():
        matplotlib.use('Qt5Agg', force=True)
except Exception:
    pass

matplotlib.rcParams.update({
    'font.size': 10,
    'axes.titlesize': 13,
    'axes.labelsize': 11,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'lines.linewidth': 1.6,
})

from matplotlib import pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavToolbar

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

try:
    from scipy import signal as _scisignal
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


# ---------------- CollapsibleSection (anti “rectangle gris”) ----------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parents.
    """
    collapsedChanged = pyqtSignal(bool)

    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # démarrage fermé
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
        self.set_collapsed(True)  # fermé sans espace au démarrage

    def content_layout(self):
        return self._content_layout

    def add_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)  # checked => ouvert
        self._apply(collapsed)
        self._update_title()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    def _on_toggled(self, checked: bool):
        collapsed = (not checked)
        self._apply(collapsed)
        self._update_title()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    def _apply(self, collapsed: bool):
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

    def _update_title(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        t = self._title[2:] if self._title[:2] in ("▼ ", "▶ ") else self._title
        self._btn.setText(arrow + t)

    def _reflow(self):
        self._content.updateGeometry(); self.updateGeometry()
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._bubble_adjust)

    def _bubble_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout(): w.layout().activate()
                w.adjustSize(); w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


# ------------- Utils DSP (numpy fallbacks) -------------
def _welch_numpy(x: np.ndarray, fs: float, nperseg: int = 1024, noverlap: int = 512):
    x = np.asarray(x, dtype=float)
    if not np.isfinite(fs) or fs <= 0: fs = 1.0
    nperseg = min(max(8, nperseg), x.size) if x.size > 0 else nperseg
    noverlap = min(max(0, noverlap), max(0, nperseg - 1))
    step = max(1, nperseg - noverlap)
    win = np.hanning(nperseg)
    K = 0; acc = None
    for start in range(0, x.size - nperseg + 1, step):
        seg = x[start:start + nperseg] * win
        spec = np.fft.rfft(seg)
        ps = (np.abs(spec) ** 2) / (np.sum(win ** 2) * fs)
        acc = ps if acc is None else acc + ps
        K += 1
    if K == 0:
        n = max(8, x.size if x.size else nperseg)
        f = np.fft.rfftfreq(n, d=1.0 / fs)
        w = np.hanning(n)
        sig = (x if x.size else np.zeros(n))
        psd = (np.abs(np.fft.rfft(sig[:n] * w)) ** 2) / (np.sum(w ** 2) * fs)
        return f, psd
    acc /= K
    f = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    return f, acc

def _coherence_numpy(x: np.ndarray, y: np.ndarray, fs: float, nperseg: int = 1024, noverlap: int = 512):
    f, Pxx = _welch_numpy(x, fs, nperseg, noverlap)
    _, Pyy = _welch_numpy(y, fs, nperseg, noverlap)
    if not np.isfinite(fs) or fs <= 0: fs = 1.0
    x = np.asarray(x, float); y = np.asarray(y, float)
    nperseg = min(nperseg, x.size, y.size)
    noverlap = min(noverlap, max(0, nperseg - 1))
    step = max(1, nperseg - noverlap)
    win = np.hanning(nperseg)
    K = 0; Pxy_acc = None
    for start in range(0, min(x.size, y.size) - nperseg + 1, step):
        sx = x[start:start + nperseg] * win
        sy = y[start:start + nperseg] * win
        Sx = np.fft.rfft(sx); Sy = np.fft.rfft(sy)
        Pxy = Sx * np.conj(Sy) / (np.sum(win ** 2) * fs)
        Pxy_acc = Pxy if Pxy_acc is None else Pxy_acc + Pxy
        K += 1
    Pxy_acc = np.zeros_like(Pxx, dtype=complex) if K == 0 else (Pxy_acc / K)
    Cxy = (np.abs(Pxy_acc) ** 2) / (Pxx * Pyy + 1e-15)
    return f, np.clip(Cxy.real, 0.0, 1.0)

def _band_edges():
    return [("delta", 1., 4.), ("theta", 4., 8.), ("alpha", 8., 13.), ("beta", 13., 30.)]


# ---------------- Plugin ----------------
class MNEViewer2D(BasePlugin):
    help = {
        'gotchas': ['High refresh rate can drop FPS; reduce update frequency or increase window size.',
               'If both raw and segment are connected, raw takes priority.',
               'Markers are only shown when the Marqueurs checkbox is enabled; max 20 markers are drawn to avoid clutter.',
               'Scipy is optional; if absent, numpy fallbacks are used for PSD/coherence (slower).',
               'MNE is optional; if absent, only segment (numpy array) input works, not MNE Raw objects.'],
        'inputs': {'ch_names': 'List[str] — channel labels (overrides names from raw/segment)',
                   'markers': 'list or dict — vertical markers in formats: (t, label), (t, label, dur), {"t":..., "label":..., "dur":..., "mode":"rel|sample"}, or a list thereof',
                   'raw': 'MNE Raw object — takes priority over segment if both connected',
                   'segment': '2D float [channels x samples] — EEG data array',
                   'sfreq': 'float (Hz) — sampling rate (used with segment, ignored for raw)',
                   'title': 'str — custom title displayed at the top'},
        'outputs': {'status': 'str — current viewer status message'},
        'parameters': [
            {'name': 'scale_uv', 'type': 'float', 'default': 50.0, 'unit': 'µV', 'desc': 'Vertical scale for signal plot'},
            {'name': 'speed', 'type': 'float', 'default': 1.0, 'desc': 'Scroll speed multiplier'},
            {'name': 'fullscreen', 'type': 'bool', 'default': False, 'desc': 'Show full screen'},
            {'name': 'max_ch_plot', 'type': 'int', 'default': 16, 'desc': 'Maximum number of channels displayed in traces and correlation matrix'},
            {'name': 'fmax', 'type': 'float', 'default': 60.0, 'desc': 'Maximum frequency in Hz for PSD, spectrogram, and coherence plots'},
            {'name': 'win_sec', 'type': 'float', 'default': 5.0, 'desc': 'Visible window duration in seconds for signal auto-scroll'},
            {'name': 'nperseg', 'type': 'int', 'default': 1024, 'desc': 'Welch segment length for PSD/coherence'},
            {'name': 'noverlap', 'type': 'int', 'default': 512, 'desc': 'Welch overlap for PSD/coherence'},
        ],
        'summary': 'MNE Viewer 2D — Montage-Free Plots (markers-ready)',
        'usage': 'Connect segment (or raw) plus sfreq and ch_names. Supports Signal, PSD, Spectrogram, Band-power, Correlation, and Coherence plots with optional vertical markers.'
    }

    name = "MNE Viewer 2D (montage-free)"
    language = "Python"
    category = "Output Nodes"

    def setup(self):
        # Entrées
        self.inputs["raw"] = BehaviorSubject(None)
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)
        self.inputs["sfreq"] = BehaviorSubject(None)
        self.inputs["title"] = BehaviorSubject(None)
        self.inputs["markers"] = BehaviorSubject(None)  # <-- NOUVEAU

        # Sorties
        self.outputs["status"] = BehaviorSubject("")

        # État
        self._raw = None
        self._seg = None
        self._names: List[str] = []
        self._sf: float = 0.0
        self._markers_in = None  # valeur brute reçue

        # UI état
        self._current_chan = 0
        self._chan_a = 0
        self._chan_b = 1
        self._max_ch_plot = 16
        self._fmax = 60.0
        self._auto_refresh = True
        self._auto_scroll = True
        self._win_sec = 5.0
        self._show_markers = True  # <-- NOUVEAU

        # Figure principale
        self._fig = plt.Figure(figsize=(7.6, 4.8), dpi=120)
        self._ax = self._fig.add_subplot(111)
        self._ax.set_position([0.12, 0.12, 0.72, 0.78])
        self._canvas = FigureCanvas(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setMinimumHeight(440)
        self._toolbar = None

        self._extra_axes: List = []
        self._current_plot: Optional[str] = None
        self._popups: List[QDialog] = []

        try:
            self.inputs["raw"].subscribe(lambda x: self._on_input_change("raw", x))
            self.inputs["segment"].subscribe(lambda x: self._on_input_change("segment", x))
        except Exception:
            pass

        self.widget = self.build_widget()

    # -- Abonnements: reset si upstream se déconnecte --
    def _on_input_change(self, key: str, value):
        try:
            if key == "raw":
                if value is None and self._seg is None:
                    self._raw = None
                    self._reset_display_blank("Aucune donnée (raw déconnecté)")
            elif key == "segment":
                if value is None and self._raw is None:
                    self._seg = None
                    self._reset_display_blank("Aucune donnée (segment déconnecté)")
        except Exception:
            pass

    # -------------- UI --------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._lbl_title = QLabel("MNE Viewer 2D — montage-free")
        self._lbl_title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(self._lbl_title)

        # ---------- Paramètres (pliables, fermés par défaut) ----------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Ligne de contrôles (choix canaux, Fmax, etc.)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Canal:"))
        self._cmb_chan = QComboBox(); self._cmb_chan.currentIndexChanged.connect(self._on_select_chan)
        row1.addWidget(self._cmb_chan)

        row1.addWidget(QLabel("A:"))
        self._cmb_a = QComboBox(); self._cmb_a.currentIndexChanged.connect(self._on_select_a)
        row1.addWidget(self._cmb_a)
        row1.addWidget(QLabel("B:"))
        self._cmb_b = QComboBox(); self._cmb_b.currentIndexChanged.connect(self._on_select_b)
        row1.addWidget(self._cmb_b)

        row1.addWidget(QLabel("Max ch/trace"))
        self._spin_max = QSpinBox(); self._spin_max.setRange(1, 64); self._spin_max.setValue(self._max_ch_plot)
        self._spin_max.valueChanged.connect(lambda v: setattr(self, "_max_ch_plot", int(v)))
        row1.addWidget(self._spin_max)

        row1.addWidget(QLabel("Fmax (Hz)"))
        self._spin_fmax = QDoubleSpinBox(); self._spin_fmax.setRange(1.0, 1000.0); self._spin_fmax.setDecimals(1)
        self._spin_fmax.setValue(self._fmax)
        self._spin_fmax.valueChanged.connect(lambda v: setattr(self, "_fmax", float(v)))
        row1.addWidget(self._spin_fmax)
        row1.addStretch(1)

        # Ligne de boutons d'action
        row2 = QHBoxLayout()
        b = QPushButton
        self._btn_signal = b("Signal"); self._btn_signal.clicked.connect(lambda: self._plot_wrapper('signal')) ; row2.addWidget(self._btn_signal)
        self._btn_psd = b("PSD"); self._btn_psd.clicked.connect(lambda: self._plot_wrapper('psd')); row2.addWidget(self._btn_psd)
        self._btn_spec = b("Spectrogramme"); self._btn_spec.clicked.connect(lambda: self._plot_wrapper('spec')); row2.addWidget(self._btn_spec)
        self._btn_bp = b("Band-power"); self._btn_bp.clicked.connect(lambda: self._plot_wrapper('bp')); row2.addWidget(self._btn_bp)
        self._btn_corr = b("Corrélation"); self._btn_corr.clicked.connect(lambda: self._plot_wrapper('corr')); row2.addWidget(self._btn_corr)
        self._btn_coh = b("Cohérence A-B"); self._btn_coh.clicked.connect(lambda: self._plot_wrapper('coh')); row2.addWidget(self._btn_coh)
        self._btn_big = b("Agrandir"); self._btn_big.clicked.connect(self._open_large_view); row2.addWidget(self._btn_big)
        row2.addStretch(1)

        # Options Welch
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("nperseg"))
        self._nper = QSpinBox(); self._nper.setRange(16, 32768); self._nper.setValue(1024)
        row3.addWidget(self._nper)
        row3.addWidget(QLabel("overlap"))
        self._nover = QSpinBox(); self._nover.setRange(0, 32760); self._nover.setValue(512)
        row3.addWidget(self._nover)
        self._chk_logpsd = QCheckBox("Log10 PSD"); self._chk_logpsd.setChecked(True)
        row3.addWidget(self._chk_logpsd)
        row3.addStretch(1)
        self._nper.valueChanged.connect(self._on_nper_changed)
        self._on_nper_changed(self._nper.value())

        # Live options
        row4 = QHBoxLayout()
        self._chk_autoref = QCheckBox("Auto-rafraîchir"); self._chk_autoref.setChecked(True)
        self._chk_autoref.toggled.connect(lambda s: setattr(self, "_auto_refresh", bool(s)))
        row4.addWidget(self._chk_autoref)
        self._chk_scroll = QCheckBox("Défilement auto"); self._chk_scroll.setChecked(True)
        self._chk_scroll.toggled.connect(lambda s: setattr(self, "_auto_scroll", bool(s)))
        row4.addWidget(self._chk_scroll)
        row4.addWidget(QLabel("Fenêtre (s)"))
        self._spin_win = QDoubleSpinBox(); self._spin_win.setRange(1.0, 120.0); self._spin_win.setDecimals(1)
        self._spin_win.setValue(self._win_sec)
        self._spin_win.valueChanged.connect(lambda v: setattr(self, "_win_sec", float(v)))
        row4.addWidget(self._spin_win)
        self._chk_marks = QCheckBox("Marqueurs"); self._chk_marks.setChecked(True)
        self._chk_marks.toggled.connect(lambda s: setattr(self, "_show_markers", bool(s)))
        row4.addWidget(self._chk_marks)
        row4.addStretch(1)

        # Injecter les 4 lignes dans la section pliable
        sec.content_layout().addLayout(row1)
        sec.content_layout().addLayout(row2)
        sec.content_layout().addLayout(row3)
        sec.content_layout().addLayout(row4)

        # ---------- Figure + Toolbar (toujours visibles) ----------
        root.addWidget(sec)
        root.addWidget(self._canvas, 1)
        self._toolbar = NavToolbar(self._canvas, w)
        root.addWidget(self._toolbar)

        self._lbl_status = QLabel(""); self._lbl_status.setStyleSheet("color:#666")
        root.addWidget(self._lbl_status)

        # Contraintes pour supprimer tout résidu d’espace
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        return w

    # -------------- Reactive --------------
    def execute(self, *args, **kwargs):
        try:
            inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)
            def _v(x):
                try: return x.value
                except Exception: return x

            raw = _v(inps.get("raw"))
            seg = _v(inps.get("segment"))
            names = _v(inps.get("ch_names"))
            sf = _v(inps.get("sfreq"))
            title = _v(inps.get("title"))
            markers = _v(inps.get("markers"))  # <-- NOUVEAU

            if title and getattr(self, "_lbl_title", None) is not None:
                self._lbl_title.setText(str(title))

            if markers is not None:
                self._markers_in = markers  # on stocke tel quel

            changed = False

            if raw is None and seg is None:
                if self._raw is not None or self._seg is not None:
                    self._raw = None; self._seg = None
                    self._reset_display_blank("Aucune donnée (déconnecté)")
                return

            if raw is not None and raw is not self._raw:
                self._raw = raw; self._seg = None; changed = True
                try: self._sf = float(raw.info.get('sfreq', 0.0) or 0.0)
                except Exception: self._sf = 0.0
                try: self._names = list(raw.ch_names)
                except Exception: self._names = []

            if seg is not None and self._raw is None:
                arr = np.asarray(seg)
                if arr.ndim == 1: arr = arr.reshape(1, -1)
                self._seg = arr
                try: self._sf = float(sf or self._sf or 0.0)
                except Exception: pass
                try: self._names = list(names or [f"Ch{i+1}" for i in range(arr.shape[0])])
                except Exception: pass
                changed = True

            if changed:
                self._refresh_channel_boxes()
                self._set_status(self._summary())
                self._plot_wrapper(self._current_plot or 'signal')
            elif self._auto_refresh and self._current_plot:
                self._plot_wrapper(self._current_plot)
        except Exception as e:
            self._set_status(f"Erreur execute: {e}")

    # -------------- Data access --------------
    def _get_data(self) -> Tuple[np.ndarray, float, List[str]]:
        if self._raw is not None and HAVE_MNE:
            try:
                with mne.use_log_level("ERROR"):
                    data = self._raw.get_data()
                fs = float(self._sf or self._raw.info.get('sfreq', 0.0) or 0.0)
                names = list(self._names or self._raw.ch_names) or [f"Ch{i+1}" for i in range(data.shape[0])]
                return data, fs, names
            except Exception:
                pass
        if self._seg is not None:
            data = np.asarray(self._seg)
            fs = float(self._sf or 0.0)
            names = list(self._names or [f"Ch{i+1}" for i in range(data.shape[0])])
            return data, fs, names
        return np.zeros((1, 1), float), 0.0, ["Ch1"]

    # -------------- Helpers --------------
    def _reset_display_blank(self, msg: str = ""):
        fig = self._fig
        self._purge_extras(fig)
        self._ax.clear(); self._ax.set_axis_off()
        if msg:
            self._ax.text(0.5, 0.5, msg, transform=self._ax.transAxes, ha='center', va='center')
            self._set_status(msg)
        fig.canvas.draw_idle()

    def _purge_extras(self, fig):
        for a in getattr(self, "_extra_axes", []):
            try: fig.delaxes(a)
            except Exception: pass
        self._extra_axes = []
        for a in list(fig.axes):
            if a is not self._ax:
                try: fig.delaxes(a)
                except Exception: pass
        self._ax.set_position([0.12, 0.12, 0.72, 0.78])

    def _add_colorbar(self, fig, ax, im, label: str):
        cax = fig.add_axes([0.86, 0.12, 0.03, 0.78])
        cb = fig.colorbar(im, cax=cax); cb.set_label(label)
        self._extra_axes.append(cax)
        return cb

    def _refresh_channel_boxes(self):
        _, _, names = self._get_data()
        if not names: names = ["Ch1"]
        def _fill(box: QComboBox):
            box.blockSignals(True); box.clear(); box.addItems(names); box.blockSignals(False)
        _fill(self._cmb_chan); _fill(self._cmb_a); _fill(self._cmb_b)
        self._cmb_chan.setCurrentIndex(min(self._current_chan, len(names)-1))
        self._cmb_a.setCurrentIndex(min(self._chan_a, len(names)-1))
        self._cmb_b.setCurrentIndex(min(self._chan_b, len(names)-1))
        if len(names) >= 2 and self._cmb_a.currentIndex() == self._cmb_b.currentIndex():
            new_b = (self._cmb_a.currentIndex() + 1) % len(names)
            self._cmb_b.setCurrentIndex(new_b); self._chan_b = new_b
        try:
            self._btn_coh.setEnabled(len(names) >= 2)
            self._btn_corr.setEnabled(len(names) >= 2)
        except Exception:
            pass

    def _on_nper_changed(self, v: int):
        v = int(v)
        if v < 2:
            v = 2
            self._nper.setValue(v)
        self._nover.setMaximum(max(0, v-1))
        if int(self._nover.value()) >= v:
            self._nover.setValue(max(0, v//2))

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if hasattr(self, "_lbl_status") and self._lbl_status is not None:
            self._lbl_status.setText(msg)
        else:
            print(f"[MNEViewer2D] {msg}")

    def _summary(self) -> str:
        data, fs, _ = self._get_data()
        n, T = data.shape
        dur = (T / fs) if fs > 0 else T
        return f"Canaux: {n} | sfreq: {fs:.2f} Hz | durée: {dur:.1f} {'s' if fs>0 else 'samples'}"

    # --------- Markers parsing & drawing ---------
    def _normalize_markers(self, markers, fs: float, T_sec: float):
        """Retourne une liste [(onset_s, label, dur_s)] bornée à [0, T_sec]."""
        out = []
        if markers is None:
            return out

        def _add(t, lab, dur=None, mode=None):
            m = (mode or "rel").lower()
            if m == "sample":
                t = float(t) / (fs if fs > 0 else 1.0)
            else:  # 'rel' par défaut
                t = float(t)
            d = 0.0 if dur is None else float(dur)
            if 0.0 <= t <= max(T_sec, 1e-12):
                out.append((t, str(lab), d))

        if isinstance(markers, dict):
            _add(markers.get("t", markers.get("time", 0.0)), markers.get("label","MARK"),
                 markers.get("dur", 0.0), markers.get("mode","rel"))
        elif isinstance(markers, (tuple, list)) and markers and isinstance(markers[0], (tuple, list, dict)):
            for it in markers:
                if isinstance(it, dict):
                    _add(it.get("t", it.get("time", 0.0)), it.get("label","MARK"),
                         it.get("dur", 0.0), it.get("mode","rel"))
                else:
                    # (t, label) / (t, label, dur[, mode])
                    t = it[0]; lab = it[1]
                    dur = it[2] if len(it) > 2 else 0.0
                    mode = it[3] if len(it) > 3 else "rel"
                    _add(t, lab, dur, mode)
        elif isinstance(markers, (tuple, list)) and len(markers) >= 2:
            _add(markers[0], markers[1], markers[2] if len(markers) > 2 else 0.0,
                 markers[3] if len(markers) > 3 else "rel")
        return out

    def _draw_markers(self, ax, fs: float, T_samples: int):
        """Trace les marqueurs sur l'axe courant (si activés)."""
        if not self._show_markers:
            return
        T_sec = (T_samples / fs) if fs > 0 else float(T_samples)
        marks = self._normalize_markers(self._markers_in, fs, T_sec)
        if not marks:
            return
        ymin, ymax = ax.get_ylim()
        ytxt = ymax
        limit = 20  # pour ne pas surcharger
        for k, (t, lab, _) in enumerate(marks[:limit]):
            ax.axvline(t, ls='--', lw=1, alpha=0.6, color='k')
            try:
                ax.text(t, ytxt, str(lab), rotation=90, va='top', ha='center', fontsize=8, alpha=0.7)
            except Exception:
                pass

    # -------------- Plot routing --------------
    def _plot_wrapper(self, kind: str):
        self._current_plot = kind
        fig = self._fig; ax = self._ax
        self._purge_extras(fig)
        ax.clear(); ax.grid(True, alpha=0.25)
        if kind == 'signal':
            self._draw_signal(ax)
        elif kind == 'psd':
            self._draw_psd(ax)
        elif kind == 'spec':
            self._draw_spectrogram(ax)
        elif kind == 'bp':
            self._draw_bandpower(ax)
        elif kind == 'corr':
            self._draw_corr(ax)
        elif kind == 'coh':
            self._draw_coherence(ax)
        fig.canvas.draw_idle()

    def _open_large_view(self):
        if not self._current_plot:
            self._set_status("Aucun graphe à agrandir"); return
        dlg = QDialog(getattr(self, 'widget', None))
        dlg.setWindowTitle(f"Agrandir — {self._current_plot}")
        v = QVBL(dlg)
        fig = plt.Figure(figsize=(10.5, 6.6), dpi=140)
        ax = fig.add_subplot(111)
        ax.set_position([0.10, 0.12, 0.74, 0.78])
        canvas = FigureCanvas(fig); v.addWidget(canvas)
        toolbar = NavToolbar(canvas, dlg); v.addWidget(toolbar)

        try:
            for a in list(fig.axes):
                if a is not ax: fig.delaxes(a)
            if self._current_plot == 'signal':
                self._draw_signal(ax)
            elif self._current_plot == 'psd':
                self._draw_psd(ax)
            elif self._current_plot == 'spec':
                self._draw_spectrogram(ax)
            elif self._current_plot == 'bp':
                self._draw_bandpower(ax)
            elif self._current_plot == 'corr':
                self._draw_corr(ax)
            elif self._current_plot == 'coh':
                self._draw_coherence(ax)
            canvas.draw(); dlg.resize(1120, 760); dlg.show()
            self._popups.append(dlg)
        except Exception as e:
            self._set_status(f"Erreur agrandissement: {e}")

    # -------------- Draw functions --------------
    def _draw_signal(self, ax):
        data, fs, names = self._get_data()
        n, T = data.shape
        k = min(n, int(self._max_ch_plot))
        idxs = np.arange(k)
        x = data[idxs]
        med = np.median(x, axis=1, keepdims=True)
        std = np.std(x, axis=1, keepdims=True) + 1e-12
        x = (x - med) / std
        offs = np.arange(k)[::-1].reshape(-1, 1) * 4.2
        x = x + offs
        if fs > 0:
            t = np.arange(T) / fs
            ax.plot(t, x.T)
            ax.set_xlabel("Temps (s)")
            if getattr(self, "_auto_scroll", False):
                end = float(t[-1]); start = max(float(t[0]), end - float(getattr(self, "_win_sec", 5.0)))
                ax.set_xlim(start, end)
            else:
                ax.set_xlim(t[0], t[-1])
            self._draw_markers(ax, fs, T)
        else:
            ax.plot(x.T); ax.set_xlabel("Samples")
            self._draw_markers(ax, 1.0, T)
        ax.set_yticks(offs[:, 0])
        ax.set_yticklabels([names[i] for i in idxs])
        ax.set_title("Signal empilé")

    def _draw_psd(self, ax):
        data, fs, names = self._get_data()
        nper_req = int(self._nper.value()); nover_req = int(self._nover.value())
        to_plot = min(data.shape[0], int(self._max_ch_plot))
        freqs = None; psd_all = []
        for i in range(to_plot):
            x = np.asarray(data[i]).ravel()
            if x.size < 4: continue
            nper = min(max(16, nper_req), x.size)
            nover = min(max(0, nover_req), max(0, nper - 1))
            if HAVE_SCIPY: f, Pxx = _scisignal.welch(x, fs=fs if fs > 0 else 1.0, nperseg=nper, noverlap=nover)
            else:          f, Pxx = _welch_numpy(x, fs=fs if fs > 0 else 1.0, nperseg=nper, noverlap=nover)
            if fs > 0:
                m = f <= float(self._fmax); f = f[m]; Pxx = Pxx[m]
            psd_all.append(Pxx)
            if freqs is None: freqs = f
        if not psd_all or freqs is None:
            ax.text(0.5,0.5,'Segment trop court pour PSD',ha='center',va='center', transform=ax.transAxes)
            ax.set_axis_off(); return
        psd = np.vstack(psd_all)
        med = np.median(psd, axis=0)
        p25 = np.percentile(psd, 25, axis=0)
        p75 = np.percentile(psd, 75, axis=0)
        if self._chk_logpsd.isChecked():
            med = 10*np.log10(med + 1e-20); p25 = 10*np.log10(p25 + 1e-20); p75 = 10*np.log10(p75 + 1e-20)
            ax.set_ylabel("dB/Hz")
        else:
            ax.set_ylabel("PSD")
        ax.plot(freqs, med, lw=2.2, label="médiane")
        ax.fill_between(freqs, p25, p75, alpha=0.28, label="IQR")
        ax.set_title("PSD (Welch) — médiane ± IQR")
        ax.set_xlabel("Fréquence (Hz)" if fs > 0 else "Bin")
        ax.legend(frameon=False, loc='upper right')
        if fs > 0: ax.set_xlim(freqs[0], freqs[-1])

    def _draw_spectrogram(self, ax):
        fig = self._fig
        data, fs, names = self._get_data()
        ch = int(self._current_chan) if 0 <= self._current_chan < data.shape[0] else 0
        x = np.asarray(data[ch]).ravel()
        if x.size < 4:
            ax.text(0.5,0.5,'Segment trop court pour spectrogramme',ha='center',va='center', transform=ax.transAxes)
            ax.set_axis_off(); return
        nper_req = int(self._nper.value()); nover_req = int(self._nover.value())
        nper = min(max(16, nper_req), x.size)
        nover = min(max(0, nover_req), max(0, nper - 1))
        if HAVE_SCIPY:
            f, t, Sxx = _scisignal.spectrogram(x, fs=fs if fs > 0 else 1.0, nperseg=nper, noverlap=nover)
        else:
            Pxx, f, t, im_ = ax.specgram(x, NFFT=nper, Fs=fs if fs > 0 else 1.0, noverlap=nover)
            try: im_.remove()
            except Exception: pass
            Sxx = Pxx
        if fs > 0:
            m = f <= float(self._fmax); f = f[m]; Sxx = Sxx[m, :]
        Z = 10*np.log10(Sxx + 1e-20)
        if Z.shape[0] < 2 or Z.shape[1] < 2:
            Zp = Z
            if Zp.shape[0] < 2: Zp = np.vstack([Zp, Zp])
            if Zp.shape[1] < 2: Zp = np.hstack([Zp, Zp[:, -1:]])
            im = ax.imshow(Zp, origin='lower', aspect='auto',
                           extent=[t[0] if t.size else 0.0, (t[-1] if t.size else (nper/(fs if fs>0 else 1.0))),
                                   f[0] if f.size else 0.0, (f[-1] if f.size else 1.0)],
                           interpolation='nearest')
        else:
            im = ax.pcolormesh(t if fs > 0 else np.arange(Z.shape[1]), f, Z, shading='auto')
        ax.set_aspect('auto')
        ax.set_ylabel("Freq (Hz)" if fs > 0 else "Bin"); ax.set_xlabel("Temps (s)" if fs > 0 else "Fenêtre")
        ax.set_title(f"Spectrogramme — {names[ch]}")
        self._add_colorbar(fig, ax, im, "dB")
        self._draw_markers(ax, fs if fs > 0 else 1.0, len(x))

    def _draw_bandpower(self, ax):
        data, fs, names = self._get_data()
        if fs <= 0:
            ax.text(0.5, 0.5, "sfreq inconnu → band-power indisponible", ha='center', va='center', transform=ax.transAxes); ax.set_axis_off(); return
        bands = _band_edges(); powers = []
        for i in range(min(data.shape[0], self._max_ch_plot)):
            x = np.asarray(data[i]).ravel()
            if x.size < 4: continue
            nper = min(max(16, int(self._nper.value())), x.size)
            nover = min(max(0, int(self._nover.value())), max(0, nper - 1))
            if HAVE_SCIPY: f, Pxx = _scisignal.welch(x, fs=fs, nperseg=nper, noverlap=nover)
            else:          f, Pxx = _welch_numpy(x, fs, nperseg=nper, noverlap=nover)
            m = (f <= float(self._fmax)) if fs > 0 else slice(None)
            f = f[m]; Pxx = Pxx[m]
            bp = []
            for _, f1, f2 in bands:
                mm = (f >= f1) & (f < f2)
                bp.append(np.trapz(Pxx[mm], f[mm]) if np.any(mm) else 0.0)
            powers.append(bp)
        if not powers:
            ax.text(0.5,0.5,'Segment trop court pour band-power',ha='center',va='center', transform=ax.transAxes); ax.set_axis_off(); return
        vals = np.asarray(powers).mean(axis=0)
        labels = [b[0] for b in bands]
        ax.bar(labels, vals)
        ax.set_title("Band-power moyenne (Welch)")
        ax.set_ylabel("Puissance (a.u.)")

    def _draw_corr(self, ax):
        fig = self._fig
        data, fs, names = self._get_data()
        k = min(data.shape[0], self._max_ch_plot)
        if k < 2 or data.shape[1] < 2:
            ax.text(0.5,0.5,'Trop peu de données pour corrélation',ha='center',va='center', transform=ax.transAxes)
            ax.set_axis_off(); return
        x = data[:k]
        x = (x - x.mean(axis=1, keepdims=True)) / (x.std(axis=1, keepdims=True) + 1e-12)
        C = np.corrcoef(x)
        C = np.nan_to_num(C, nan=0.0, posinf=0.0, neginf=0.0)
        np.fill_diagonal(C, 1.0)
        im = ax.imshow(C, vmin=-1, vmax=1, cmap='coolwarm', origin='lower', interpolation='nearest', aspect='auto')
        ax.set_title("Corrélation inter-canaux")
        if k <= 32:
            ax.set_xticks(np.arange(k)); ax.set_xticklabels(names[:k], rotation=90, fontsize=8)
            ax.set_yticks(np.arange(k)); ax.set_yticklabels(names[:k], fontsize=8)
        self._add_colorbar(fig, ax, im, "ρ")

    def _draw_coherence(self, ax):
        data, fs, names = self._get_data()
        a = int(self._chan_a) if 0 <= self._chan_a < data.shape[0] else 0
        b = int(self._chan_b) if 0 <= self._chan_b < data.shape[0] else min(1, data.shape[0]-1)
        if data.shape[0] < 2:
            ax.text(0.5, 0.5, "Au moins 2 canaux requis", ha='center', va='center', transform=ax.transAxes); ax.set_axis_off(); return
        if a == b:
            ax.text(0.5, 0.5, "Choisir deux canaux distincts (A ≠ B)", ha='center', va='center', transform=ax.transAxes); ax.set_axis_off(); return
        x = np.asarray(data[a]).ravel(); y = np.asarray(data[b]).ravel()
        L = min(x.size, y.size)
        if L < 4:
            ax.text(0.5,0.5,'Segment trop court pour cohérence',ha='center',va='center', transform=ax.transAxes); ax.set_axis_off(); return
        nper = min(max(16, int(self._nper.value())), L)
        nover = min(max(0, int(self._nover.value())), max(0, nper - 1))
        if HAVE_SCIPY:
            f, Cxy = _scisignal.coherence(x, y, fs=fs if fs > 0 else 1.0, nperseg=nper, noverlap=nover)
        else:
            f, Cxy = _coherence_numpy(x, y, fs if fs > 0 else 1.0, nperseg=nper, noverlap=nover)
        if fs > 0:
            m = f <= float(self._fmax); f = f[m]; Cxy = Cxy[m]
        Cxy = np.nan_to_num(Cxy, nan=0.0, posinf=0.0, neginf=0.0)
        if f.size == 0:
            ax.text(0.5,0.5,'Aucune fréquence dans la fenêtre Fmax',ha='center',va='center', transform=ax.transAxes); ax.set_axis_off(); return
        if f.size == 1:
            ax.plot(f, Cxy, marker='o', linestyle='None')
            dx = max(1.0, float(f[0])*0.1); ax.set_xlim(float(f[0])-dx, float(f[0])+dx)
        else:
            ax.plot(f, Cxy, lw=2.0)
        ax.set_ylim(0, 1)
        ax.set_xlabel("Fréquence (Hz)" if fs > 0 else "Bin")
        ax.set_ylabel("Cohérence")
        ax.set_title(f"Cohérence {names[a]} – {names[b]}")

    # -------------- Slots --------------
    def _on_select_chan(self, i: int):
        self._current_chan = int(i)
        if self._current_plot == 'spec':
            self._plot_wrapper('spec')
    def _on_select_a(self, i: int):
        self._chan_a = int(i)
        if self._current_plot == 'coh':
            self._plot_wrapper('coh')
    def _on_select_b(self, i: int):
        self._chan_b = int(i)
        if self._current_plot == 'coh':
            self._plot_wrapper('coh')
