# plugins/eeg_raw_filter_plugin.py
# Filtre "offline" sur l'objet complet mne.io.Raw (FIR/IIR zero-phase).
# Usage : EEGReader(raw) → EEGRawFilter(raw, info, sfreq, ch_names) → EEGLiveDisplay (From Raw = ON)
# Ajouts :
#  - sorties sfreq & ch_names
#  - émission des métadonnées à l'arrivée d'un Raw (même avant filtrage)
#  - émission des métadonnées après filtrage

from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QCheckBox, QPushButton, QComboBox
)
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from core.node_base import BasePlugin


class _FilterWorker(QObject):
    finished = pyqtSignal(object, dict)   # (raw_filt, info_msg)
    failed   = pyqtSignal(str)

    def __init__(self, raw, params):
        super().__init__()
        self.raw = raw
        self.params = params

    def run(self):
        try:
            import mne  # requis si Raw existe
            raw_in = self.raw
            if raw_in is None:
                self.failed.emit("Aucun Raw en entrée.")
                return

            p = self.params
            in_place   = p.get("in_place", False)
            method     = p.get("method", "fir")      # 'fir' ou 'iir'
            phase      = p.get("phase", "zero")      # 'zero' ou 'zero-double'
            hp         = p.get("hp", None)
            lp         = p.get("lp", None)
            do_hp      = p.get("enable_hp", True)
            do_lp      = p.get("enable_lp", True)
            do_notch   = p.get("enable_notch", False)
            notch_list = p.get("notch_freqs", [])
            picks_mode = p.get("picks", "all")       # 'all' ou 'eeg'

            raw = raw_in if in_place else raw_in.copy()

            # Choix des canaux à filtrer
            picks = None
            if picks_mode == "eeg":
                picks = mne.pick_types(
                    raw.info, eeg=True, meg=False, stim=False,
                    eog=False, ecg=False, seeg=True, misc=False
                )

            # Notch (secteur, harmoniques)
            if do_notch and notch_list:
                raw.notch_filter(freqs=notch_list, picks=picks, method=method, phase=phase, verbose=False)

            # HP/LP (band-pass implicite)
            l_freq = float(hp) if (do_hp and hp and hp > 0) else None
            h_freq = float(lp) if (do_lp and lp and lp > 0) else None
            if l_freq is not None or h_freq is not None:
                raw.filter(l_freq=l_freq, h_freq=h_freq, picks=picks,
                           method=method, phase=phase, verbose=False)

            info_msg = {
                "sfreq": float(raw.info.get("sfreq", 0.0)),
                "ch_names": list(raw.ch_names),
                "note": f"filtered (hp={l_freq}, lp={h_freq}, notch={notch_list}, method={method}, phase={phase}, picks={picks_mode})",
            }
            self.finished.emit(raw, info_msg)
        except Exception as e:
            self.failed.emit(str(e))


class EEGRawFilterPlugin(BasePlugin):
    name = "EEGRawFilter"
    category = "Processing Nodes"

    def setup(self):
        # Entrées / Sorties
        self.inputs = {"raw": BehaviorSubject(None)}
        self.outputs = {
            "raw": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),      # <-- ajouté
            "ch_names": BehaviorSubject(None),   # <-- ajouté
        }

        # Paramètres
        self._enable_hp = True
        self._hp = 1.0
        self._enable_lp = True
        self._lp = 40.0
        self._enable_notch = False
        self._notch_str = "50, 100"   # ex : 50, 100 (harmoniques)
        self._method = "fir"          # 'fir' ou 'iir'
        self._phase = "zero"          # 'zero' ou 'zero-double'
        self._picks_mode = "all"      # 'all' ou 'eeg'
        self._in_place = False        # par défaut on travaille sur une copie
        self._auto_apply = False      # appliquer dès qu'un nouveau Raw arrive

        # État
        self._raw_in = None
        self._lbl = None
        self._apply_btn = None

        # Thread
        self._thread = None
        self._worker = None

    # ---------------- UI ----------------
    def build_widget(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        # Ligne 1 : HP/LP
        row1 = QHBoxLayout()
        self.chk_hp = QCheckBox("HP")
        self.chk_hp.setChecked(self._enable_hp)
        row1.addWidget(self.chk_hp)

        row1.addWidget(QLabel("HP (Hz):"))
        self.spn_hp = QDoubleSpinBox()
        self.spn_hp.setRange(0.01, 300.0)
        self.spn_hp.setSingleStep(0.1)
        self.spn_hp.setValue(self._hp)
        row1.addWidget(self.spn_hp)

        self.chk_lp = QCheckBox("LP")
        self.chk_lp.setChecked(self._enable_lp)
        row1.addWidget(self.chk_lp)

        row1.addWidget(QLabel("LP (Hz):"))
        self.spn_lp = QDoubleSpinBox()
        self.spn_lp.setRange(0.5, 1000.0)
        self.spn_lp.setSingleStep(0.5)
        self.spn_lp.setValue(self._lp)
        row1.addWidget(self.spn_lp)
        v.addLayout(row1)

        # Ligne 2 : Notch + picks
        row2 = QHBoxLayout()
        self.chk_notch = QCheckBox("Notch")
        self.chk_notch.setChecked(self._enable_notch)
        row2.addWidget(self.chk_notch)

        row2.addWidget(QLabel("f0, f1, ... (Hz):"))
        self.ed_notch = QLineEdit(self._notch_str)
        self.ed_notch.setPlaceholderText("ex: 50, 100")
        row2.addWidget(self.ed_notch)

        row2.addWidget(QLabel("Picks:"))
        self.cmb_picks = QComboBox()
        self.cmb_picks.addItems(["all", "eeg"])
        self.cmb_picks.setCurrentText(self._picks_mode)
        row2.addWidget(self.cmb_picks)
        v.addLayout(row2)

        # Ligne 3 : méthode, phase, in_place, auto
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Method:"))
        self.cmb_method = QComboBox()
        self.cmb_method.addItems(["fir", "iir"])
        self.cmb_method.setCurrentText(self._method)
        row3.addWidget(self.cmb_method)

        row3.addWidget(QLabel("Phase:"))
        self.cmb_phase = QComboBox()
        self.cmb_phase.addItems(["zero", "zero-double"])
        self.cmb_phase.setCurrentText(self._phase)
        row3.addWidget(self.cmb_phase)

        self.chk_inplace = QCheckBox("In-place")
        self.chk_inplace.setChecked(self._in_place)
        row3.addWidget(self.chk_inplace)

        self.chk_auto = QCheckBox("Auto-apply on new Raw")
        self.chk_auto.setChecked(self._auto_apply)
        row3.addWidget(self.chk_auto)
        v.addLayout(row3)

        # Ligne 4 : actions + statut
        row4 = QHBoxLayout()
        self._apply_btn = QPushButton("Apply filter")
        self._apply_btn.clicked.connect(self._apply_clicked)
        row4.addWidget(self._apply_btn)

        self._lbl = QLabel("Idle (no raw)")
        row4.addWidget(self._lbl)
        row4.addStretch(1)
        v.addLayout(row4)

        return w

    # -------------- Runtime --------------
    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        raw = args.get("raw", None)
        if raw is not None and raw is not self._raw_in:
            self._raw_in = raw
            # Émet les métadonnées tout de suite (même avant filtrage)
            self._emit_meta_from_raw(raw, note="input")
            self._update_status()
            if self._auto_apply:
                self._apply_clicked()
        return {}

    # -------------- Helpers --------------
    def _emit_meta_from_raw(self, raw, note=None):
        try:
            fs = float(raw.info.get("sfreq", 0.0))
            ch_names = list(raw.ch_names)
        except Exception:
            fs, ch_names = 0.0, []
        if fs > 0:
            self.outputs["sfreq"].on_next(fs)
        if ch_names:
            self.outputs["ch_names"].on_next(ch_names)

        info = {"sfreq": fs, "ch_names": ch_names}
        if note:
            info["note"] = str(note)
        self.outputs["info"].on_next(info)

    def _gather_params(self):
        self._enable_hp = self.chk_hp.isChecked()
        self._hp = float(self.spn_hp.value())
        self._enable_lp = self.chk_lp.isChecked()
        self._lp = float(self.spn_lp.value())
        self._enable_notch = self.chk_notch.isChecked()
        self._notch_str = self.ed_notch.text().strip()
        self._method = self.cmb_method.currentText()
        self._phase = self.cmb_phase.currentText()
        self._in_place = self.chk_inplace.isChecked()
        self._picks_mode = self.cmb_picks.currentText()
        self._auto_apply = self.chk_auto.isChecked()

        notch_list = []
        if self._notch_str:
            try:
                notch_list = [float(x) for x in self._notch_str.replace(";", ",").split(",") if x.strip()]
            except Exception:
                notch_list = []

        return {
            "enable_hp": self._enable_hp,
            "hp": self._hp,
            "enable_lp": self._enable_lp,
            "lp": self._lp,
            "enable_notch": self._enable_notch,
            "notch_freqs": notch_list,
            "method": self._method,
            "phase": self._phase,
            "in_place": self._in_place,
            "picks": self._picks_mode,
        }

    def _apply_clicked(self):
        if self._raw_in is None:
            if self._lbl: self._lbl.setText("Aucun Raw à filtrer.")
            return
        params = self._gather_params()
        self._apply_btn.setEnabled(False)
        if self._lbl: self._lbl.setText("Filtrage en cours...")

        # Thread de travail (évite de bloquer l'UI)
        self._thread = QThread()
        self._worker = _FilterWorker(self._raw_in, params)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        # Nettoyage
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._worker.failed.connect(self._thread.quit)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.start()

    def _on_done(self, raw_filt, info_msg):
        # 1) Émet le Raw filtré
        self.outputs["raw"].on_next(raw_filt)

        # 2) Émet méta dédiées (sfreq/ch_names) + info
        if isinstance(info_msg, dict):
            fs = float(info_msg.get("sfreq", 0.0)) if isinstance(info_msg.get("sfreq", None), (int, float)) else 0.0
            ch = list(info_msg.get("ch_names", [])) if isinstance(info_msg.get("ch_names", None), (list, tuple)) else []
            if fs > 0:
                self.outputs["sfreq"].on_next(fs)
            if ch:
                self.outputs["ch_names"].on_next(ch)
            self.outputs["info"].on_next(info_msg)
        else:
            # fallback au cas où
            self._emit_meta_from_raw(raw_filt, note="filtered")

        # 3) UI
        self._apply_btn.setEnabled(True)
        self._update_status(suffix="(filtered)")

    def _on_failed(self, err):
        if self._lbl: self._lbl.setText(f"Erreur: {err}")
        self._apply_btn.setEnabled(True)

    def _update_status(self, suffix=""):
        try:
            if self._raw_in is None:
                self._lbl.setText("Idle (no raw)")
                return
            fs = float(self._raw_in.info.get("sfreq", 0.0))
            n_ch = len(self._raw_in.ch_names)
            n_samp = int(self._raw_in.n_times)
            self._lbl.setText(f"Raw: {n_ch} ch, Fs={fs:.1f} Hz, n={n_samp} {suffix}")
        except Exception:
            self._lbl.setText("Raw prêt" + (" " + suffix if suffix else ""))
