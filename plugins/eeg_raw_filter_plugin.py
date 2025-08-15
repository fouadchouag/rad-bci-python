# plugins/eeg_raw_filter_plugin.py
# EEGRawFilter : filtrage "offline" sur mne.io.Raw (FIR/IIR zero-phase)
# Version AUTO : pas de bouton "Apply" — applique en tâche de fond à chaque modification.
# Sorties : raw (filtré), info, sfreq, ch_names

from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QCheckBox, QComboBox,
    QLayout, QSizePolicy
)
from PyQt5.QtCore import QObject, QThread, pyqtSignal
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

import atexit

# ---------------- Worker ----------------
class _FilterWorker(QObject):
    finished = pyqtSignal(object, dict)   # (raw_filt, info_msg)
    failed   = pyqtSignal(str)

    def __init__(self, raw, params):
        super().__init__()
        self.raw = raw
        self.params = params

    def run(self):
        try:
            import mne
            raw_in = self.raw
            if raw_in is None:
                self.failed.emit("Aucun Raw en entrée.")
                return

            p = self.params
            in_place   = p.get("in_place", False)
            method     = p.get("method", "fir")
            phase      = p.get("phase", "zero")
            hp         = p.get("hp", None)
            lp         = p.get("lp", None)
            do_hp      = p.get("enable_hp", True)
            do_lp      = p.get("enable_lp", True)
            do_notch   = p.get("enable_notch", False)
            notch_list = p.get("notch_freqs", [])
            picks_mode = p.get("picks", "all")

            raw = raw_in if in_place else raw_in.copy()

            picks = None
            if picks_mode == "eeg":
                picks = mne.pick_types(
                    raw.info, eeg=True, meg=False, stim=False, eog=False, ecg=False, seeg=True, misc=False
                )

            if do_notch and notch_list:
                raw.notch_filter(freqs=notch_list, picks=picks, method=method, phase=phase, verbose=False)

            l_freq = float(hp) if (do_hp and hp and hp > 0) else None
            h_freq = float(lp) if (do_lp and lp and lp > 0) else None
            if l_freq is not None or h_freq is not None:
                raw.filter(l_freq=l_freq, h_freq=h_freq, picks=picks, method=method, phase=phase, verbose=False)

            info_msg = {
                "sfreq": float(raw.info.get("sfreq", 0.0)),
                "ch_names": list(raw.ch_names),
                "note": f"filtered (hp={l_freq}, lp={h_freq}, notch={notch_list}, method={method}, phase={phase}, picks={picks_mode})",
            }
            self.finished.emit(raw, info_msg)
        except Exception as e:
            self.failed.emit(str(e))

# ---------------- Plugin ----------------
class EEGRawFilterPlugin(BasePlugin):
    name = "EEGRawFilter"
    category = "Processing Nodes"

    def __del__(self):
        # filet de sécurité si GC sans on_destroy
        try:
            self._stop_thread_blocking(force=True)
        except Exception:
            pass

    def setup(self):
        self.inputs = {"raw": BehaviorSubject(None)}
        self.outputs = {
            "raw": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
        }

        # paramètres
        self._enable_hp = True
        self._hp = 1.0
        self._enable_lp = True
        self._lp = 40.0
        self._enable_notch = False
        self._notch_str = "50, 100"
        self._method = "fir"
        self._phase = "zero"
        self._picks_mode = "all"
        self._in_place = False

        # état
        self._raw_in = None
        self._lbl = None

        # worker / thread
        self._thread = None
        self._worker = None
        self._busy = False
        self._rerun = False
        self._last_params = None
        self._cleanup_registered = False

        # cleanup à l'extinction Python
        atexit.register(self._stop_thread_blocking)

    def build_widget(self) -> QWidget:
        w = QWidget()
        UiKit.apply_node_style(w)
        v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # contenu paramètres
        panel = QWidget()
        pv = QVBoxLayout(panel); pv.setContentsMargins(8, 8, 8, 8)

        row1 = QHBoxLayout()
        self.chk_hp = QCheckBox("HP"); self.chk_hp.setChecked(self._enable_hp)
        self.chk_hp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_hp)

        row1.addWidget(QLabel("HP (Hz):"))
        self.spn_hp = QDoubleSpinBox(); self.spn_hp.setRange(0.01, 300.0); self.spn_hp.setSingleStep(0.1); self.spn_hp.setValue(self._hp)
        self.spn_hp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_hp)

        self.chk_lp = QCheckBox("LP"); self.chk_lp.setChecked(self._enable_lp)
        self.chk_lp.stateChanged.connect(self._on_params_changed)
        row1.addWidget(self.chk_lp)

        row1.addWidget(QLabel("LP (Hz):"))
        self.spn_lp = QDoubleSpinBox(); self.spn_lp.setRange(0.5, 1000.0); self.spn_lp.setSingleStep(0.5); self.spn_lp.setValue(self._lp)
        self.spn_lp.valueChanged.connect(self._on_params_changed)
        row1.addWidget(self.spn_lp)
        pv.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_notch = QCheckBox("Notch"); self.chk_notch.setChecked(self._enable_notch)
        self.chk_notch.stateChanged.connect(self._on_params_changed)
        row2.addWidget(self.chk_notch)

        row2.addWidget(QLabel("f0, f1, ... (Hz):"))
        self.ed_notch = QLineEdit(self._notch_str); self.ed_notch.setPlaceholderText("ex: 50, 100")
        self.ed_notch.textChanged.connect(self._on_params_changed)
        row2.addWidget(self.ed_notch)

        row2.addWidget(QLabel("Picks:"))
        self.cmb_picks = QComboBox(); self.cmb_picks.addItems(["all", "eeg"]); self.cmb_picks.setCurrentText(self._picks_mode)
        self.cmb_picks.currentTextChanged.connect(self._on_params_changed)
        row2.addWidget(self.cmb_picks)
        pv.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Method:"))
        self.cmb_method = QComboBox(); self.cmb_method.addItems(["fir", "iir"]); self.cmb_method.setCurrentText(self._method)
        self.cmb_method.currentTextChanged.connect(self._on_params_changed)
        row3.addWidget(self.cmb_method)

        row3.addWidget(QLabel("Phase:"))
        self.cmb_phase = QComboBox(); self.cmb_phase.addItems(["zero", "zero-double"]); self.cmb_phase.setCurrentText(self._phase)
        self.cmb_phase.currentTextChanged.connect(self._on_params_changed)
        row3.addWidget(self.cmb_phase)

        self.chk_inplace = QCheckBox("In-place"); self.chk_inplace.setChecked(self._in_place)
        self.chk_inplace.stateChanged.connect(self._on_params_changed)
        row3.addWidget(self.chk_inplace)

        row3.addStretch(1)
        pv.addLayout(row3)

        # statut
        row4 = QHBoxLayout()
        self._lbl = QLabel("Idle (no raw)")
        row4.addWidget(self._lbl)
        row4.addStretch(1)
        pv.addLayout(row4)

        v.addWidget(CollapsibleSection("Paramètres", panel, collapsed=True))

        # IMPORTANT : nettoyage thread si le widget est détruit
        w.destroyed.connect(self._on_destroy)

        # S'enregistrer aussi sur aboutToQuit de Qt (si possible)
        self._register_about_to_quit_once()

        return w

    # --------- Runtime ----------
    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict):
            args.update(inputs)
        args.update(kwargs)

        raw = args.get("raw", None)

        # Déconnexion explicite -> propager None + arrêter proprement
        if "raw" in args and raw is None:
            self._raw_in = None
            self.outputs["raw"].on_next(None)
            self.outputs["info"].on_next({"note": "disconnected"})
            if self._lbl: self._lbl.setText("Disconnected")
            self._stop_thread_blocking()
            return {}

        if raw is not None:
            self._raw_in = raw
            # 1) Pass-through immédiat (prévisualisation)
            self.outputs["raw"].on_next(raw)
            # 2) Méta (ch_names, sfreq)
            self._emit_meta_from_raw(raw, note="input")
            # 3) Lancer filtrage auto
            self._schedule_apply()
        return {}

    # --------- Helpers ----------
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
        enable_hp = self.chk_hp.isChecked()
        hp = float(self.spn_hp.value())
        enable_lp = self.chk_lp.isChecked()
        lp = float(self.spn_lp.value())
        enable_notch = self.chk_notch.isChecked()
        notch_str = self.ed_notch.text().strip()
        method = self.cmb_method.currentText()
        phase = self.cmb_phase.currentText()
        in_place = self.chk_inplace.isChecked()
        picks_mode = self.cmb_picks.currentText()

        notch_list = []
        if notch_str:
            try:
                notch_list = [float(x) for x in notch_str.replace(";", ",").split(",") if x.strip()]
            except Exception:
                notch_list = []

        return {
            "enable_hp": enable_hp,
            "hp": hp,
            "enable_lp": enable_lp,
            "lp": lp,
            "enable_notch": enable_notch,
            "notch_freqs": notch_list,
            "method": method,
            "phase": phase,
            "in_place": in_place,
            "picks": picks_mode,
        }

    def _on_params_changed(self, *args):
        self._schedule_apply()

    def _schedule_apply(self):
        if self._raw_in is None:
            if self._lbl: self._lbl.setText("Idle (no raw)")
            return
        params = self._gather_params()
        self._last_params = params
        if self._busy:
            self._rerun = True
            if self._lbl: self._lbl.setText("Filtering… (queued)")
            return
        self._run_filter_async(params)

    def _run_filter_async(self, params):
        if self._raw_in is None:
            return
        # sécurité : arrêter un éventuel ancien thread
        self._stop_thread_blocking()
        self._busy = True
        self._rerun = False
        if self._lbl: self._lbl.setText("Filtering…")

        self._thread = QThread()
        self._worker = _FilterWorker(self._raw_in, params)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        # cycle de vie
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread_objects)
        self._thread.start()

    def _cleanup_thread_objects(self):
        try:
            if self._worker is not None:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
        try:
            if self._thread is not None:
                self._thread.deleteLater()
        except Exception:
            pass
        self._thread = None

    def _on_done(self, raw_filt, info_msg):
        self._busy = False
        if self._raw_in is None:
            if self._lbl: self._lbl.setText("Done (stale)")
        else:
            self.outputs["raw"].on_next(raw_filt)
            if isinstance(info_msg, dict):
                fs = float(info_msg.get("sfreq", 0.0)) if isinstance(info_msg.get("sfreq", None), (int, float)) else 0.0
                ch = list(info_msg.get("ch_names", [])) if isinstance(info_msg.get("ch_names", None), (list, tuple)) else []
                if fs > 0:
                    self.outputs["sfreq"].on_next(fs)
                if ch:
                    self.outputs["ch_names"].on_next(ch)
                self.outputs["info"].on_next(info_msg)
            else:
                self._emit_meta_from_raw(raw_filt, note="filtered")

            if self._lbl: self._lbl.setText("Filtered")

        if self._rerun and self._raw_in is not None:
            self._rerun = False
            last = self._last_params or self._gather_params()
            self._run_filter_async(last)

    def _on_failed(self, err):
        self._busy = False
        if self._lbl: self._lbl.setText(f"Erreur: {err}")
        if self._rerun and self._raw_in is not None:
            self._rerun = False
            last = self._last_params or self._gather_params()
            self._run_filter_async(last)

    # --------- arrêt propre du thread en cours ---------
    def _stop_thread_blocking(self, force=False):
        """Si un thread est en cours, tente de le quitter et attend sa fin.
        `force=True` : en dernier recours, terminate() si ça ne s'arrête pas."""
        th = self._thread
        if th is None:
            return
        try:
            if th.isRunning():
                th.quit()
                if not th.wait(10000):  # 10 s
                    if force:
                        try:
                            th.terminate()
                            th.wait(3000)
                        except Exception:
                            pass
        except Exception:
            pass
        finally:
            # nettoyage des refs
            try:
                if self._worker is not None:
                    self._worker.deleteLater()
            except Exception:
                pass
            self._worker = None
            try:
                if self._thread is not None:
                    self._thread.deleteLater()
            except Exception:
                pass
            self._thread = None
            self._busy = False
            self._rerun = False

    # --------- hook destruction widget / app ---------
    def _on_destroy(self, *_):
        self._stop_thread_blocking(force=True)

    def _register_about_to_quit_once(self):
        if self._cleanup_registered:
            return
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(lambda: self._stop_thread_blocking(force=True))
                self._cleanup_registered = True
        except Exception:
            # pas bloquant si pas d'app Qt à ce moment
            pass
