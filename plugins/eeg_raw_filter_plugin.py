# plugins/eeg_raw_filter_plugin.py
# -*- coding: utf-8 -*-
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QDoubleSpinBox, QLineEdit, QCheckBox, QComboBox,
    QLayout, QSizePolicy, QApplication
)
from PyQt5.QtCore import QObject, QThread, pyqtSignal

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# --- metrics: fallback no-op si indisponible ---
try:
    from core.metrics_logger import metrics  # exposé par main via loader
except Exception:
    def metrics():
        class _Noop:
            def event(self, *a, **k): pass
            def param_change(self, *a, **k): pass
            def run_meta(self, *a, **k): pass
            def cpu_mem(self, *a, **k): pass
            def ttfp(self, *a, **k): pass
        return _Noop()

import atexit


# ---------------- Worker ----------------
class _FilterWorker(QObject):
    finished = pyqtSignal(object, dict)
    failed   = pyqtSignal(str)

    def __init__(self, raw, params):
        super().__init__(parent=None)
        self.raw = raw
        self.params = dict(params or {})

    def run(self):
        try:
            import mne
            raw_in = self.raw
            if raw_in is None:
                self.failed.emit("Aucun Raw en entrée.")
                return

            p = self.params
            in_place   = bool(p.get("in_place", False))
            method     = str(p.get("method", "fir"))
            phase      = str(p.get("phase", "zero"))
            hp         = p.get("hp", None)
            lp         = p.get("lp", None)
            do_hp      = bool(p.get("enable_hp", True))
            do_lp      = bool(p.get("enable_lp", True))
            do_notch   = bool(p.get("enable_notch", False))
            notch_list = list(p.get("notch_freqs", [])) if p.get("notch_freqs", []) else []
            picks_mode = str(p.get("picks", "all"))

            raw = raw_in if in_place else raw_in.copy()

            # Assure le chargement des données (corrige l'erreur MNE)
            try:
                if not getattr(raw, "preload", False):
                    raw.load_data()  # charge en RAM (float64 par défaut)
                    # option: réduire en float32 pour perf/mémoire
                    #try:
                    #    raw._data = raw._data.astype("float32", copy=False)
                    #except Exception:
                    #    pass
            except Exception:
                pass

            # Détermination des picks
            picks = None
            if picks_mode == "eeg":
                try:
                    picks = mne.pick_types(
                        raw.info, eeg=True, meg=False, stim=False, eog=False, ecg=False, seeg=True, misc=False
                    )
                except Exception:
                    picks = None

            # Notch
            if do_notch and notch_list:
                try:
                    # phase n'est pertinent que pour FIR; MNE ignore pour IIR
                    raw.notch_filter(freqs=notch_list, picks=picks, method=method, phase=phase, verbose=False)
                except TypeError:
                    # compat anciennes versions sans 'phase'
                    raw.notch_filter(freqs=notch_list, picks=picks, method=method, verbose=False)

            # BP/LP/HP
            l_freq = float(hp) if (do_hp and hp and hp > 0) else None
            h_freq = float(lp) if (do_lp and lp and lp > 0) else None
            if l_freq is not None or h_freq is not None:
                try:
                    raw.filter(l_freq=l_freq, h_freq=h_freq, picks=picks, method=method, phase=phase, verbose=False)
                except TypeError:
                    # compat sans 'phase'
                    raw.filter(l_freq=l_freq, h_freq=h_freq, picks=picks, method=method, verbose=False)

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
    language = "Python"

    def __del__(self):
        try:
            self.on_remove()
        except Exception:
            pass

    def setup(self):
        self.inputs = {"raw": BehaviorSubject(None)}
        self.outputs = {
            "raw": BehaviorSubject(None),
            "info": BehaviorSubject(None),
            "sfreq": BehaviorSubject(None),
            "ch_names": BehaviorSubject(None),
            "config_out": BehaviorSubject(None),
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
        self._shutting_down = False

        # hooks de fin (app + atexit)
        try:
            app = QApplication.instance()
            if app is not None and not self._cleanup_registered:
                app.aboutToQuit.connect(self.on_remove)
                self._cleanup_registered = True
        except Exception:
            pass
        atexit.register(self.on_remove)

    # ---------- Config I/O ----------
    def export_config(self) -> dict:
        try:
            notch_list = [float(x) for x in self._notch_str.replace(";", ",").split(",") if x.strip()]
        except Exception:
            notch_list = []
        return {
            "enable_hp": bool(self._enable_hp),
            "hp": float(self._hp),
            "enable_lp": bool(self._enable_lp),
            "lp": float(self._lp),
            "enable_notch": bool(self._enable_notch),
            "notch_freqs": notch_list,
            "method": str(self._method),
            "phase": str(self._phase),
            "picks": str(self._picks_mode),
            "in_place": bool(self._in_place),
        }

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return

        def set_bool(attr, key):
            v = cfg.get(key, getattr(self, attr))
            try: setattr(self, attr, bool(v))
            except Exception: pass

        def set_float(attr, key, mn=None, mx=None):
            v = cfg.get(key, getattr(self, attr))
            try:
                fv = float(v)
                if mn is not None: fv = max(mn, fv)
                if mx is not None: fv = min(mx, fv)
                setattr(self, attr, fv)
            except Exception: pass

        def set_str(attr, key, allowed=None):
            v = cfg.get(key, getattr(self, attr))
            if v is None: return
            s = str(v)
            if allowed and s not in allowed: return
            setattr(self, attr, s)

        set_bool("_enable_hp", "enable_hp")
        set_float("_hp", "hp", 0.0, 300.0)
        set_bool("_enable_lp", "enable_lp")
        set_float("_lp", "lp", 0.0, 1000.0)
        set_bool("_enable_notch", "enable_notch")

        nf = cfg.get("notch_freqs", None)
        if nf is not None:
            try:
                if isinstance(nf, (list, tuple)):
                    vals = [float(x) for x in nf]
                else:
                    vals = [float(x) for x in str(nf).replace(";", ",").split(",") if str(x).strip()]
                self._notch_str = ", ".join(str(x) for x in vals)
            except Exception:
                pass

        set_str("_method", "method", allowed=["fir","iir"])
        set_str("_phase", "phase", allowed=["zero","zero-double"])
        set_str("_picks_mode", "picks", allowed=["all","eeg"])
        set_bool("_in_place", "in_place")

        try:
            if hasattr(self, "chk_hp") and self.chk_hp:
                self.chk_hp.blockSignals(True); self.chk_hp.setChecked(self._enable_hp); self.chk_hp.blockSignals(False)
            if hasattr(self, "spn_hp") and self.spn_hp:
                self.spn_hp.blockSignals(True); self.spn_hp.setValue(self._hp); self.spn_hp.blockSignals(False)
            if hasattr(self, "chk_lp") and self.chk_lp:
                self.chk_lp.blockSignals(True); self.chk_lp.setChecked(self._enable_lp); self.chk_lp.blockSignals(False)
            if hasattr(self, "spn_lp") and self.spn_lp:
                self.spn_lp.blockSignals(True); self.spn_lp.setValue(self._lp); self.spn_lp.blockSignals(False)
            if hasattr(self, "chk_notch") and self.chk_notch:
                self.chk_notch.blockSignals(True); self.chk_notch.setChecked(self._enable_notch); self.chk_notch.blockSignals(False)
            if hasattr(self, "ed_notch") and self.ed_notch:
                self.ed_notch.blockSignals(True); self.ed_notch.setText(self._notch_str); self.ed_notch.blockSignals(False)
            if hasattr(self, "cmb_method") and self.cmb_method:
                self.cmb_method.blockSignals(True); self.cmb_method.setCurrentText(self._method); self.cmb_method.blockSignals(False)
            if hasattr(self, "cmb_phase") and self.cmb_phase:
                self.cmb_phase.blockSignals(True); self.cmb_phase.setCurrentText(self._phase); self.cmb_phase.blockSignals(False)
            if hasattr(self, "cmb_picks") and self.cmb_picks:
                self.cmb_picks.blockSignals(True); self.cmb_picks.setCurrentText(self._picks_mode); self.cmb_picks.blockSignals(False)
            if hasattr(self, "chk_inplace") and self.chk_inplace:
                self.chk_inplace.blockSignals(True); self.chk_inplace.setChecked(self._in_place); self.chk_inplace.blockSignals(False)
        except Exception:
            pass

        self._emit_config()
        self._schedule_apply()

    def config_hints(self) -> dict:
        return {
            "fields": {
                "enable_hp": {"type": "bool", "label": "HP on"},
                "hp": {"type": "float", "min": 0.01, "max": 300.0, "step": 0.1, "label": "HP (Hz)"},
                "enable_lp": {"type": "bool", "label": "LP on"},
                "lp": {"type": "float", "min": 0.5, "max": 1000.0, "step": 0.5, "label": "LP (Hz)"},
                "enable_notch": {"type": "bool", "label": "Notch on"},
                "notch_freqs": {"type": "list", "help": "Fréquences notch (CSV)", "label": "Notch freqs"},
                "method": {"type": "enum", "enum": ["fir", "iir"], "label": "Méthode"},
                "phase": {"type": "enum", "enum": ["zero","zero-double"], "label": "Phase"},
                "picks": {"type": "enum", "enum": ["all","eeg"], "label": "Picks"},
                "in_place": {"type": "bool", "label": "In-place"},
            },
            "_order": ["enable_hp","hp","enable_lp","lp","enable_notch","notch_freqs","method","phase","picks","in_place"],
        }

    def build_widget(self) -> QWidget:
        w = QWidget()
        UiKit.apply_node_style(w)
        v = QVBoxLayout(w)
        v.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

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

        row4 = QHBoxLayout()
        self._lbl = QLabel("Idle (no raw)")
        row4.addWidget(self._lbl)
        row4.addStretch(1)
        pv.addLayout(row4)

        v.addWidget(CollapsibleSection("Paramètres", panel, collapsed=True))

        w.destroyed.connect(self._on_destroy)

        try:
            app = QApplication.instance()
            if app is not None and not self._cleanup_registered:
                app.aboutToQuit.connect(self.on_remove)
                self._cleanup_registered = True
        except Exception:
            pass

        self._emit_config()
        return w

    # --------- Runtime ----------
    def execute(self, inputs=None, **kwargs):
        args = {}
        if isinstance(inputs, dict): args.update(inputs)
        args.update(kwargs)

        raw = args.get("raw", None)

        if "raw" in args and raw is None:
            self._raw_in = None
            self.outputs["raw"].on_next(None)
            self.outputs["info"].on_next({"note": "disconnected"})
            if self._lbl: self._lbl.setText("Disconnected")
            self._stop_thread_blocking(force=True)
            return {}

        if raw is not None:
            self._raw_in = raw
            self.outputs["raw"].on_next(raw)
            self._emit_meta_from_raw(raw, note="input")
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
        # snapshot OLD
        old = {
            "enable_hp": self._enable_hp,
            "hp": self._hp,
            "enable_lp": self._enable_lp,
            "lp": self._lp,
            "enable_notch": self._enable_notch,
            "notch_freqs": self._notch_str,
            "method": self._method,
            "phase": self._phase,
            "in_place": self._in_place,
            "picks": self._picks_mode,
        }
        # read NEW from UI
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

        # log PARAM_CHANGE (clé par clé)
        new = {
            "enable_hp": self._enable_hp,
            "hp": self._hp,
            "enable_lp": self._enable_lp,
            "lp": self._lp,
            "enable_notch": self._enable_notch,
            "notch_freqs": self._notch_str,
            "method": self._method,
            "phase": self._phase,
            "in_place": self._in_place,
            "picks": self._picks_mode,
        }
        try:
            for k, v_old in old.items():
                v_new = new.get(k)
                if str(v_old) != str(v_new):
                    metrics().param_change(name=k, old=v_old, new=v_new)
        except Exception:
            pass

        self._emit_config()
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
        if self._shutting_down or self._raw_in is None:
            return

        # arrêter un thread existant proprement
        if self._thread is not None and self._thread.isRunning():
            ok = self._stop_thread_blocking(force=True)
            if not ok:
                if self._lbl: self._lbl.setText("Filtering… (waiting previous)")
                return

        self._busy = True
        self._rerun = False
        if self._lbl: self._lbl.setText("Filtering…")
        try:
            metrics().event("FILTER_START", **(params or {}))
        except Exception:
            pass

        self._thread = QThread(parent=None)
        self._thread.setObjectName(f"{self.name}:filter")
        self._worker = _FilterWorker(self._raw_in, params)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)

        # cycle de vie & nettoyage garanti
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._cleanup_thread_objects)

        self._thread.start()

    def _cleanup_thread_objects(self):
        try:
            if self._thread is not None and self._thread.isRunning():
                return
        except Exception:
            pass
        try:
            if self._thread is not None:
                self._thread.deleteLater()
        except Exception:
            pass
        self._thread = None
        self._busy = False

    def _on_done(self, raw_filt, info_msg):
        self._busy = False
        try:
            metrics().event("FILTER_DONE")
        except Exception:
            pass

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
        try:
            metrics().event("FILTER_FAIL", error=str(err))
        except Exception:
            pass

        if self._lbl: self._lbl.setText(f"Erreur: {err}")
        if self._rerun and self._raw_in is not None:
            self._rerun = False
            last = self._last_params or self._gather_params()
            self._run_filter_async(last)

    # --------- arrêt propre du thread en cours ---------
    def _stop_thread_blocking(self, force=False, timeout_ms=10000) -> bool:
        th = self._thread
        if th is None:
            return True
        try:
            try: th.requestInterruption()
            except Exception: pass
            try: th.quit()
            except Exception: pass

            if not th.wait(timeout_ms):
                if force:
                    try:
                        th.terminate()
                        th.wait(3000)
                    except Exception:
                        pass
                else:
                    return False
        except Exception:
            pass
        finally:
            try:
                if self._worker is not None:
                    self._worker.deleteLater()
            except Exception:
                pass
            self._worker = None
            try:
                if th is not None:
                    th.deleteLater()
            except Exception:
                pass
            if th is self._thread:
                self._thread = None
            self._busy = False
            self._rerun = False

        try:
            return (self._thread is None) or (not th.isRunning())
        except Exception:
            return self._thread is None

    # --------- hooks destruction ---------
    def _on_destroy(self, *_):
        self.on_remove()

    def on_remove(self):
        self._shutting_down = True
        self._stop_thread_blocking(force=True)
        self._raw_in = None
