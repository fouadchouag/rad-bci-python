# plugins/lsl_markers_inlet.py
# -*- coding: utf-8 -*-

import os, threading, time
from collections import deque
from rx.subject import BehaviorSubject

os.environ.setdefault("LSL_NO_IPV6", "1")

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QCheckBox,
    QSizePolicy, QStyle
)
from PyQt5.QtCore import QTimer
from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection

try:
    from pylsl import resolve_byprop, StreamInlet
    LSL_OK = True
except Exception:
    LSL_OK = False


class LSL_Markers_Inlet(BasePlugin):
    help = help = { 'gotchas': [ 'Resolves only LSL streams with type="Markers" (not EEG).',
               'Events are pulled one sample at a time and buffered; emitted in bursts on the QTimer tick.',
               'Network hiccups may cause gaps—use buffering.',
               'Auto-connect triggers after import_config if enabled.'],
  'inputs': { 'config_in': 'dict — merged configuration block (keys: emit_ms, auto_connect, stream_name)',
              'lsl_markers_conf': 'dict — markers-specific config (same keys as config_in, overrides config_in)'},
  'outputs': { 'config_out': 'dict — current configuration (emit_ms, auto_connect, stream_name)',
               'events': 'list[dict] — batch of events [{"ts": float, "code": str}, ...] since last tick',
               'last_event': 'dict — most recent event {"ts": float, "code": str}'},
  'parameters': [ { 'default': 20,
                     'desc': 'Interval between emit ticks in milliseconds',
                     'name': 'emit_ms',
                     'type': 'int'},
                   { 'default': False,
                     'desc': 'Automatically connect on config import',
                     'name': 'auto_connect',
                     'type': 'bool'}],
  'summary': 'Inlet LSL pour flux de marqueurs (strings).',
  'usage': 'Use the UI to refresh and connect to a Markers LSL stream, or send a config dict via config_in/lsl_markers_conf inputs to autoconnect programmatically.'}

    """
    Inlet LSL pour flux de marqueurs (strings).

    Entrées config :
      - config_in (dict)          ← config scène/BCI_Config
      - lsl_markers_conf (dict)   ← config spécifique

    Sorties:
      - events     : list[{'ts': float, 'code': str}]
      - last_event : {'ts': float, 'code': str}
      - config_out : dict (config courante)

    UI:
      - choix du stream (type='Markers'), refresh, connect/disconnect, emit_ms, Auto-connect
    """
    name = "LSL_Markers_Inlet"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        # data outs
        self.outputs["events"]     = BehaviorSubject(None)
        self.outputs["last_event"] = BehaviorSubject(None)
        # config pins
        self.inputs["config_in"]        = BehaviorSubject(None)
        self.inputs["lsl_markers_conf"] = BehaviorSubject(None)
        self.outputs["config_out"]      = BehaviorSubject(None)

        # state
        self._inlet = None
        self._reader = None
        self._run = False
        self._buf = deque()
        self._emit_ms = 20
        self._auto_connect = False
        self._preferred_name = None

        # ui refs
        self._combo = None
        self._lbl = None
        self._timer = None
        self._ck_auto = None

    # ---------- CONFIG API ----------
    def export_config(self) -> dict:
        return {
            "emit_ms": int(self._emit_ms),
            "auto_connect": bool(self._auto_connect),
            "stream_name": (str(self._preferred_name) if self._preferred_name else None)
        }

    def import_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        # Scene-style {"nodes": {"LSL_Markers_Inlet": {...}}}
        src = cfg
        nodes = cfg.get("nodes") if isinstance(cfg.get("nodes"), dict) else None
        if nodes and isinstance(nodes.get(self.name), dict):
            src = nodes[self.name]
        # flat block
        if "emit_ms" in src:
            self._emit_ms = int(src.get("emit_ms") or self._emit_ms)
            if self._timer:
                self._timer.setInterval(self._emit_ms)
        if "auto_connect" in src:
            self._auto_connect = bool(src.get("auto_connect"))
            if self._ck_auto:
                self._ck_auto.blockSignals(True)
                self._ck_auto.setChecked(self._auto_connect)
                self._ck_auto.blockSignals(False)
        if "stream_name" in src and src.get("stream_name"):
            self._preferred_name = str(src["stream_name"])
            # si dispo dans la combo, sélectionne-la
            if self._combo:
                idx = self._combo.findText(self._preferred_name)
                if idx >= 0:
                    self._combo.setCurrentIndex(idx)
        self._emit_config()
        # auto-connect si demandé
        if self._auto_connect and LSL_OK:
            QTimer.singleShot(150, self._maybe_autoconnect)

    def _emit_config(self):
        try:
            self.outputs["config_out"].on_next(self.export_config())
        except Exception:
            pass

    # ---------- UI ----------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        panel = QWidget(); v = QVBoxLayout(panel); v.setContentsMargins(8,8,8,8); v.setSpacing(6)

        r0 = QHBoxLayout()
        r0.addWidget(QLabel("Stream (type=Markers):"))
        self._combo = QComboBox(); r0.addWidget(self._combo, 1)
        btn_refresh = UiKit.make_btn("Refresh", role="ghost", icon_sp=QStyle.SP_BrowserReload)
        btn_refresh.clicked.connect(self._refresh_streams); r0.addWidget(btn_refresh)
        btn_conn = UiKit.make_btn("Connect", role="primary", icon_sp=QStyle.SP_DialogYesButton)
        btn_conn.clicked.connect(self._connect); r0.addWidget(btn_conn)
        btn_disc = UiKit.make_btn("Disconnect", role="danger", icon_sp=QStyle.SP_DialogCancelButton)
        btn_disc.clicked.connect(self._disconnect); r0.addWidget(btn_disc)
        v.addLayout(r0)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("emit [ms]:"))
        sp_emit = QSpinBox(); sp_emit.setRange(5, 500); sp_emit.setValue(self._emit_ms)
        sp_emit.valueChanged.connect(self._on_emit_ms_changed); r1.addWidget(sp_emit)

        self._ck_auto = QCheckBox("Auto-connect")
        self._ck_auto.setChecked(self._auto_connect)
        self._ck_auto.toggled.connect(lambda s: (setattr(self, "_auto_connect", bool(s)), self._emit_config()))
        r1.addWidget(self._ck_auto)

        r1.addStretch(1)
        v.addLayout(r1)

        self._lbl = QLabel("LSL: " + ("OK" if LSL_OK else "missing")); v.addWidget(self._lbl)
        root.addWidget(CollapsibleSection("LSL Markers Inlet", panel, collapsed=True))

        self._timer = QTimer(w)
        self._timer.timeout.connect(self._emit_tick)
        self._timer.start(self._emit_ms)

        self._refresh_streams()
        # tentative auto-connect (si config reçue ensuite, on re-tentera via import_config)
        QTimer.singleShot(150, self._maybe_autoconnect)
        return w

    def _on_emit_ms_changed(self, v):
        self._emit_ms = int(v)
        if self._timer:
            self._timer.setInterval(self._emit_ms)
        self._emit_config()

    # ---------- LSL ops ----------
    def _refresh_streams(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing. pip install pylsl")
            return
        try:
            infos = resolve_byprop('type', 'Markers', timeout=1.0)
            names = [inf.name() for inf in infos]
            self._combo.clear()
            if names:
                self._combo.addItems(names)
                # restore preferred
                if self._preferred_name and self._preferred_name in names:
                    self._combo.setCurrentText(self._preferred_name)
            else:
                self._combo.addItem("(no Markers streams)")
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Resolve error: {e}")

    def _maybe_autoconnect(self):
        if not self._auto_connect or not LSL_OK:
            return
        # préfère le nom configuré
        if self._preferred_name:
            idx = self._combo.findText(self._preferred_name)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._connect()

    def _connect(self):
        if not LSL_OK:
            if self._lbl: self._lbl.setText("pylsl missing.")
            return
        try:
            name = self._combo.currentText().strip()
            self._preferred_name = name if name and "(no Markers" not in name else None
            infos = resolve_byprop('name', self._preferred_name, timeout=1.5) if self._preferred_name else resolve_byprop('type','Markers',timeout=1.5)
            if not infos:
                if self._lbl: self._lbl.setText("No matching Markers stream.")
                return
            info = infos[0]
            self._inlet = StreamInlet(info, max_buflen=120, processing_flags=0)
            self._buf.clear()
            self._run = True
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            if self._lbl: self._lbl.setText(f"Connected to {info.name()}")
            self._emit_config()
        except Exception as e:
            if self._lbl: self._lbl.setText(f"Connect error: {e}")

    def _disconnect(self):
        self._run = False
        try:
            if self._reader and self._reader.is_alive():
                self._reader.join(timeout=0.5)
        except Exception:
            pass
        self._reader = None
        self._inlet = None
        if self._lbl: self._lbl.setText("Disconnected.")

    def _read_loop(self):
        while self._run and (self._inlet is not None):
            try:
                sample, ts = self._inlet.pull_sample(timeout=0.2)
                if sample is not None and ts is not None:
                    try:
                        code = str(sample[0])
                    except Exception:
                        code = str(sample)
                    self._buf.append({"ts": float(ts), "code": code})
                else:
                    time.sleep(0.002)
            except Exception:
                time.sleep(0.01)

    def _emit_tick(self):
        if not self._buf:
            return
        try:
            items = list(self._buf); self._buf.clear()
            self.outputs["events"].on_next(items)
            self.outputs["last_event"].on_next(items[-1])
        except Exception:
            pass

    # ---------- runtime ----------
    def execute(self, **kw):
        # merge config
        merged = {}
        for key in ("config_in", "lsl_markers_conf"):
            blk = kw.get(key, None)
            if isinstance(blk, dict):
                merged.update(blk)
        if merged:
            self.import_config(merged)
        return {}