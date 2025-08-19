# plugins/bci_epoch_node.py
# -*- coding: utf-8 -*-

import numpy as np
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
    QSpinBox, QCheckBox, QComboBox, QGroupBox, QSizePolicy, QLineEdit, QStyle
)
from core.node_base import BasePlugin

from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    import sip
    def _alive(w):
        try: return (w is not None) and (not sip.isdeleted(w))
        except Exception: return w is not None
except Exception:
    def _alive(w): return w is not None


def _to_ns_nc(x):
    arr = np.asarray(x)
    if arr.ndim == 1:
        return arr[:, None], False
    if arr.shape[0] >= arr.shape[1]:
        return arr, False
    return arr.T, True

def _from_ns_nc(arr, was_T):
    return arr.T if was_T else arr


class BCIEpochNode(BasePlugin):
    name = "BCI_Epoch"
    language = "Python"
    category = "BCI/Segmentation"

    # ---------------- lifecycle ----------------
    def setup(self):
        # Inputs data
        self.inputs["chunk"]     = BehaviorSubject(None)
        self.inputs["sfreq"]     = BehaviorSubject(None)
        self.inputs["ch_names"]  = BehaviorSubject(None)
        self.inputs["events"]    = BehaviorSubject(None)
        self.inputs["reset"]     = BehaviorSubject(None)
        self.inputs["flush"]     = BehaviorSubject(None)

        # 🔌 Entrées config (compat BCI_Config)
        self.inputs["config_in"]  = BehaviorSubject(None)  # générique
        self.inputs["epoch_conf"] = BehaviorSubject(None)  # dédiée

        # Outputs data
        self.outputs["segment"]   = BehaviorSubject(None)
        self.outputs["sfreq"]     = BehaviorSubject(None)
        self.outputs["ch_names"]  = BehaviorSubject(None)
        self.outputs["epoch_info"]= BehaviorSubject(None)

        # 🔌 Sortie config pour "Collect"
        self.outputs["config_out"] = BehaviorSubject(None)

        # State
        self._fs = None
        self._n_ch = None
        self._ch_names = None
        self._was_T = False

        # Buffer
        self._buf = None
        self._buf_len = 0
        self._buf_start_gidx = 0
        self._g_end = 0
        self._epoch_idx = 0

        # Params (avec valeurs par défaut cohérentes avec BCI_Config)
        self._mode = "Sliding"      # "Sliding" | "Event-locked"
        self._win_sec  = 1.0
        self._step_sec = 0.5
        self._drop_incomplete = True

        self._pre_sec  = 0.2
        self._post_sec = 0.8
        self._ev_filter_text = ""
        self._ev_queue = []
        self._events_chunk_relative = False

        self._buffer_sec = 30.0

        # UI refs
        self._lbl_status = None
        self._cmb_mode = None
        self._spL = None
        self._spS = None
        self._ck_drop = None
        self._spPre = None
        self._spPost = None
        self._edFilt = None
        self._ckRel = None
        self._spBuf = None

        # emit config initiale
        self._emit_config()

    def build_widget(self):
        w = QWidget(); w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        UiKit.apply_node_style(w)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        gbM = QWidget(); ml = QVBoxLayout(gbM); ml.setContentsMargins(8,8,8,8)
        rmode = QHBoxLayout()
        rmode.addWidget(QLabel("Epoch mode:"))
        self._cmb_mode = QComboBox(); self._cmb_mode.addItems(["Sliding","Event-locked"])
        self._cmb_mode.setCurrentText(self._mode)
        self._cmb_mode.currentIndexChanged.connect(lambda i: setattr(self,"_mode", self._cmb_mode.itemText(i)) or self._emit_config())
        rmode.addWidget(self._cmb_mode); rmode.addStretch(1)
        ml.addLayout(rmode)

        gbS = QWidget(); sl = QVBoxLayout(gbS); sl.setContentsMargins(8,8,8,8)
        rs = QHBoxLayout()
        rs.addWidget(QLabel("Window L [s]:"))
        self._spL = QDoubleSpinBox(); self._spL.setRange(0.05, 60.0); self._spL.setDecimals(3); self._spL.setValue(self._win_sec)
        self._spL.valueChanged.connect(lambda v: setattr(self,"_win_sec", float(v)) or self._emit_config())
        rs.addWidget(self._spL); rs.addSpacing(12); rs.addWidget(QLabel("Step [s]:"))
        self._spS = QDoubleSpinBox(); self._spS.setRange(0.01, 10.0); self._spS.setDecimals(3); self._spS.setValue(self._step_sec)
        self._spS.valueChanged.connect(lambda v: setattr(self,"_step_sec", float(v)) or self._emit_config())
        rs.addWidget(self._spS); rs.addSpacing(12)
        self._ck_drop = QCheckBox("Drop incomplete"); self._ck_drop.setChecked(self._drop_incomplete)
        self._ck_drop.toggled.connect(lambda s: setattr(self,"_drop_incomplete", bool(s)) or self._emit_config())
        rs.addWidget(self._ck_drop); rs.addStretch(1); sl.addLayout(rs)

        gbE = QWidget(); el = QVBoxLayout(gbE); el.setContentsMargins(8,8,8,8)
        re = QHBoxLayout()
        re.addWidget(QLabel("Pre [s]:")); self._spPre = QDoubleSpinBox(); self._spPre.setRange(0.0, 10.0); self._spPre.setDecimals(3); self._spPre.setValue(self._pre_sec)
        self._spPre.valueChanged.connect(lambda v: setattr(self,"_pre_sec", float(v)) or self._emit_config()); re.addWidget(self._spPre)
        re.addSpacing(12); re.addWidget(QLabel("Post [s]:"))
        self._spPost = QDoubleSpinBox(); self._spPost.setRange(0.05, 10.0); self._spPost.setDecimals(3); self._spPost.setValue(self._post_sec)
        self._spPost.valueChanged.connect(lambda v: setattr(self,"_post_sec", float(v)) or self._emit_config()); re.addWidget(self._spPost)
        re.addSpacing(12); re.addWidget(QLabel("Keep types (comma, empty=all):"))
        self._edFilt = QLineEdit(self._ev_filter_text); self._edFilt.textChanged.connect(lambda t: setattr(self,"_ev_filter_text", t) or self._emit_config())
        re.addWidget(self._edFilt, 1); el.addLayout(re)
        re2 = QHBoxLayout()
        self._ckRel = QCheckBox("Events 'pos' are CHUNK-relative"); self._ckRel.setChecked(self._events_chunk_relative)
        self._ckRel.toggled.connect(lambda s: setattr(self, "_events_chunk_relative", bool(s)) or self._emit_config())
        re2.addWidget(self._ckRel); re2.addStretch(1); el.addLayout(re2)

        gbB = QWidget(); bl = QVBoxLayout(gbB); bl.setContentsMargins(8,8,8,8)
        rb = QHBoxLayout()
        rb.addWidget(QLabel("Buffer [s]:"))
        self._spBuf = QDoubleSpinBox(); self._spBuf.setRange(1.0, 600.0); self._spBuf.setDecimals(1); self._spBuf.setValue(self._buffer_sec)
        self._spBuf.valueChanged.connect(lambda v: setattr(self,"_buffer_sec", float(v)) or self._emit_config()); rb.addWidget(self._spBuf)
        btn_reset = UiKit.make_btn("Reset buffer", role="danger", icon_sp=QStyle.SP_BrowserStop)
        btn_reset.clicked.connect(self._reset_state); rb.addWidget(btn_reset); rb.addStretch(1)
        bl.addLayout(rb)

        self._lbl_status = QLabel("Idle")

        root.addWidget(CollapsibleSection("Mode", gbM, collapsed=False))
        root.addWidget(CollapsibleSection("Sliding params", gbS, collapsed=False))
        root.addWidget(CollapsibleSection("Event-locked params", gbE, collapsed=True))
        root.addWidget(CollapsibleSection("Buffer & Control", gbB, collapsed=True))
        root.addWidget(self._lbl_status)

        return w

    # ---------------- CONFIG API ----------------
    def export_config(self) -> dict:
        """Compat BCI_Config → bloc 'epoch'."""
        mode = "sliding" if self._mode.lower().startswith("slid") else "event"
        cfg = {
            "mode": mode,
            "buffer_s": float(self._buffer_sec),
            "events_chunk_relative": bool(self._events_chunk_relative),
            "drop_incomplete": bool(self._drop_incomplete),
        }
        if mode == "sliding":
            cfg.update({"win_s": float(self._win_sec), "step_s": float(self._step_sec)})
        else:
            cfg.update({"pre_s": float(self._pre_sec), "post_s": float(self._post_sec)})
        return cfg

    def import_config(self, cfg: dict):
        """Tolère clés: win_s/step_s, pre_s/post_s, tmin/tmax, mode=sliding|event."""
        if not isinstance(cfg, dict):
            return
        # mode
        m = str(cfg.get("mode", self._mode)).lower()
        if "event" in m:
            self._mode = "Event-locked"
        elif "slid" in m:
            self._mode = "Sliding"

        # sliding
        if "win_s" in cfg:  self._win_sec  = float(cfg.get("win_s",  self._win_sec))
        if "step_s" in cfg: self._step_sec = float(cfg.get("step_s", self._step_sec))
        if "drop_incomplete" in cfg: self._drop_incomplete = bool(cfg.get("drop_incomplete"))

        # event: pre/post ou tmin/tmax
        if "pre_s" in cfg:   self._pre_sec  = float(cfg.get("pre_s",  self._pre_sec))
        if "post_s" in cfg:  self._post_sec = float(cfg.get("post_s", self._post_sec))
        if "tmin" in cfg or "tmax" in cfg:
            tmin = float(cfg.get("tmin", -self._pre_sec))
            tmax = float(cfg.get("tmax",  self._post_sec))
            # map: tmin (souvent négatif), tmax (positif)
            self._pre_sec  = float(abs(min(0.0, tmin)))
            self._post_sec = float(max(0.0, tmax))

        if "buffer_s" in cfg: self._buffer_sec = float(cfg.get("buffer_s", self._buffer_sec))
        if "events_chunk_relative" in cfg: self._events_chunk_relative = bool(cfg.get("events_chunk_relative"))

        # sync UI
        if _alive(self._cmb_mode): self._cmb_mode.setCurrentText(self._mode)
        if _alive(self._spL):      self._spL.setValue(self._win_sec)
        if _alive(self._spS):      self._spS.setValue(self._step_sec)
        if _alive(self._ck_drop):  self._ck_drop.setChecked(self._drop_incomplete)
        if _alive(self._spPre):    self._spPre.setValue(self._pre_sec)
        if _alive(self._spPost):   self._spPost.setValue(self._post_sec)
        if _alive(self._spBuf):    self._spBuf.setValue(self._buffer_sec)
        if _alive(self._ckRel):    self._ckRel.setChecked(self._events_chunk_relative)

        self._emit_config()

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------------- runtime ----------------
    def execute(self, **kw):
        # 🔸 appliquer config si présente (avec ou sans câbles)
        merged = {}
        if isinstance(kw.get("config_in"), dict):  merged.update(kw["config_in"])
        if isinstance(kw.get("epoch_conf"), dict): merged.update(kw["epoch_conf"])
        if merged: self.import_config(merged)

        # Reset?
        if kw.get("reset", None):
            self._reset_state()

        chunk = kw.get("chunk", None)
        fs    = kw.get("sfreq", None)
        chn   = kw.get("ch_names", None)
        evs   = kw.get("events", None)
        flush = bool(kw.get("flush", False))

        if chunk is None or fs is None:
            self._set_status("Waiting for chunk + sfreq"); return {}

        arr, was_T = _to_ns_nc(chunk)
        n_samp, n_ch = arr.shape

        if (self._fs is None) or (self._n_ch is None) or (self._n_ch != n_ch) or (self._was_T != was_T):
            self._fs = float(fs); self._n_ch = int(n_ch); self._was_T = was_T; self._ch_names = chn
            self._alloc_buffer()
            self._next_end = None
            if self._mode == "Sliding":
                self._next_end = self._g_end + int(round(self._win_sec * self._fs))

        if abs(float(fs) - float(self._fs)) > 1e-6:
            self._fs = float(fs)
            self._alloc_buffer(reinit=True)

        self._append_chunk(arr)

        if evs is not None:
            pos = evs.get("pos", []) or []
            typ = evs.get("typ", []) or []
            keep_types = self._parse_filter_types(self._ev_filter_text)
            for i in range(min(len(pos), len(typ))):
                p = int(pos[i])
                if self._events_chunk_relative:
                    p = self._g_end - arr.shape[0] + p
                t = int(typ[i])
                if (keep_types is None) or (t in keep_types):
                    if p >= self._buf_start_gidx:
                        self._ev_queue.append((p, t))

        emitted = 0
        if self._mode == "Sliding":
            emitted += self._emit_sliding(flush=flush)
        else:
            emitted += self._emit_event_locked(flush=flush)

        if emitted == 0:
            self._set_status(f"Buffered: {self._g_end} samp | mode={self._mode}")
        return {}

    # ---------------- buffer helpers ----------------
    def _alloc_buffer(self, reinit=False):
        cap = max(1, int(round(self._buffer_sec * float(self._fs or 1.0))))
        if (self._buf is None) or reinit or (self._buf.shape[0] != cap) or (self._buf.shape[1] != int(self._n_ch or 1)):
            self._buf = np.zeros((cap, int(self._n_ch or 1)), dtype=float)
            self._buf_len = 0
            self._buf_start_gidx = self._g_end
            self._epoch_idx = 0

    def _append_chunk(self, arr):
        n_samp = arr.shape[0]; cap = self._buf.shape[0]
        write_ptr = (self._g_end - self._buf_start_gidx) % cap
        if n_samp >= cap:
            arr = arr[-cap:, :]; n_samp = cap
        overflow = max(0, (self._g_end + n_samp) - (self._buf_start_gidx + cap))
        if overflow > 0:
            self._buf_start_gidx += overflow
            self._buf_len = max(0, self._buf_len - overflow)

        first = min(n_samp, cap - write_ptr)
        self._buf[write_ptr:write_ptr+first, :] = arr[:first, :]
        remain = n_samp - first
        if remain > 0:
            self._buf[0:remain, :] = arr[first:, :]

        self._g_end += n_samp
        self._buf_len = min(cap, self._buf_len + n_samp)

    def _slice_global(self, g0, g1):
        cap = self._buf.shape[0]
        if (g0 < self._buf_start_gidx) or (g1 > self._buf_start_gidx + self._buf_len):
            return None
        b0 = (g0 - self._buf_start_gidx) % cap
        length = g1 - g0
        if b0 + length <= cap:
            return self._buf[b0:b0+length, :].copy()
        else:
            first = cap - b0
            part1 = self._buf[b0:b0+first, :]
            part2 = self._buf[0:length-first, :]
            return np.vstack([part1, part2]).copy()

    # ---------------- emission ----------------
    def _emit_sliding(self, flush=False):
        fs = float(self._fs)
        win = max(1, int(round(self._win_sec * fs)))
        step = max(1, int(round(self._step_sec * fs)))
        if self._next_end is None:
            self._next_end = self._g_end
        emitted = 0
        while True:
            can_emit = (self._g_end >= self._next_end)
            if not can_emit and flush and (not self._drop_incomplete):
                if self._g_end - (self._next_end - win) > 0:
                    self._next_end = self._g_end
                    can_emit = True
            if not can_emit:
                break
            g1 = self._next_end; g0 = g1 - win
            if g0 < self._buf_start_gidx:
                self._next_end += step; continue
            seg = self._slice_global(g0, g1)
            if seg is None or (seg.shape[0] <= 0): break
            self._push_epoch(seg, {"mode":"Sliding", "t0":int(g0), "t1":int(g1), "end":int(self._g_end)})
            emitted += 1
            self._next_end += step
        if emitted > 0:
            self._set_status(f"Sliding emitted {emitted} | next_end={self._next_end} | g_end={self._g_end}")
        return emitted

    def _emit_event_locked(self, flush=False):
        fs = float(self._fs)
        pre  = max(0, int(round(self._pre_sec  * fs)))
        post = max(1, int(round(self._post_sec * fs)))
        emitted = 0
        i = 0
        while i < len(self._ev_queue):
            pos, typ = self._ev_queue[i]
            g0 = pos - pre; g1 = pos + post
            if (self._g_end < g1) and (not flush):
                i += 1; continue
            if g0 < self._buf_start_gidx:
                self._ev_queue.pop(i); continue
            seg = self._slice_global(g0, min(g1, self._g_end))
            if seg is None or seg.shape[0] <= 0 or (seg.shape[0] < (g1-g0) and not flush):
                i += 1; continue
            info = {"mode":"Event-locked","t0":int(g0),"t1":int(min(g1,self._g_end)),
                    "end":int(self._g_end),"event_type":int(typ),"event_pos":int(pos)}
            self._push_epoch(seg, info)
            emitted += 1
            self._ev_queue.pop(i)
        if emitted > 0:
            self._set_status(f"Event-locked emitted {emitted} | queue={len(self._ev_queue)} | g_end={self._g_end}")
        return emitted

    def _push_epoch(self, seg_ns_nc, info):
        out = _from_ns_nc(seg_ns_nc, self._was_T)
        info = dict(info)
        info["epoch_idx"] = int(self._epoch_idx); self._epoch_idx += 1
        self.outputs["segment"].on_next(out)
        self.outputs["sfreq"].on_next(float(self._fs))
        self.outputs["ch_names"].on_next(self._ch_names)
        self.outputs["epoch_info"].on_next(info)

    # ---------------- utils ----------------
    def _parse_filter_types(self, txt):
        t = (txt or "").strip()
        if not t: return None
        out=[]
        for s in t.split(","):
            s=s.strip()
            if not s: continue
            try: out.append(int(s))
            except: pass
        return set(out) if out else None

    def _reset_state(self):
        self._fs = self._fs if self._fs is not None else self.inputs["sfreq"].value
        self._n_ch = None
        self._buf = None
        self._buf_len = 0
        self._buf_start_gidx = 0
        self._g_end = 0
        self._epoch_idx = 0
        self._ev_queue.clear()
        self._next_end = None
        if _alive(self._lbl_status): self._lbl_status.setText("Reset.")

    def _set_status(self, msg):
        if _alive(self._lbl_status): self._lbl_status.setText(msg)
