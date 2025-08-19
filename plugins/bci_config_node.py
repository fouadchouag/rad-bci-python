# plugins/bci_config_node.py
# -*- coding: utf-8 -*-

import gc, os, json, weakref
from typing import Dict, Any, Tuple, List

from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QLineEdit, QFormLayout, QCheckBox, QSpinBox,
    QDoubleSpinBox, QComboBox, QFileDialog, QSizePolicy, QStyle, QScrollArea,
    QDialog, QTextEdit, QDialogButtonBox
)
from PyQt5.QtCore import Qt

from core.node_base import BasePlugin
from core.ui_kit import UiKit
from core.collapsible import CollapsibleSection


# ---------- utils ----------
def _flatten(d: dict, parent="", sep="."):
    flat = {}
    for k, v in (d or {}).items():
        key = f"{parent}{sep}{k}" if parent else str(k)
        if isinstance(v, dict):
            flat.update(_flatten(v, key, sep))
        else:
            flat[key] = v
    return flat

def _unflatten(flat: dict, sep="."):
    root = {}
    for k, v in (flat or {}).items():
        parts = str(k).split(sep)
        cur = root
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return root

def _flatten_hints(hints: dict, parent="", sep="."):
    """Accepte {'fields':{...}} ou un dict aligné avec la config. Retourne {dotkey: meta}."""
    if not isinstance(hints, dict):
        return {}
    fields = hints.get("fields") if "fields" in hints else hints
    out = {}
    for k, v in (fields or {}).items():
        key = f"{parent}{sep}{k}" if parent else str(k)
        if isinstance(v, dict) and "type" not in v and "enum" not in v and "help" not in v:
            out.update(_flatten_hints(v, key, sep))
        else:
            out[key] = v or {}
    return out

def _value_to_str(x):
    if isinstance(x, (list, tuple)):
        return ",".join(str(i) for i in x)
    return str(x)


class BCI_ConfigNode(BasePlugin):
    """
    Config manager « no-code » :
      • Scan des nœuds (export_config / config_out)
      • Édition conviviale (auto-UI, hints : min/max/step/enum/help)
      • Preview/Revert/Apply (selected | class | all)
      • Presets Save/Load (tolérant aux IDs qui changent)

    Entrées:
      - config_in : dict (preset à appliquer)
    Sorties:
      - config_out : dict (dernier preset appliqué)
    """
    name = "BCI_Config"
    language = "Python"
    category = "BCI/Utils"

    # ---------------- lifecycle ----------------
    def setup(self):
        self.inputs["config_in"]   = BehaviorSubject(None)
        self.outputs["config_out"] = BehaviorSubject(None)

        # workflow state
        self._nodes_by_key: Dict[str, weakref.ref] = {}   # "Class@id" -> weakref(plugin)
        self._cfg_cache: Dict[str, dict] = {}             # "Class@id" -> {"class","plugin_name","config":{...}}
        self._current_key: str = None
        self._apply_target = "selected"                   # selected | class | all

        # per-selection state
        self._widget_map: Dict[str, QWidget] = {}         # dotkey -> editor
        self._row_labels: Dict[str, QLabel]  = {}         # dotkey -> label (pour hide/filter)
        self._orig_cfg_flat: Dict[str, Any]  = {}         # dotkey -> original value
        self._hints_flat: Dict[str, dict]    = {}         # dotkey -> hints

        # UI refs
        self._lbl = None
        self._search_node = None
        self._search_param = None
        self._list = None
        self._form = None
        self._form_scroll = None
        self._cmb_target = None
        self._btn_preview = None
        self._btn_revert = None

    # ------------ helpers: runtime map ------------
    def _refresh_nodes_map(self):
        """Recharge la carte runtime {Class@id -> weakref(node)} sans toucher à la UI."""
        self._nodes_by_key.clear()
        try:
            for node in self._enumerate_plugins():
                key = self._node_key(node)
                self._nodes_by_key[key] = weakref.ref(node)
        except Exception:
            pass

    # ------------ build UI ------------
    def build_widget(self):
        w = QWidget(); UiKit.apply_node_style(w)
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        root = QVBoxLayout(w); root.setContentsMargins(6,6,6,6); root.setSpacing(8)

        # ---- header cmds ----
        cmd = QWidget(); c = QHBoxLayout(cmd); c.setContentsMargins(8,8,8,8); c.setSpacing(6)
        btn_scan = UiKit.make_btn("Scan workflow", role="primary", icon_sp=QStyle.SP_BrowserReload)
        btn_scan.clicked.connect(self._on_scan); c.addWidget(btn_scan)

        c.addSpacing(8)
        c.addWidget(QLabel("Apply to:"))
        self._cmb_target = QComboBox(); self._cmb_target.addItems(["selected","class","all"])
        self._cmb_target.currentTextChanged.connect(lambda s: setattr(self, "_apply_target", s))
        c.addWidget(self._cmb_target)

        self._btn_preview = UiKit.make_btn("Preview", role="ghost", icon_sp=QStyle.SP_MessageBoxInformation)
        self._btn_preview.clicked.connect(self._on_preview_clicked); c.addWidget(self._btn_preview)

        self._btn_revert = UiKit.make_btn("Revert", role="danger", icon_sp=QStyle.SP_BrowserStop)
        self._btn_revert.clicked.connect(self._on_revert_clicked); c.addWidget(self._btn_revert)

        btn_apply = UiKit.make_btn("Apply changes", role="success", icon_sp=QStyle.SP_DialogApplyButton)
        btn_apply.clicked.connect(self._on_apply_clicked); c.addWidget(btn_apply)

        c.addSpacing(12)
        btn_load = UiKit.make_btn("Load preset…", role="ghost", icon_sp=QStyle.SP_DialogOpenButton)
        btn_load.clicked.connect(self._on_load_preset); c.addWidget(btn_load)
        btn_save = UiKit.make_btn("Save preset…", role="ghost", icon_sp=QStyle.SP_DialogSaveButton)
        btn_save.clicked.connect(self._on_save_preset); c.addWidget(btn_save)

        c.addStretch(1)
        root.addWidget(CollapsibleSection("Workflow Config (friendly UI)", cmd, collapsed=False))

        # ---- middle: list + form ----
        mid = QWidget(); m = QHBoxLayout(mid); m.setContentsMargins(0,0,0,0); m.setSpacing(8)

        # left column
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0,0,0,0); lv.setSpacing(6)
        self._search_node = QLineEdit(); self._search_node.setPlaceholderText("Rechercher un nœud…")
        self._search_node.textChanged.connect(self._filter_nodes)
        lv.addWidget(self._search_node)

        self._list = QListWidget(); self._list.itemSelectionChanged.connect(self._on_select_node)
        self._list.setMinimumWidth(280)
        lv.addWidget(self._list, 1)
        m.addWidget(left, 0)

        # right column
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0,0,0,0); rv.setSpacing(6)

        # param search
        self._search_param = QLineEdit(); self._search_param.setPlaceholderText("Filtrer les paramètres…")
        self._search_param.textChanged.connect(self._filter_params)
        rv.addWidget(self._search_param)

        # form (scrollable)
        self._form_scroll = QScrollArea(); self._form_scroll.setWidgetResizable(True)
        form_container = QWidget(); self._form = QFormLayout(form_container)
        self._form.setLabelAlignment(Qt.AlignRight); self._form.setFormAlignment(Qt.AlignTop)
        self._form_scroll.setWidget(form_container)
        rv.addWidget(self._form_scroll, 1)

        self._lbl = QLabel("Clique sur « Scan workflow », puis sélectionne un nœud à modifier.")
        rv.addWidget(self._lbl)

        m.addWidget(right, 1)
        root.addWidget(mid, 1)
        return w

    # ---------------- runtime ----------------
    def execute(self, **kw):
        preset = kw.get("config_in", None)
        if isinstance(preset, dict) and preset:
            self._apply_preset_dict(preset)
        return {}

    # ---------------- actions ----------------
    def _on_scan(self):
        self._nodes_by_key.clear()
        self._cfg_cache.clear()
        self._list.clear()
        count = 0
        for node in self._enumerate_plugins():
            key = self._node_key(node)
            cfg = self._read_config(node) or {}
            self._nodes_by_key[key] = weakref.ref(node)
            self._cfg_cache[key] = cfg
            title = cfg.get("plugin_name", getattr(node, "name", type(node).__name__))
            it = QListWidgetItem(f"{title} — {type(node).__name__} @{id(node)}")
            it.setData(Qt.UserRole, key)
            self._list.addItem(it); count += 1
        self._lbl.setText(f"Scanned {count} nodes. Select one to edit.")
        if count: self._list.setCurrentRow(0)

    def _on_select_node(self):
        items = self._list.selectedItems()
        self._clear_form()
        self._orig_cfg_flat.clear()
        self._hints_flat.clear()
        if not items:
            self._current_key = None
            self._lbl.setText("No node selected.")
            return
        key = items[0].data(Qt.UserRole)
        self._current_key = key
        node = self._node_from_key(key)
        cfg = (self._cfg_cache.get(key, {}) or {}).get("config", {})
        hints = self._read_hints(node)
        self._hints_flat = _flatten_hints(hints)
        self._build_form_from_config(cfg)
        self._lbl.setText(f"Editing: {key}")

    def _on_apply_clicked(self):
        if self._apply_target == "selected":
            self._apply_selected()
        elif self._apply_target == "class":
            self._apply_class()
        else:
            self._apply_all()

    def _on_revert_clicked(self):
        if not self._current_key:
            self._lbl.setText("No node selected.")
            return
        node = self._node_from_key(self._current_key)
        fresh = self._read_config(node).get("config", {})
        self._build_form_from_config(fresh)
        self._lbl.setText("Reverted to node values.")

    def _on_preview_clicked(self):
        cfg_new = self._collect_form_values()
        diff = self._diff_with_original(cfg_new)
        self._show_diff_dialog(diff)

    def _on_save_preset(self):
        preset = self._make_preset_from_cache()
        if not preset:
            self._lbl.setText("Nothing to save.")
            return
        path, _ = QFileDialog.getSaveFileName(None, "Save preset", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(preset, f, indent=2, ensure_ascii=False)
            self._lbl.setText(f"Preset saved: {os.path.basename(path)}")
        except Exception as e:
            self._lbl.setText(f"Save error: {e}")

    def _on_load_preset(self):
        path, _ = QFileDialog.getOpenFileName(None, "Load preset", "", "JSON (*.json)")
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                preset = json.load(f)
            if isinstance(preset, dict):
                # si l'utilisateur est en "selected" sans sélection, basculer en "all" pour être utile
                if self._apply_target == "selected" and not self._current_key:
                    self._apply_target = "all"
                    if self._cmb_target:
                        self._cmb_target.blockSignals(True)
                        self._cmb_target.setCurrentText("all")
                        self._cmb_target.blockSignals(False)
                self._apply_preset_dict(preset)
                self.outputs["config_out"].on_next(preset)
                self._lbl.setText(f"Preset loaded & applied ({self._apply_target}).")
        except Exception as e:
            self._lbl.setText(f"Load error: {e}")

    # ---------------- helpers: apply ----------------
    def _apply_selected(self):
        if not self._current_key:
            self._lbl.setText("No node selected.")
            return
        cfg = self._collect_form_values()
        self._refresh_nodes_map()
        if self._apply_config_to_key(self._current_key, cfg):
            self._cfg_cache[self._current_key] = {
                "class": self._current_key.split("@",1)[0],
                "plugin_name": self._current_key,
                "config": cfg
            }
            self.outputs["config_out"].on_next({"nodes": { self._current_key: self._cfg_cache[self._current_key] }})
            self._lbl.setText("Applied to selected node.")
            self._build_form_from_config(cfg)
        else:
            self._lbl.setText("Apply failed for selected node.")

    def _apply_class(self):
        if not self._current_key:
            self._lbl.setText("No node selected.")
            return
        cfg = self._collect_form_values()
        cls = self._current_key.split("@",1)[0]
        self._refresh_nodes_map()
        blob = {}; applied = 0
        for key in list(self._nodes_by_key.keys()):
            if key.startswith(cls+"@") and self._apply_config_to_key(key, cfg):
                self._cfg_cache[key] = {"class": cls, "plugin_name": key, "config": cfg}
                blob[key] = self._cfg_cache[key]; applied += 1
        if applied:
            self.outputs["config_out"].on_next({"nodes": blob})
        self._lbl.setText(f"Applied to class '{cls}' ({applied} nodes).")
        if self._current_key in blob:
            self._build_form_from_config(cfg)

    def _apply_all(self):
        self._refresh_nodes_map()
        cfg = self._collect_form_values() if self._current_key else None
        blob = {}; applied = 0
        for key in list(self._nodes_by_key.keys()):
            c = cfg if cfg is not None else (self._cfg_cache.get(key, {}) or {}).get("config", {})
            if self._apply_config_to_key(key, c):
                self._cfg_cache[key] = {"class": key.split("@",1)[0], "plugin_name": key, "config": c}
                blob[key] = self._cfg_cache[key]; applied += 1
        if applied:
            self.outputs["config_out"].on_next({"nodes": blob})
        self._lbl.setText(f"Applied to all ({applied} nodes).")
        if self._current_key and self._current_key in blob:
            self._build_form_from_config(blob[self._current_key]["config"])

    def _apply_preset_dict(self, preset: dict):
        """Applique un preset en étant tolérant aux IDs (fallback par classe)."""
        # s'assurer qu'on a la carte runtime
        self._refresh_nodes_map()

        nodes = preset.get("nodes")
        if nodes is None and isinstance(preset, dict):
            nodes = {k: (v if isinstance(v, dict) and "config" in v else {"config": v})
                     for k, v in preset.items()}
        if not isinstance(nodes, dict):
            return

        blob = {}; applied = 0

        def _keys_for_class(cls: str) -> List[str]:
            return [k for k in self._nodes_by_key.keys() if k.startswith(cls + "@")]

        if self._apply_target == "selected" and self._current_key:
            # 1) exact
            info = nodes.get(self._current_key)
            if info is None:
                # 2) par classe
                cls = self._current_key.split("@",1)[0]
                # chercher une entrée du preset qui correspond à cette classe
                for k, inf in nodes.items():
                    kcls = str(k).split("@",1)[0]
                    if kcls == cls:
                        info = inf; break
            if info:
                cfg = info.get("config", {})
                if self._apply_config_to_key(self._current_key, cfg):
                    cls = self._current_key.split("@",1)[0]
                    self._cfg_cache[self._current_key] = {"class": cls, "plugin_name": self._current_key, "config": cfg}
                    blob[self._current_key] = self._cfg_cache[self._current_key]; applied += 1
                    self._build_form_from_config(cfg)

        elif self._apply_target == "class" and self._current_key:
            cls = self._current_key.split("@",1)[0]
            # trouver une config de référence pour cette classe dans le preset
            cfg_ref = None
            # 1) essayer key exacte
            info = nodes.get(self._current_key)
            if info: cfg_ref = info.get("config", {})
            # 2) sinon la première entrée de la même classe
            if cfg_ref is None:
                for k, inf in nodes.items():
                    if str(k).split("@",1)[0] == cls:
                        cfg_ref = inf.get("config", {}); break
            cfg_ref = cfg_ref or {}
            for key in _keys_for_class(cls):
                if self._apply_config_to_key(key, cfg_ref):
                    self._cfg_cache[key] = {"class": cls, "plugin_name": key, "config": cfg_ref}
                    blob[key] = self._cfg_cache[key]; applied += 1
            if self._current_key in blob:
                self._build_form_from_config(cfg_ref)

        else:
            # ALL : pour chaque entrée du preset, appliquer à tous les nœuds de cette classe
            for k, info in nodes.items():
                cfg = info.get("config", {})
                cls = info.get("class") or str(k).split("@",1)[0]
                for key in _keys_for_class(cls):
                    if self._apply_config_to_key(key, cfg):
                        self._cfg_cache[key] = {"class": cls, "plugin_name": key, "config": cfg}
                        blob[key] = self._cfg_cache[key]; applied += 1
            # si on est en train d'éditer un nœud présent dans blob, rafraîchir la vue
            if self._current_key and self._current_key in blob:
                self._build_form_from_config(blob[self._current_key]["config"])

        if applied:
            self.outputs["config_out"].on_next({"nodes": blob})
        self._lbl.setText(f"Preset applied ({self._apply_target}): {applied} node(s).")

    # ---------------- form build / edit ----------------
    def _clear_form(self):
        self._widget_map.clear()
        self._row_labels.clear()
        while self._form.count():
            it = self._form.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

    def _build_form_from_config(self, cfg: dict):
        self._clear_form()
        flat = _flatten(cfg)
        self._orig_cfg_flat = flat.copy()
        if not flat:
            self._form.addRow(QLabel("<i>No parameters found for this node.</i>"))
            return

        order = None
        try:
            order = self._read_order_from_hints(self._hints_flat)
        except Exception:
            order = None

        keys = list(flat.keys())
        if order:
            keys.sort(key=lambda k: (order.index(k) if k in order else len(order), k.lower()))
        else:
            keys.sort(key=str.lower)

        for k in keys:
            v = flat[k]
            meta = self._hints_flat.get(k, {}) if isinstance(self._hints_flat, dict) else {}
            label_txt = meta.get("label", k)
            help_txt  = meta.get("help", None)

            editor = self._make_editor(k, v, meta)
            lbl = QLabel(label_txt)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if help_txt:
                lbl.setToolTip(help_txt)
                editor.setToolTip(help_txt)

            self._form.addRow(lbl, editor)
            self._widget_map[k] = editor
            self._row_labels[k] = lbl
            self._connect_change_signal(k, editor)

        if self._search_param: self._search_param.setText("")

    def _make_editor(self, key: str, val: Any, meta: dict) -> QWidget:
        if isinstance(meta, dict) and "enum" in meta and isinstance(meta["enum"], (list, tuple)):
            combo = QComboBox()
            labels = meta.get("labels")
            for i, opt in enumerate(meta["enum"]):
                text = str(labels[i]) if isinstance(labels, (list, tuple)) and i < len(labels) else str(opt)
                combo.addItem(text, opt)
            idx = max(0, combo.findData(val))
            combo.setCurrentIndex(idx)
            return combo

        if isinstance(val, bool):
            cb = QCheckBox(); cb.setChecked(val)
            return cb

        if isinstance(val, int) and not isinstance(val, bool):
            sp = QSpinBox()
            sp.setRange(int(meta.get("min", -1_000_000_000)), int(meta.get("max", 1_000_000_000)))
            step = int(meta.get("step", 1))
            sp.setSingleStep(step if step != 0 else 1)
            sp.setValue(int(val))
            return sp

        if isinstance(val, float):
            ds = QDoubleSpinBox()
            ds.setDecimals(int(meta.get("decimals", 6)))
            ds.setRange(float(meta.get("min", -1e9)), float(meta.get("max", 1e9)))
            ds.setSingleStep(float(meta.get("step", 0.1)))
            ds.setValue(float(val))
            return ds

        if isinstance(val, (list, tuple)):
            le = QLineEdit(_value_to_str(val)); le.setPlaceholderText("csv, p.ex. 8,12,30")
            return le

        le = QLineEdit(str(val))
        ph = meta.get("placeholder")
        if isinstance(ph, str): le.setPlaceholderText(ph)
        return le

    def _connect_change_signal(self, key: str, editor: QWidget):
        def mark():
            self._highlight_if_changed(key)
        if isinstance(editor, QCheckBox):
            editor.toggled.connect(lambda _s: mark())
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.valueChanged.connect(lambda _v: mark())
        elif isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(lambda _i: mark())
        elif isinstance(editor, QLineEdit):
            editor.textChanged.connect(lambda _t: mark())
        mark()

    def _editor_value(self, editor: QWidget):
        if isinstance(editor, QCheckBox):
            return bool(editor.isChecked())
        if isinstance(editor, QSpinBox):
            return int(editor.value())
        if isinstance(editor, QDoubleSpinBox):
            return float(editor.value())
        if isinstance(editor, QComboBox):
            return editor.currentData()
        if isinstance(editor, QLineEdit):
            text = editor.text()
            if "," in text:
                parts = [p.strip() for p in text.split(",") if p.strip()!=""]
                nums, ok = [], True
                for p in parts:
                    try:
                        if "." in p or "e" in p.lower():
                            nums.append(float(p))
                        else:
                            nums.append(int(p))
                    except Exception:
                        ok = False; break
                return nums if ok else parts
            try:
                if text.strip()=="":
                    return ""
                if "." in text or "e" in text.lower():
                    return float(text)
                return int(text)
            except Exception:
                return text
        return None

    def _collect_form_values(self) -> dict:
        flat = {}
        for k, w in self._widget_map.items():
            flat[k] = self._editor_value(w)
        return _unflatten(flat)

    # ---------------- filtering ----------------
    def _filter_nodes(self, text: str):
        t = (text or "").strip().lower()
        for i in range(self._list.count()):
            it = self._list.item(i)
            it.setHidden(t not in it.text().lower())

    def _filter_params(self, text: str):
        t = (text or "").strip().lower()
        for k, lbl in self._row_labels.items():
            ed = self._widget_map.get(k)
            hay = f"{lbl.text()} { _value_to_str(self._editor_value(ed)) }".lower()
            vis = (t in hay)
            lbl.setHidden(not vis)
            if ed: ed.setHidden(not vis)

    # ---------------- diff / preview / highlight ----------------
    def _diff_with_original(self, cfg_new: dict) -> Dict[str, Tuple[Any, Any]]:
        diff = {}
        flat_new = _flatten(cfg_new)
        keys = set(self._orig_cfg_flat.keys()) | set(flat_new.keys())
        for k in sorted(keys):
            v0 = self._orig_cfg_flat.get(k, None)
            v1 = flat_new.get(k, None)
            if _value_to_str(v0) != _value_to_str(v1):
                diff[k] = (v0, v1)
        return diff

    def _show_diff_dialog(self, diff: Dict[str, Tuple[Any, Any]]):
        dlg = QDialog(None)
        dlg.setWindowTitle("Preview changes")
        lay = QVBoxLayout(dlg)
        txt = QTextEdit(); txt.setReadOnly(True)
        if not diff:
            txt.setPlainText("No changes.")
        else:
            lines = [f"{k}:\n    {repr(v0)}  →  {repr(v1)}" for k,(v0,v1) in diff.items()]
            txt.setPlainText("\n\n".join(lines))
        lay.addWidget(txt)
        btns = QDialogButtonBox(QDialogButtonBox.Ok, parent=dlg)
        lay.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        dlg.resize(600, 420)
        dlg.exec_()

    def _highlight_if_changed(self, key: str):
        ed = self._widget_map.get(key)
        if not ed: return
        cur = self._editor_value(ed)
        old = self._orig_cfg_flat.get(key, None)
        changed = (_value_to_str(cur) != _value_to_str(old))
        style = "background: #fff6cc;" if changed else ""
        ed.setStyleSheet(style)
        lbl = self._row_labels.get(key)
        if lbl: lbl.setStyleSheet(style)

    # ---------------- node IO ----------------
    def _enumerate_plugins(self):
        out = []
        try:
            for obj in gc.get_objects():
                try:
                    if isinstance(obj, BasePlugin):
                        out.append(obj)
                except Exception:
                    pass
        except Exception:
            pass
        return out

    @staticmethod
    def _node_key(node: BasePlugin) -> str:
        return f"{type(node).__name__}@{id(node)}"

    def _node_from_key(self, key: str):
        ref = self._nodes_by_key.get(key)
        return ref() if ref else None

    def _read_config(self, node: BasePlugin) -> dict:
        try:
            if hasattr(node, "export_config") and callable(node.export_config):
                cfg = node.export_config() or {}
                return {"class": type(node).__name__, "plugin_name": getattr(node, "name", type(node).__name__), "config": cfg}
        except Exception:
            pass
        try:
            outs = getattr(node, "outputs", None)
            if isinstance(outs, dict) and "config_out" in outs and hasattr(outs["config_out"], "value"):
                val = outs["config_out"].value
                if isinstance(val, dict):
                    cfg = val
                else:
                    try:
                        cfg = json.loads(val)
                    except Exception:
                        cfg = {}
                if isinstance(cfg, dict) and "nodes" in cfg:
                    return {"class": type(node).__name__, "plugin_name": getattr(node, "name", type(node).__name__), "config": {}}
                return {"class": type(node).__name__, "plugin_name": getattr(node, "name", type(node).__name__), "config": cfg}
        except Exception:
            pass
        return {"class": type(node).__name__, "plugin_name": getattr(node, "name", type(node).__name__), "config": {}}

    def _read_hints(self, node: BasePlugin) -> dict:
        try:
            if hasattr(node, "config_hints") and callable(node.config_hints):
                h = node.config_hints() or {}
                if isinstance(h, dict):
                    return h
        except Exception:
            pass
        return {}

    def _read_order_from_hints(self, hints_flat: dict):
        try:
            if isinstance(hints_flat, dict) and "_order" in hints_flat:
                return list(hints_flat["_order"])
        except Exception:
            pass
        pairs = []
        for k, meta in (hints_flat or {}).items():
            try:
                if isinstance(meta, dict) and "order" in meta:
                    pairs.append((int(meta["order"]), k))
            except Exception:
                pass
        if pairs:
            pairs.sort()
            return [k for _,k in pairs]
        return None

    def _apply_config_to_key(self, key: str, cfg: dict) -> bool:
        node = self._node_from_key(key)
        if node is None:
            return False
        return self._apply_config_to_node(node, cfg)

    def _apply_config_to_node(self, node: BasePlugin, cfg: dict) -> bool:
        ok = False
        try:
            if hasattr(node, "import_config") and callable(node.import_config):
                node.import_config(cfg); ok = True
        except Exception:
            ok = False
        if not ok:
            try:
                ins = getattr(node, "inputs", None)
                if isinstance(ins, dict) and "config_in" in ins and hasattr(ins["config_in"], "on_next"):
                    ins["config_in"].on_next(cfg); ok = True
            except Exception:
                ok = False
        if not ok and isinstance(cfg, dict):
            changed = False
            flat = _flatten(cfg)
            for k, v in flat.items():
                try:
                    if hasattr(node, k) and isinstance(v, (int, float, bool, str, list, tuple)):
                        setattr(node, k, v); changed = True
                except Exception:
                    pass
            ok = changed
        try:
            if ok and hasattr(node, "_emit_config") and callable(node._emit_config):
                node._emit_config()
        except Exception:
            pass
        return ok

    # ---------------- presets ----------------
    def _make_preset_from_cache(self) -> dict:
        if not self._cfg_cache:
            return {}
        return {"nodes": {k: v for k, v in self._cfg_cache.items()}}
