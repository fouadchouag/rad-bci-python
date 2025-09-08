# plugins/acquisition_manager.py
# -*- coding: utf-8 -*-
"""
AcquisitionManager (léger) — LSL | Emulator | Native (disabled)
Compat. EEGLiveDisplay (segment, ch_names, sfreq, info).
"""

from typing import Optional, List, Tuple, Any
import threading, time, numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QDoubleSpinBox, QCheckBox,
    QLayout, QSizePolicy, QStyle, QDialog, QListWidget, QListWidgetItem,
    QAbstractItemView, QDialogButtonBox, QComboBox, QPushButton
)
from PyQt5.QtCore import QObject, pyqtSignal, Qt
from PyQt5.QtGui import QPalette

from rx.subject import BehaviorSubject
from core.node_base import BasePlugin
        # utilitaires
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

# BENCH HOOK: logger d’événements (fallback silencieux si absent)
try:
    from utils.eval_log import log_evt
except Exception:
    def log_evt(*_a, **_k): pass

# pylsl optionnel
try:
    from pylsl import StreamInlet, resolve_streams
except Exception:
    StreamInlet = None
    resolve_streams = None


# ------------ helpers ------------
def _next_pow2(n: int) -> int:
    n = int(max(1, n))
    return 1 << (n - 1).bit_length()

def _hann_edge(N: int, edge_ratio: float = 0.12) -> np.ndarray:
    N = int(max(1, N))
    e = max(1, int(edge_ratio * N))
    w = np.ones(N, dtype=np.float32)
    if 2*e >= N:
        return np.hanning(N).astype(np.float32)
    import numpy as _np
    ramp = (1 - _np.cos(_np.linspace(0, _np.pi, e))) / 2.0
    w[:e] *= ramp
    w[-e:] *= ramp[::-1]
    return w.astype(np.float32)


# ---------- Bridge Qt (thread -> GUI) ----------
class _QtBridge(QObject):
   

    sig_info = pyqtSignal(dict)           # info/meta/statut
    sig_seg  = pyqtSignal(object, int)    # ndarray, run_id

    def connect(self, info_cb, seg_cb):
        self.sig_info.connect(lambda d: info_cb(d), Qt.QueuedConnection)
        self.sig_seg.connect(lambda a, rid: seg_cb(a, rid), Qt.QueuedConnection)


# ---------- Dialogue simple de sélection LSL ----------
class _LSLPicker(QDialog):
    def __init__(self, labels: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choisir un flux LSL")
        self.setModal(True)
        self.setMinimumWidth(420)
        pal = self.palette()
        pal.setColor(QPalette.Base, Qt.white)
        pal.setColor(QPalette.Text, Qt.black)
        pal.setColor(QPalette.Window, Qt.white)
        pal.setColor(QPalette.WindowText, Qt.black)
        self.setPalette(pal)

        v = QVBoxLayout(self)
        self.listw = QListWidget()
        self.listw.setSelectionMode(QAbstractItemView.SingleSelection)
        self.listw.setUniformItemSizes(True)
        for t in labels:
            self.listw.addItem(QListWidgetItem(t))
        if self.listw.count() > 0:
            self.listw.setCurrentRow(0)
        v.addWidget(self.listw)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def selected_row(self) -> int:
        idx = self.listw.currentRow()
        return int(idx if idx is not None else -1)


# ===================== Plugin =========================
class AcquisitionManager(BasePlugin):
    help = help = { 'gotchas': [],
                   'inputs': {},
                   'outputs': {'segment': '2D float [ch x samples]'},
                   'parameters': [],
                   'summary': 'AcquisitionManager (léger) — LSL | Emulator | Native (disabled)',
                   'usage': 'Connect to processing nodes.'}
     
    name = "AcquisitionManager"
    category = "Input Nodes"
    language = "Python"
    start_hidden = True
    supports_collapse = True

    # ---------- lifecycle ----------
    def setup(self):
        # sorties
        self.outputs["segment"]  = BehaviorSubject(None)
        self.outputs["ch_names"] = BehaviorSubject(None)
        self.outputs["sfreq"]    = BehaviorSubject(None)
        self.outputs["info"]     = BehaviorSubject(None)

        # état général
        self._debug = True
        self._running = False
        self._stop_evt = threading.Event()
        self._thr: Optional[threading.Thread] = None
        self._run_id = 0
        self._meta_ready = threading.Event()

        # cache méta
        self._sfreq = 0.0
        self._ch_names: List[str] = []

        # UI refs
        self._cmb_driver: Optional[QComboBox] = None
        self._sec_src = None
        self._sec_lsl = None
        self._sec_emu = None
        self._sec_nat = None
        self._sec_seg = None

        # LSL UI state
        self._lsl_infos: List[Any] = []
        self._lsl_labels: List[str] = []
        self._lsl_sel_idx: int = -1
        self._lsl_chunk = 50
        self._lbl_status_lsl: Optional[QLabel] = None
        self._lbl_lsl_sel: Optional[QLabel] = None
        self._lbl_lsl_found: Optional[QLabel] = None

        # Emulator UI
        self._emu_sf = 250
        self._emu_nch = 8
        self._emu_noise = 0.05
        self._emu_chunk = 50
        self._lbl_status_emu: Optional[QLabel] = None

        # Segmentation
        self._seg_len_s = 0.0
        self._hop_ratio = 0.5
        self._hop_s = 0.0
        self._smoothing = True

        # bridge
        self._bridge = _QtBridge()
        self._bridge.connect(self._emit_info_gui, self._emit_seg_gui)

        self.widget = self.build_widget()

        # BENCH HOOKS
        self._samples_in = 0        # cumul d’échantillons temporels
        self._klog_next  = 1000     # seuils SAMPLES_IN: 1000, 2000, 3000, ...

    def execute(self, inputs=None):
        return {}

    # ---------- UI ----------
    def build_widget(self) -> QWidget:
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root = QVBoxLayout(w); root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        # ===== Source =====
        src = QWidget(); vs = QVBoxLayout(src); vs.setContentsMargins(8,8,8,8); vs.setSpacing(8)
        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Source:"))
        self._cmb_driver = QComboBox()
        self._cmb_driver.addItems(["LSL", "Emulator", "Native (disabled)"])
        self._cmb_driver.setCurrentIndex(0)
        self._cmb_driver.currentIndexChanged.connect(lambda _i: self._on_driver_changed(self._cmb_driver.currentText()))
        r0.addWidget(self._cmb_driver, 0)
        r0.addSpacing(16)
        chk_dbg = QCheckBox("Debug"); chk_dbg.setChecked(self._debug)
        chk_dbg.stateChanged.connect(lambda s: setattr(self, "_debug", bool(s)))
        r0.addWidget(chk_dbg); r0.addStretch(1)
        vs.addLayout(r0)
        self._sec_src = CollapsibleSection("Source", src, collapsed=True)
        root.addWidget(self._sec_src)

        # ===== LSL =====
        root.addWidget(self._build_lsl_section(w))
        # ===== Emulator =====
        root.addWidget(self._build_emu_section(w))
        # ===== Segmentation =====
        self._sec_seg = self._build_seg_section(w); root.addWidget(self._sec_seg)
        # ===== Native placeholder =====
        root.addWidget(self._build_native_section(w))

        self._update_sections()
        return w

    def _build_lsl_section(self, parent=None) -> CollapsibleSection:
        p = QWidget(); v = QVBoxLayout(p); v.setContentsMargins(8,8,8,8); v.setSpacing(8)

        r1 = QHBoxLayout()
        btn_scan = UiKit.make_btn("Rechercher", icon_sp=QStyle.SP_BrowserReload)
        btn_scan.clicked.connect(self._refresh_lsl_list); r1.addWidget(btn_scan)
        btn_pick = UiKit.make_btn("Choisir…", role="primary", icon_sp=QStyle.SP_DialogOpenButton)
        btn_pick.clicked.connect(self._pick_lsl); r1.addWidget(btn_pick)
        r1.addWidget(QLabel("Sélection:")); self._lbl_lsl_sel = QLabel("(aucun)"); r1.addWidget(self._lbl_lsl_sel, 1)
        v.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Chunk len (samples):"))
        sp = QSpinBox(); sp.setRange(1, 4096); sp.setValue(self._lsl_chunk); sp.valueChanged.connect(lambda x: setattr(self, "_lsl_chunk", int(x))); r2.addWidget(sp)
        self._lbl_lsl_found = QLabel("Flux: 0"); r2.addWidget(self._lbl_lsl_found, 1)
        v.addLayout(r2)

        r3 = QHBoxLayout()
        btn_start = UiKit.make_btn("Start", role="success", icon_sp=QStyle.SP_MediaPlay); btn_stop  = UiKit.make_btn("Stop", role="danger", icon_sp=QStyle.SP_MediaStop)
        btn_start.clicked.connect(lambda: self._on_start("lsl")); btn_stop.clicked.connect(self._on_stop)
        r3.addWidget(btn_start); r3.addWidget(btn_stop); r3.addStretch(1); v.addLayout(r3)

        self._lbl_status_lsl = QLabel("Statut: " + ("❌ pylsl introuvable — pip install pylsl" if resolve_streams is None else "idle"))
        v.addWidget(self._lbl_status_lsl)

        sec = CollapsibleSection("LSL", p, collapsed=True, parent=parent); self._sec_lsl = sec
        return sec

    def _build_emu_section(self, parent=None) -> CollapsibleSection:
        p = QWidget(); v = QVBoxLayout(p); v.setContentsMargins(8,8,8,8); v.setSpacing(8)
        r = QHBoxLayout()
        r.addWidget(QLabel("sfreq:")); sf = QSpinBox(); sf.setRange(10,4000); sf.setValue(self._emu_sf); sf.valueChanged.connect(lambda x: setattr(self,"_emu_sf", int(x))); r.addWidget(sf)
        r.addWidget(QLabel("n_ch:")); nc = QSpinBox(); nc.setRange(1,256); nc.setValue(self._emu_nch); nc.valueChanged.connect(lambda x: setattr(self,"_emu_nch", int(x))); r.addWidget(nc)
        r.addWidget(QLabel("noise:")); no = QDoubleSpinBox(); no.setRange(0.0,5.0); no.setDecimals(3); no.setSingleStep(0.01); no.setValue(self._emu_noise); no.valueChanged.connect(lambda x: setattr(self,"_emu_noise", float(x))); r.addWidget(no)
        r.addWidget(QLabel("chunk:")); ck = QSpinBox(); ck.setRange(1,4096); ck.setValue(self._emu_chunk); ck.valueChanged.connect(lambda x: setattr(self,"_emu_chunk", int(x))); r.addWidget(ck)
        r.addStretch(1); v.addLayout(r)
        r3 = QHBoxLayout()
        btn_start = UiKit.make_btn("Start", role="success", icon_sp=QStyle.SP_MediaPlay); btn_stop  = UiKit.make_btn("Stop",  role="danger",  icon_sp=QStyle.SP_MediaStop)
        btn_start.clicked.connect(lambda: self._on_start("emu")); btn_stop.clicked.connect(self._on_stop)
        r3.addWidget(btn_start); r3.addWidget(btn_stop); r3.addStretch(1); v.addLayout(r3)
        self._lbl_status_emu = QLabel("Statut: idle"); v.addWidget(self._lbl_status_emu)
        sec = CollapsibleSection("Émulateur", p, collapsed=True, parent=parent); self._sec_emu = sec
        return sec

    def _build_seg_section(self, parent=None) -> CollapsibleSection:
        p = QWidget(); v = QVBoxLayout(p); v.setContentsMargins(8,8,8,8); v.setSpacing(8)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("seg_len (s, 0=auto):"))
        sp_seg = QDoubleSpinBox(); sp_seg.setRange(0.0, 60.0); sp_seg.setDecimals(3); sp_seg.setSingleStep(0.05); sp_seg.setValue(self._seg_len_s)
        sp_seg.valueChanged.connect(lambda x: setattr(self,"_seg_len_s", float(x))); r1.addWidget(sp_seg)

        r1.addSpacing(12); r1.addWidget(QLabel("hop ratio (0..1):"))
        sp_hr = QDoubleSpinBox(); sp_hr.setRange(0.0, 1.0); sp_hr.setDecimals(2); sp_hr.setSingleStep(0.05); sp_hr.setValue(self._hop_ratio)
        sp_hr.valueChanged.connect(lambda x: setattr(self,"_hop_ratio", float(x))); r1.addWidget(sp_hr)

        r1.addSpacing(12); r1.addWidget(QLabel("hop (s, si ratio=0):"))
        sp_hs = QDoubleSpinBox(); sp_hs.setRange(0.0, 60.0); sp_hs.setDecimals(3); sp_hs.setSingleStep(0.05); sp_hs.setValue(self._hop_s)
        sp_hs.valueChanged.connect(lambda x: setattr(self,"_hop_s", float(x))); r1.addWidget(sp_hs)

        r1.addStretch(1); v.addLayout(r1)
        r2 = QHBoxLayout()
        chk_sm = QCheckBox("Smoothing (Hann bords)"); chk_sm.setChecked(self._smoothing)
        chk_sm.stateChanged.connect(lambda s: setattr(self,"_smoothing", bool(s)))
        r2.addWidget(chk_sm); r2.addStretch(1); v.addLayout(r2)

        sec = CollapsibleSection("Segmentation", p, collapsed=True, parent=parent); self._sec_seg = sec
        return sec

    def _build_native_section(self, parent=None) -> CollapsibleSection:
        p = QWidget(); v = QVBoxLayout(p); v.setContentsMargins(8,8,8,8); v.setSpacing(6)
        v.addWidget(QLabel("🔒 Native hardware désactivé (connexion directe sans LSL — placeholder)."))
        sec = CollapsibleSection("Native (coming soon)", p, collapsed=True, parent=parent); self._sec_nat = sec
        return sec

    # ---------- driver visibility ----------
    def _on_driver_changed(self, _txt: str):
        if self._running:
            self._on_stop()
        try:
            self.outputs["segment"].on_next(None)
            self.outputs["info"].on_next({"status":"driver changed"})
        except Exception:
            pass
        self._update_sections()

    def _cur_driver(self) -> str:
        return self._cmb_driver.currentText() if self._cmb_driver else "LSL"

    def _update_sections(self):
        drv = (self._cur_driver() or "LSL").lower()
        show_lsl = drv.startswith("lsl")
        show_emu = drv.startswith("emulator")
        show_nat = drv.startswith("native")

        if self._sec_lsl: self._sec_lsl.setVisible(show_lsl)
        if self._sec_emu: self._sec_emu.setVisible(show_emu)
        if self._sec_nat: self._sec_nat.setVisible(show_nat)
        if self._sec_src: self._sec_src.setVisible(True)
        if self._sec_seg: self._sec_seg.setVisible(True)

        self._set_status("idle" if not show_nat else "Native (désactivé)")

    # ---------- status / logs ----------
    def _set_status(self, s: str):
        if self._lbl_status_lsl: self._lbl_status_lsl.setText(f"Statut: {s}")
        if self._lbl_status_emu: self._lbl_status_emu.setText(f"Statut: {s}")

    def _log(self, *a):
        if self._debug: print("[AcqAM]", *a)

    # ---------- LSL (scan + jolis libellés) ----------
    def _pretty_label(self, info: Any) -> str:
        name = (info.name() or "").strip()
        stype = (info.type() or "").strip() or "EEG"
        nch = int(info.channel_count() or 0)
        sf  = int(info.nominal_srate() or 0)

        is_bf = False
        try:
            manuf = (info.desc().child_value("manufacturer") or "").strip().lower()
            if manuf == "brainflow":
                is_bf = True
        except Exception:
            pass
        nm_low = name.lower()
        if nm_low.startswith("bf-"):
            is_bf = True
            name = "Brain Flow " + name[3:]
        elif "brainflow" in nm_low and "brain flow" not in nm_low:
            is_bf = True
            name = name.replace("brainflow", "Brain Flow")

        if is_bf and not name.lower().startswith("brain flow"):
            name = f"Brain Flow {name}"

        return f"{name}/{stype} - {nch}ch @{sf}Hz"

    def _refresh_lsl_list(self):
        if resolve_streams is None:
            self._lsl_infos = []; self._lsl_labels = []
            if self._lbl_lsl_found: self._lbl_lsl_found.setText("Flux: 0 (pylsl absent)")
            return

        infos: List[Any] = []
        err = None
        try:
            infos = resolve_streams(wait_time=2.0)
        except TypeError:
            try:
                infos = resolve_streams(2.0)
            except Exception as e:
                err = e
        except Exception as e:
            err = e

        if not infos:
            try:
                from pylsl import resolve_byprop
                infos = resolve_byprop('type','EEG', timeout=1.0)
            except Exception:
                pass

        if not infos and err is not None:
            self._log("resolve_streams error:", err)

        def _key(info):
            name = (info.name() or "").lower()
            prefer = 0 if (name.startswith("bf-") or "brainflow" in name or name in ("fakeeeg","simeeg")) else 1
            return (prefer, int(info.channel_count() or 0))
        infos = sorted(infos or [], key=_key)

        self._lsl_infos = infos
        self._lsl_labels = [self._pretty_label(i) for i in infos]
        if self._lbl_lsl_found:
            self._lbl_lsl_found.setText(f"Flux: {len(self._lsl_labels)}")
        if self._lbl_lsl_sel and (self._lsl_sel_idx < 0 or self._lsl_sel_idx >= len(self._lsl_labels)):
            self._lbl_lsl_sel.setText("(aucun)")
        self._log("LSL found:", self._lsl_labels)

    def _pick_lsl(self):
        if not self._lsl_labels:
            self._refresh_lsl_list()
        if not self._lsl_labels:
            self._set_status("Aucun flux LSL"); return
        dlg = _LSLPicker(self._lsl_labels, parent=self.widget)
        if dlg.exec_() == QDialog.Accepted:
            idx = dlg.selected_row()
            if 0 <= idx < len(self._lsl_infos):
                self._lsl_sel_idx = idx
                if self._lbl_lsl_sel:
                    self._lbl_lsl_sel.setText(self._lsl_labels[idx])
                self._set_status(f"Sélectionné: {self._lsl_labels[idx]}")

    # ---------- start/stop ----------
    def _on_start(self, driver: Optional[str] = None):
        if self._running:
            self._on_stop()

        drv = (driver or (self._cur_driver() if self._cmb_driver else "LSL")).lower()

        # BENCH HOOK: début de run (source)
        try:
            log_evt("RUN", f"source={drv}")
        except Exception:
            pass

        if drv.startswith("native"):
            self._set_status("Native désactivé — rien à démarrer"); return

        self._run_id += 1
        run_id = self._run_id
        self._meta_ready.clear()
        self._stop_evt.clear()
        self._running = True
        # reset compteurs bench
        self._samples_in = 0
        self._klog_next = 1000

        if drv.startswith("lsl") and StreamInlet is not None:
            if self._lsl_sel_idx < 0 or self._lsl_sel_idx >= len(self._lsl_infos):
                if not self._lsl_infos:
                    self._refresh_lsl_list()
                if not self._lsl_infos:
                    self._set_status("Aucun flux LSL"); self._running = False; return
                self._lsl_sel_idx = 0
                if self._lbl_lsl_sel:
                    self._lbl_lsl_sel.setText(self._lsl_labels[0])

            info = self._lsl_infos[self._lsl_sel_idx]
            label = self._pretty_label(info)
            self._set_status(f"LSL: connecting… ({label})")
            self._log("START LSL", label, "run_id=", run_id)
            self._thr = threading.Thread(target=self._run_lsl, args=(info, run_id), daemon=True)
            self._thr.start()

        else:
            self._set_status("Emulator: running")
            self._log("START Emulator", "run_id=", run_id)
            self._thr = threading.Thread(target=self._run_emulator, args=(run_id,), daemon=True)
            self._thr.start()

    def _on_stop(self):
        self._stop_evt.set()
        t = self._thr; self._thr = None
        if t and t.is_alive():
            t.join(timeout=3.0)
        self._running = False
        try:
            self.outputs["segment"].on_next(None)
            self.outputs["info"].on_next({"status":"stopped"})
        except Exception:
            pass
        self._set_status("idle")
        self._log("STOP")

    # ---------- segmentation params ----------
    def _prepare_seg(self, sf: float) -> Tuple[int,int,Optional[np.ndarray]]:
        if self._seg_len_s <= 0:
            target = 256 * (float(sf)/250.0)
            seg_len = max(32, _next_pow2(int(round(target))))
        else:
            seg_len = max(16, int(round(self._seg_len_s * float(sf))))
        if self._hop_ratio > 0:
            hop = max(1, int(round(self._hop_ratio * seg_len)))
        else:
            hop = max(1, int(round(self._hop_s * float(sf))))
        win = _hann_edge(seg_len) if self._smoothing else None
        self._log(f"seg params: len={seg_len} hop={hop} sf={sf}")
        return seg_len, hop, win

    # ---------- workers ----------
    def _run_emulator(self, run_id: int):
        sf = int(self._emu_sf); nch = int(self._emu_nch)
        noise = float(self._emu_noise); chunk = int(self._emu_chunk)

        ch_names = [f"Ch{i+1}" for i in range(nch)]
        if len(ch_names) < nch:
            ch_names += [f"Ch{i+1}" for i in range(len(ch_names), nch)]
        elif len(ch_names) > nch:
            ch_names = ch_names[:nch]

        self._bridge.sig_info.emit({
            "reset": True, "sfreq": float(sf), "ch_names": ch_names,
            "source": "emulator",
            "status": f"Emulator — {nch}ch @ {sf}Hz"
        })
        self._meta_ready.wait(timeout=0.5)

        seg_len, hop, win = self._prepare_seg(sf)
        buf = np.zeros((0, nch), dtype=np.float32)
        t = 0
        while not self._stop_evt.is_set() and self._run_id == run_id:
            tt = (t + np.arange(chunk)) / float(sf)
            base = 0.7*np.sin(2*np.pi*10.0*tt) + 0.3*np.sin(2*np.pi*20.0*tt)
            blk = np.repeat(base[:, None], nch, axis=1) + noise*np.random.randn(chunk, nch)
            blk = blk.astype(np.float32, copy=False)
            buf = np.vstack([buf, blk])

            while buf.shape[0] >= seg_len:
                seg = buf[:seg_len, :]
                buf = buf[hop:, :]
                if win is not None:
                    seg = (seg * win[:, None]).astype(np.float32, copy=False)
                self._bridge.sig_seg.emit(np.array(seg.T, dtype=np.float32, order="C", copy=True), run_id)

            t += chunk
            time.sleep(chunk / float(sf))

    def _run_lsl(self, info: Any, run_id: int):
        if StreamInlet is None:
            self._bridge.sig_info.emit({"status": "pylsl absent"}); return
        try:
            inlet = StreamInlet(info, max_chunklen=self._lsl_chunk)
        except Exception as e:
            self._bridge.sig_info.emit({"status": f"Erreur StreamInlet: {e}"}); return

        try:
            nch = int(info.channel_count()); sf = float(info.nominal_srate() or 0.0)
            name = info.name(); stp = info.type(); uid = info.source_id()
            ch_names = []
            try:
                node = info.desc().child("channels").first_child()
                while node.name():
                    lab = node.child_value("label")
                    ch_names.append(lab if lab else f"ch{len(ch_names)+1}")
                    node = node.next_sibling()
            except Exception:
                ch_names = [f"ch{i+1}" for i in range(nch)]
        except Exception as e:
            self._bridge.sig_info.emit({"status": f"Erreur méta LSL: {e}"}); return

        if len(ch_names) < nch:
            ch_names = ch_names + [f"Ch{i+1}" for i in range(len(ch_names), nch)]
        elif len(ch_names) > nch:
            ch_names = ch_names[:nch]

        if sf <= 0: sf = 250.0
        self._bridge.sig_info.emit({
            "sfreq": sf, "ch_names": ch_names, "name": name, "type": stp, "uid": uid,
            "n_channels": nch, "reset": True,
            "status": f"LSL connected — {self._pretty_label(info)}",
        })
        self._meta_ready.wait(timeout=0.5)

        seg_len, hop, win = self._prepare_seg(sf)
        buf = np.zeros((0, nch), dtype=np.float32)
        last_log = 0.0

        while not self._stop_evt.is_set() and self._run_id == run_id:
            try:
                samples, _ = inlet.pull_chunk(timeout=0.2, max_samples=max(self._lsl_chunk, seg_len))
            except Exception as e:
                self._bridge.sig_info.emit({"status": f"Erreur lecture: {e}"}); break

            if samples and len(samples) > 0:
                arr = np.asarray(samples, dtype=np.float32)  # (n_samples, n_ch)
                if arr.ndim == 1: arr = arr[:, None]
                if arr.shape[1] != nch:
                    if arr.shape[1] < nch:
                        pad = np.zeros((arr.shape[0], nch - arr.shape[1]), dtype=np.float32)
                        arr = np.hstack([arr, pad])
                    else:
                        arr = arr[:, :nch]
                buf = np.vstack([buf, arr])

                while buf.shape[0] >= seg_len:
                    seg = buf[:seg_len, :]
                    buf = buf[hop:, :]
                    if win is not None:
                        seg = (seg * win[:, None]).astype(np.float32, copy=False)
                    self._bridge.sig_seg.emit(np.array(seg.T, dtype=np.float32, order="C", copy=True), run_id)

                now = time.time()
                if now - last_log > 1.0 and self._debug:
                    print("[AcqAM] LSL pull", arr.shape, "run", run_id)
                    last_log = now
            else:
                time.sleep(0.01)

        try:
            inlet.close_stream()
        except Exception:
            pass

    # ---------- emission GUI ----------
    def _emit_info_gui(self, info: dict):
        sf = info.get("sfreq", None)
        ch = info.get("ch_names", None)
        if isinstance(sf, (int, float)) and sf > 0:
            self._sfreq = float(sf); self.outputs["sfreq"].on_next(self._sfreq)
        if isinstance(ch, (list, tuple)) and ch:
            self._ch_names = list(ch); self.outputs["ch_names"].on_next(self._ch_names)
        if info.get("reset") or (isinstance(ch, (list,tuple)) and ch):
            self._meta_ready.set()
        self.outputs["info"].on_next(info)
        st = info.get("status", None)
        if st: self._set_status(st)

    def _emit_seg_gui(self, arr, run_id: int):
        if run_id != self._run_id:
            if self._debug: print("[AcqAM] drop stale seg from run", run_id, "current", self._run_id)
            return
        if arr is None:
            self.outputs["segment"].on_next(None); return
        try:
            a = np.asarray(arr)
            if a.ndim == 2:
                nch_hint = len(self._ch_names) if self._ch_names else None
                if nch_hint:
                    if a.shape[0] != nch_hint and a.shape[1] == nch_hint:
                        a = a.T
                    elif a.shape[0] != nch_hint and a.shape[1] != nch_hint:
                        if a.shape[0] > a.shape[1]:
                            a = a.T
                else:
                    if a.shape[0] > a.shape[1]:
                        a = a.T
            a = np.asarray(a, dtype=np.float32, order="C")

            # BENCH HOOK: créditer SAMPLES_IN par pas de 1000
            try:
                n_samp = int(a.shape[1]) if a.ndim == 2 else 0
                if n_samp > 0:
                    self._samples_in += n_samp
                    while self._samples_in >= self._klog_next:
                        log_evt("SAMPLES_IN", str(self._klog_next))
                        self._klog_next += 1000
            except Exception:
                pass

            if self._debug: print("[AcqAM] emit seg", a.shape, "run", run_id)
            self.outputs["segment"].on_next(a)
        except Exception as e:
            if self._debug: print("[AcqAM] emit error:", e)

    # ---------- cleanup ----------
    def on_remove(self):
        try:
            self._on_stop()
        except Exception:
            pass