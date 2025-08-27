# plugins/mne_ica_viewer.py
# -*- coding: utf-8 -*-
from typing import Any, Dict, Optional
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QDoubleSpinBox, QSpinBox, QCheckBox, QDialog, QScrollArea,
    QSizePolicy, QLayout
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

try:
    from core.collapsible import CollapsibleSection
except Exception:
    class CollapsibleSection(QWidget):
        def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
            super().__init__(parent)
            btn = QPushButton(title); btn.setCheckable(True); btn.setChecked(not collapsed)
            wrap = QWidget(); v = QVBoxLayout(wrap); v.setContentsMargins(0,0,0,0); v.addWidget(content or QWidget())
            root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.addWidget(btn); root.addWidget(wrap)
            btn.toggled.connect(wrap.setVisible); wrap.setVisible(btn.isChecked())

import mne


class MNEICAViewer(BasePlugin):
    name = "MNEICAViewer"
    language = "Python"
    category = "Visualization"
    supports_collapse = True

    def setup(self):
        self.inputs = {"ica": BehaviorSubject(None), "raw": BehaviorSubject(None)}
        self.outputs = {
            "ica": BehaviorSubject(None),
            "bad_components": BehaviorSubject(None),
            "raw": BehaviorSubject(None),
            "config_out": BehaviorSubject(None),
        }
        self._ica = None
        self._inst = None
        self._sel_idx = 0
        self._pending_draw = False
        self._cfg: Dict[str, Any] = {"preview_win_s": 5.0, "decim_ts": 4, "auto_apply": False}

        self._widget = None; self._list = None; self._lbl = None
        self._sp_win = None; self._sp_dec = None; self._chk_auto = None

        self._fig_topo = Figure(figsize=(3.2, 3.2)); self._ax_topo = self._fig_topo.add_subplot(111)
        self._cv_topo = FigureCanvas(self._fig_topo)
        self._fig_ts = Figure(figsize=(6.0, 2.4)); self._ax_ts = self._fig_ts.add_subplot(111)
        self._cv_ts = FigureCanvas(self._fig_ts)

        self._popup = None
        self._pop_fig_topo = None; self._pop_ax_topo = None; self._pop_cv_topo = None
        self._pop_fig_ts = None; self._pop_ax_ts = None; self._pop_cv_ts = None

        self._emit_config()

    # ----- config -----
    def export_config(self) -> dict: return dict(self._cfg)
    def import_config(self, cfg: dict):
        if isinstance(cfg, dict):
            for k in self._cfg: self._cfg[k] = cfg.get(k, self._cfg[k])
            self._sync_ui(); self._emit_config(); self._schedule_redraw()
    def config_hints(self) -> dict:
        return {"fields": {
            "preview_win_s": {"type":"float","min":1.0,"max":30.0,"step":0.5,"label":"Fenêtre (s) time-course"},
            "decim_ts": {"type":"int","min":1,"max":50,"label":"Décimation time-course"},
            "auto_apply": {"type":"bool","label":"Appliquer auto"},
        }, "_order": ["preview_win_s","decim_ts","auto_apply"]}
    def _emit_config(self):
        try: self.outputs["config_out"].on_next(self.export_config())
        except Exception: pass

    # ----- UI -----
    def build_widget(self) -> QWidget:
        if self._widget is not None: return self._widget
        w = QWidget(); w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root = QVBoxLayout(w); root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        panel = QWidget(); f = QFormLayout(panel)
        self._sp_win = QDoubleSpinBox(); self._sp_win.setRange(1.0,60.0); self._sp_win.setSingleStep(0.5)
        self._sp_win.setValue(float(self._cfg["preview_win_s"]))
        self._sp_win.valueChanged.connect(lambda v: self._on_cfg("preview_win_s", float(v)))
        f.addRow("Fenêtre time-course (s)", self._sp_win)
        self._sp_dec = QSpinBox(); self._sp_dec.setRange(1,50); self._sp_dec.setValue(int(self._cfg["decim_ts"]))
        self._sp_dec.valueChanged.connect(lambda v: self._on_cfg("decim_ts", int(v)))
        f.addRow("Décimation time-course", self._sp_dec)
        self._chk_auto = QCheckBox("Appliquer automatiquement")
        self._chk_auto.setChecked(bool(self._cfg["auto_apply"]))
        self._chk_auto.stateChanged.connect(lambda s: self._on_cfg("auto_apply", bool(s == Qt.Checked)))
        f.addRow("", self._chk_auto)

        r = QHBoxLayout()
        b_all = QPushButton("Tout sélectionner"); b_none = QPushButton("Tout désélectionner")
        b_apply = QPushButton("Appliquer → Raw (copy)"); b_big = QPushButton("Agrandir")
        b_all.clicked.connect(self._select_all); b_none.clicked.connect(self._select_none)
        b_apply.clicked.connect(self._apply_now); b_big.clicked.connect(self._show_large)
        r.addWidget(b_all); r.addWidget(b_none); r.addStretch(1); r.addWidget(b_apply); r.addWidget(b_big)

        self._list = QListWidget()
        self._list.itemChanged.connect(self._on_list_changed)
        self._list.currentRowChanged.connect(self._on_row_changed)
        self._lbl = QLabel("ICA: —")

        plots = QWidget(); pv = QVBoxLayout(plots); pv.setContentsMargins(0,0,0,0); pv.setSpacing(6)
        pv.addWidget(self._cv_topo, 0); pv.addWidget(self._cv_ts, 0)

        root.addWidget(CollapsibleSection("Paramètres", panel, collapsed=True))
        root.addLayout(r); root.addWidget(self._lbl); root.addWidget(self._list, 0); root.addWidget(plots, 0)
        self._widget = w; return w

    def _sync_ui(self):
        if self._sp_win: self._sp_win.blockSignals(True); self._sp_win.setValue(float(self._cfg["preview_win_s"])); self._sp_win.blockSignals(False)
        if self._sp_dec: self._sp_dec.blockSignals(True); self._sp_dec.setValue(int(self._cfg["decim_ts"])); self._sp_dec.blockSignals(False)
        if self._chk_auto: self._chk_auto.blockSignals(True); self._chk_auto.setChecked(bool(self._cfg["auto_apply"])); self._chk_auto.blockSignals(False)
    def _on_cfg(self, k, v): 
        self._cfg[k]=v; self._emit_config(); 
        if k in ("preview_win_s","decim_ts"): self._schedule_redraw()

    # ----- exec -----
    def execute(self, in_data=None, **kwargs):
        if in_data is None or not isinstance(in_data, dict): in_data={}
        if kwargs: in_data.update(kwargs)
        ica = in_data.get("ica", None); raw = in_data.get("raw", None)
        changed = False
        if ica is not None and ica is not self._ica: self._ica = ica; changed = True
        if raw is not None and raw is not self._inst: self._inst = raw; self._schedule_redraw()
        if changed: self._rebuild_list(); self._schedule_redraw()
        self._push_state()
        return {}

    # ----- helpers -----
    def _rebuild_list(self):
        if self._list is None: return
        self._list.blockSignals(True); self._list.clear()
        n = 0
        try:
            if self._ica is not None and hasattr(self._ica, "n_components_"): n = int(self._ica.n_components_)
        except Exception: n = 0
        for k in range(n):
            it = QListWidgetItem(f"IC {k}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            checked = Qt.Checked if (self._ica and hasattr(self._ica,"exclude") and (k in set(self._ica.exclude))) else Qt.Unchecked
            it.setCheckState(checked); self._list.addItem(it)
        self._list.blockSignals(False)
        self._sel_idx = 0; 
        if n>0: self._list.setCurrentRow(0)
        if self._lbl is not None: self._lbl.setText(f"ICA: {n} composantes" if n else "ICA: —")

    def _on_list_changed(self, _item):
        if self._ica is None: return
        ex = []
        for i in range(self._list.count()):
            if self._list.item(i).checkState() == Qt.Checked: ex.append(i)
        try: self._ica.exclude = sorted(list(set(int(i) for i in ex)))
        except Exception: pass
        self._push_state()
        if self._cfg.get("auto_apply", False): self._apply_now()
        else: self._schedule_redraw()

    def _on_row_changed(self, idx):
        if idx is None or idx < 0: return
        self._sel_idx = int(idx); self._schedule_redraw()

    # ----- montage helper + topomap (identique à ta version) -----
    def _info_with_default_montage(self, info):
        if info is None: return None
        try:
            info2 = info.copy()
            has_pos = any(ch.get('loc', None) is not None and np.any(np.asarray(ch['loc']) != 0) for ch in info2['chs'])
            if has_pos: return info2
            for mname in ("standard_1020", "standard_1005"):
                try:
                    montage = mne.channels.make_standard_montage(mname)
                    info2.set_montage(montage, on_missing='ignore')
                    has_pos2 = any(ch.get('loc', None) is not None and np.any(np.asarray(ch['loc']) != 0) for ch in info2['chs'])
                    if has_pos2: return info2
                except Exception:
                    continue
            return info2
        except Exception:
            return info

    def _draw_topomap(self, comp_idx: int):
        self._ax_topo.clear()
        vals, info = self._get_topomap_data(comp_idx)
        if vals is None or info is None:
            self._ax_topo.set_title("Topomap indisponible"); self._cv_topo.draw(); return
        info2 = self._info_with_default_montage(info)
        try:
            mne.viz.plot_topomap(vals, info2, axes=self._ax_topo, show=False)
            self._ax_topo.set_title(f"IC {comp_idx} — topomap")
        except Exception:
            idx = np.argsort(np.abs(vals))[::-1][:min(20, len(vals))]
            self._ax_topo.bar(range(len(idx)), vals[idx])
            try: ch_names = [ch['ch_name'] for ch in info2['chs']]
            except Exception: ch_names = [f"ch{i+1}" for i in range(len(vals))]
            self._ax_topo.set_xticks(range(len(idx)))
            self._ax_topo.set_xticklabels([ch_names[i] for i in idx], rotation=70, fontsize=8)
            self._ax_topo.set_title(f"IC {comp_idx} — poids (fallback)")
        self._fig_topo.tight_layout(); self._cv_topo.draw()

    def _get_topomap_data(self, comp_idx: int):
        if self._ica is None: return None, None
        try:
            W = self._ica.get_components()
            if W is None or W.ndim != 2: return None, None
            if comp_idx < 0 or comp_idx >= W.shape[1]: return None, None
            vals = W[:, comp_idx]
            info = getattr(self._ica, "info", None)
            if info is None and self._inst is not None: info = getattr(self._inst, "info", None)
            return vals, info
        except Exception:
            return None, None

    # ----- séries IC robustes (Raw / Epochs, sans kwargs) -----
    def _get_ic_series(self, comp_idx: int):
        """Retourne (x, t, fs) pour la composante comp_idx, en ne chargeant
        qu'un petit bout du signal (évite le blocage sur GDF très longs)."""
        if self._ica is None or self._inst is None:
            return None, None, None
        try:
            src = self._ica.get_sources(self._inst)  # pas de kwargs
            # Fréquence d'échantillonnage
            fs = None
            if hasattr(src, "info") and isinstance(src.info, dict) and "sfreq" in src.info:
                try:
                    fs = float(src.info["sfreq"])
                except Exception:
                    fs = None

            # Fenêtre d'aperçu + petite marge, avec un plafond de sécurité
            win = max(1.0, float(self._cfg.get("preview_win_s", 5.0)))
            margin_s = 2.0
            max_s = float(self._cfg.get("preview_max_s", 20.0))  # option cachée (pas de widget)
            if fs and fs > 0:
                N = int(round(min(max_s, win + margin_s) * fs))
            else:
                N = 5000  # repli

            # Récupération partielle des données
            if hasattr(src, "get_data"):
                try:
                    arr = src.get_data(start=0, stop=N)
                except TypeError:
                    # Anciennes versions MNE sans start/stop -> fallback (plus lourd)
                    arr = src.get_data()
            elif hasattr(src, "_data"):
                arr = src._data
                # Tronquer si nécessaire
                if arr.ndim == 2 and arr.shape[1] > N:
                    arr = arr[:, :N]
                elif arr.ndim == 3 and arr.shape[2] > N:
                    arr = arr[:, :, :N]
            else:
                return None, None, None

            arr = np.asarray(arr)

            # Raw: (n_ic, n_times) ; Epochs: (n_epochs, n_ic, n_times)
            if arr.ndim == 2:
                n_ic = arr.shape[0]
                k = comp_idx if 0 <= comp_idx < n_ic else 0
                x = arr[k]
            elif arr.ndim == 3:
                n_ep, n_ic, _ = arr.shape
                k = comp_idx if 0 <= comp_idx < n_ic else 0
                x = arr[0, k] if n_ep > 0 else arr.mean(axis=0)[k]
            else:
                return None, None, None

            # Times alignés
            t = getattr(src, "times", None)
            if t is not None:
                t = np.asarray(t).ravel()
                # Tronquer t si plus long que x
                if t.size > x.size:
                    t = t[:x.size]
                elif t.size < x.size and fs:
                    # re-génère si incohérent
                    t = np.arange(x.size, dtype=float) / float(fs)
            else:
                t = (np.arange(x.size, dtype=float) / float(fs)) if (fs and fs > 0) else np.arange(x.size, dtype=float)

            return x, t, fs
        except Exception:
            return None, None, None


    def _draw_timeseries(self, comp_idx: int):
        self._ax_ts.clear()
        x, t, fs = self._get_ic_series(comp_idx)
        if x is None:
            self._ax_ts.set_title("Time-course indisponible"); self._cv_ts.draw(); return
        win = max(1.0, float(self._cfg.get("preview_win_s", 5.0)))
        if fs and fs > 0:
            N = int(round(win * fs))
            x = x[:N]; t = t[:N]
        dec = max(1, int(self._cfg.get("decim_ts", 4)))
        self._ax_ts.plot(t[::dec], x[::dec], linewidth=0.8)
        self._ax_ts.set_xlabel("Temps (s)"); self._ax_ts.set_ylabel("a.u.")
        self._ax_ts.set_title(f"IC {comp_idx} — {win:.1f}s")
        self._fig_ts.tight_layout(); self._cv_ts.draw()

    def _redraw(self):
        self._pending_draw = False
        if self._ica is None:
            self._ax_topo.clear(); self._ax_topo.set_title("ICA non connecté"); self._cv_topo.draw()
            self._ax_ts.clear(); self._ax_ts.set_title("Time-course: —"); self._cv_ts.draw()
            return
        k = int(self._sel_idx or 0)
        self._draw_topomap(k)
        self._draw_timeseries(k)
        if self._popup is not None:
            self._draw_topomap_big(k); self._draw_timeseries_big(k)

    def _schedule_redraw(self):
        if self._pending_draw: return
        self._pending_draw = True; QTimer.singleShot(0, self._redraw)

    def _push_state(self):
        try:
            ex = list(getattr(self._ica, "exclude", [])) if self._ica is not None else None
            self.outputs["ica"].on_next(self._ica); self.outputs["bad_components"].on_next(ex)
        except Exception: pass

    # ----- actions -----
    def _select_all(self):
        if not self._list: return
        self._list.blockSignals(True)
        for i in range(self._list.count()): self._list.item(i).setCheckState(Qt.Checked)
        self._list.blockSignals(False); self._on_list_changed(None)

    def _select_none(self):
        if not self._list: return
        self._list.blockSignals(True)
        for i in range(self._list.count()): self._list.item(i).setCheckState(Qt.Unchecked)
        self._list.blockSignals(False); self._on_list_changed(None)

    def _apply_now(self):
        if self._inst is None or self._ica is None:
            self.outputs["raw"].on_next(None); return
        try:
            out = self._inst.copy(); self._ica.apply(out)   # pas d'args kw
            self.outputs["raw"].on_next(out)
        except Exception as e:
            print(f"[MNEICAViewer] Apply error: {e}"); self.outputs["raw"].on_next(None)

    # ----- vue agrandie -----
    def _show_large(self):
        if self._popup is not None:
            try: self._popup.close()
            except Exception: pass
            self._popup = None
        dlg = QDialog(); dlg.setWindowTitle("ICA — Vue agrandie")
        layout = QVBoxLayout(dlg)
        scroller = QScrollArea(); scroller.setWidgetResizable(True); layout.addWidget(scroller, 1)
        content = QWidget(); cv = QVBoxLayout(content); cv.setContentsMargins(12,12,12,12); cv.setSpacing(8)

        self._pop_fig_topo = Figure(figsize=(6.0, 6.0))
        self._pop_ax_topo = self._pop_fig_topo.add_subplot(111)
        self._pop_cv_topo = FigureCanvas(self._pop_fig_topo); cv.addWidget(self._pop_cv_topo)

        self._pop_fig_ts = Figure(figsize=(10.0, 3.0))
        self._pop_ax_ts = self._pop_fig_ts.add_subplot(111)
        self._pop_cv_ts = FigureCanvas(self._pop_fig_ts); cv.addWidget(self._pop_cv_ts)

        scroller.setWidget(content); dlg.setLayout(layout); dlg.resize(1100, 900)
        self._popup = dlg

        def _on_close(*_):
            self._popup = None
            self._pop_fig_topo = None; self._pop_ax_topo = None; self._pop_cv_topo = None
            self._pop_fig_ts = None; self._pop_ax_ts = None; self._pop_cv_ts = None

        dlg.finished.connect(_on_close); dlg.show(); self._redraw()

    def _draw_topomap_big(self, comp_idx: int):
        if self._pop_ax_topo is None or self._pop_cv_topo is None: return
        self._pop_ax_topo.clear()
        vals, info = self._get_topomap_data(comp_idx)
        if vals is None or info is None:
            self._pop_ax_topo.set_title("Topomap indisponible"); self._pop_cv_topo.draw(); return
        info2 = self._info_with_default_montage(info)
        try:
            mne.viz.plot_topomap(vals, info2, axes=self._pop_ax_topo, show=False)
            self._pop_ax_topo.set_title(f"IC {comp_idx} — topomap (large)")
        except Exception:
            idx = np.argsort(np.abs(vals))[::-1][:min(40, len(vals))]
            self._pop_ax_topo.bar(range(len(idx)), vals[idx])
            try: ch_names = [ch['ch_name'] for ch in info2['chs']]
            except Exception: ch_names = [f"ch{i+1}" for i in range(len(vals))]
            self._pop_ax_topo.set_xticks(range(len(idx)))
            self._pop_ax_topo.set_xticklabels([ch_names[i] for i in idx], rotation=70, fontsize=8)
            self._pop_ax_topo.set_title(f"IC {comp_idx} — poids (fallback large)")
        self._pop_fig_topo.tight_layout(); self._pop_cv_topo.draw()

    def _draw_timeseries_big(self, comp_idx: int):
        if self._pop_ax_ts is None or self._pop_cv_ts is None: return
        self._pop_ax_ts.clear()
        x, t, fs = self._get_ic_series(comp_idx)
        if x is None:
            self._pop_ax_ts.set_title("Time-course indisponible"); self._pop_cv_ts.draw(); return
        win = max(1.0, float(self._cfg.get("preview_win_s", 5.0)))
        if fs and fs > 0:
            N = int(round(win * fs)); x = x[:N]; t = t[:N]
        dec = max(1, int(self._cfg.get("decim_ts", 4)))
        self._pop_ax_ts.plot(t[::dec], x[::dec], linewidth=0.9)
        self._pop_ax_ts.set_xlabel("Temps (s)"); self._pop_ax_ts.set_ylabel("a.u.")
        self._pop_ax_ts.set_title(f"IC {comp_idx} — {win:.1f}s (large)")
        self._pop_fig_ts.tight_layout(); self._pop_cv_ts.draw()

    def on_remove(self):
        try: self.outputs["ica"].on_next(self._ica); self.outputs["bad_components"].on_next(list(getattr(self._ica,"exclude",[])) if self._ica else None)
        except Exception: pass
        try: self.outputs["raw"].on_next(None)
        except Exception: pass
        if self._popup is not None:
            try: self._popup.close()
            except Exception: pass
        self._popup = None
