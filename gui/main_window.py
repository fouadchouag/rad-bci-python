# gui/main_window.py
# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame,
    QGraphicsPathItem, QFileDialog, QAction,
    QDialog, QListWidget, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QPointF
import sip

import json
import re
from json import JSONDecodeError
from pathlib import Path
import numpy as np

import os
import logging
from core.plugin_registry import discover_plugins
from .node_item import NodeItem
from gui.lowcode_creator import LowCodeCreator
from .connection_item import ConnectionItem

# ✅ perf: initialiser tôt la limite de threads BLAS pour éviter l'over-subscription
try:
    from core.rt_perf import init_fast_defaults
except Exception:
    def init_fast_defaults(*_a, **_k): pass  # fallback no-op

# Templates : import relatif (prioritaire) puis absolu en fallback
try:
    from .workflow_templates import TEMPLATES, instantiate_template
except Exception:
    try:
        from workflow_templates import TEMPLATES, instantiate_template
    except Exception:
        TEMPLATES = {}
        def instantiate_template(*_a, **_k):
            raise RuntimeError("workflow_templates.py manquant (placez-le dans gui/ ou à la racine).")

# 🔹 Console de logs
try:
    from gui.log_console import LogConsoleDock
except Exception:
    LogConsoleDock = None


class MainWindow(QMainWindow):
    # -------------------------- Synonymes de pins --------------------------
    PIN_SYNONYMS = {
        "raw":        ["data", "eeg", "Raw", "X"],
        "sfreq":      ["fs", "Fs", "sampling_rate", "sample_rate", "sf"],
        "ch_names":   ["channels", "ch", "chan_names", "labels", "names"],
        "segment":    ["segments", "window", "trial", "epoch", "sample"],
        "label":      ["labels", "y", "target", "class"],
        "features":   ["feature", "X", "x", "vec", "embedding"],
        "model":      ["clf", "classifier", "estimator"],
        "cov":        ["covariance", "C"],
        "feature_transform": ["transform", "feat_transform", "csp"],
        "ts_transform":      ["transform", "tspace", "tangent", "feat_transform"],
    }

    def __init__(self):
        super().__init__()

        # ✅ BLAS
        try:
            init_fast_defaults(blas_threads=1)
        except Exception:
            pass

        self.setWindowTitle("RBciAD – Reactive BCI Builder")
        self.setGeometry(100, 100, 1200, 800)

        self._closing = False

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 3000, 3000)
        self.view = QGraphicsView(self.scene)

        # Z-order
        self._z_counter = 0
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        # Plugins
        self.plugins_by_category = discover_plugins()
        self.plugin_classes_by_name = {}

        # Logs UI
        self.log_dock = None
        self.logger = logging.getLogger("RBciAD")
        self.logger.setLevel(logging.DEBUG)
        if LogConsoleDock is not None:
            try:
                self.log_dock = LogConsoleDock(self, title="Console (logs)")
                self.log_dock.attach_logger(name="RBciAD", level=logging.INFO)
            except Exception:
                self.log_dock = None

        self._init_ui()
        self.category_widgets = {}
        self.current_workflow_path = None

        # Palette
        self._populate_palette()

        # Liste à plat des plugins
        self.all_plugins = []
        for plugin_list in self.plugins_by_category.values():
            self.all_plugins.extend(plugin_list)

        self.logger.info("📦 Plugins chargés dans all_plugins :")
        for cls in self.all_plugins:
            self.logger.info(f"   - {cls.__name__}")

        # 🔥 IMPORTANT: plus de démarrage auto des métriques ici.
        # On installe seulement les hotkeys F9/F10 (ne créent aucun fichier tant qu'on n'appuie pas).
        try:
            from core.metrics_hotkeys import install_global_metrics_hotkeys
            install_global_metrics_hotkeys(app_name="RBciAD", out_dir="runs")
            self.logger.info("[metrics] Hotkeys installés : F9=Start/Stop, F10=Stop forcé")
        except Exception as e:
            self.logger.warning(f"[metrics] hotkeys non installés ({e})")

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_new = QPushButton("🆕 Nouveau")
        btn_load = QPushButton("📂 Charger")
        btn_save = QPushButton("💾 Sauvegarder")
        btn_save_as = QPushButton("💾 Enregistrer sous...")
        btn_lowcode = QPushButton("🛠️ Dev Mode (➕ Ajouter un Node)")

        btn_logs = QPushButton("🪵 Logs")
        btn_logs.setCheckable(True)
        if self.log_dock is not None:
            btn_logs.toggled.connect(lambda vis: self.log_dock.setVisible(vis))

        # (❌ supprimé) Boutons TTFP/Bench/Metrics

        for btn in [btn_new, btn_load, btn_save, btn_save_as, btn_lowcode, btn_logs]:
            btn.setMinimumHeight(40)
            btn.setStyleSheet("font-weight: bold; font-size: 14px;")
            toolbar.addWidget(btn)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setFixedHeight(60)
        main_layout.addWidget(toolbar_widget)

        # Centre
        center_layout = QHBoxLayout()

        # Palette
        self.palette_frame = QFrame()
        self.palette_layout = QVBoxLayout(self.palette_frame)
        self.palette_frame.setLayout(self.palette_layout)

        palette_scroll = QScrollArea()
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setWidget(self.palette_frame)
        palette_scroll.setFixedWidth(220)

        center_layout.addWidget(palette_scroll)
        center_layout.addWidget(self.view, stretch=1)

        self.workflow_label = QLabel("🗂️ Aucun fichier")
        self.workflow_label.setStyleSheet("font-style: italic; color: gray; margin-left: 8px;")
        main_layout.addWidget(self.workflow_label)

        main_layout.addLayout(center_layout)

        # Connexions
        btn_new.clicked.connect(self._action_new_workflow_from_template)
        btn_load.clicked.connect(self._load_workflow)
        btn_save.clicked.connect(self._save_workflow)
        btn_lowcode.clicked.connect(self._show_lowcode_creator)
        btn_save_as.clicked.connect(self._save_workflow_as)

        # Dock logs
        if self.log_dock is not None:
            try:
                self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
                self.log_dock.hide()
                self.log_dock.visibilityChanged.connect(lambda vis: btn_logs.setChecked(vis))
                self.logger.info("Console de logs initialisée.")
            except Exception as e:
                self.logger.error(f"Erreur ajout dock logs: {e}")

    def closeEvent(self, ev):
        self._closing = True
        try:
            self.scene.selectionChanged.disconnect(self._on_scene_selection_changed)
        except Exception:
            pass
        return super().closeEvent(ev)

    def _populate_palette(self):
        self.plugins_by_category = discover_plugins()
        self.plugin_classes_by_name = {}

        self.logger.info("📦 Plugins détectés :")
        for cat, plugins in self.plugins_by_category.items():
            self.logger.info(f"  📁 {cat} : {[cls.__name__ for cls in plugins]}")

        # Nettoyer la palette
        for i in reversed(range(self.palette_layout.count())):
            widget = self.palette_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Reconstruire la palette + registre
        for category, plugin_list in self.plugins_by_category.items():
            cat_label = QLabel(f"📁 {category}")
            cat_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            self.palette_layout.addWidget(cat_label)

            for plugin_class in plugin_list:
                self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
                try:
                    self.plugin_classes_by_name[plugin_class.name] = plugin_class
                except Exception:
                    pass

                btn = QPushButton(plugin_class.name)
                btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
                self.palette_layout.addWidget(btn)

    def add_plugin_to_palette(self, category, plugin_class):
        if category not in self.category_widgets:
            label = QLabel(f"📁 {category}")
            label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            self.palette_layout.addWidget(label)

            layout = QVBoxLayout()
            container = QWidget()
            container.setLayout(layout)
            self.palette_layout.addWidget(container)

            self.category_widgets[category] = layout

        layout = self.category_widgets[category]
        btn = QPushButton(plugin_class.name)
        btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
        layout.addWidget(btn)

        self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
        try:
            self.plugin_classes_by_name[plugin_class.name] = plugin_class
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Z-order helpers
    # ---------------------------------------------------------------------
    def _raise_node(self, node_item: NodeItem):
        try:
            self._z_counter += 1
            node_item.setZValue(self._z_counter)
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ raise_node: {e}")

    def _on_scene_selection_changed(self):
        if self._closing:
            return
        scene = getattr(self, "scene", None)
        if scene is None or sip.isdeleted(scene):
            return
        try:
            items = scene.selectedItems()
        except RuntimeError:
            return
        for item in items:
            if isinstance(item, NodeItem):
                self._raise_node(item)

    # ---------------------------------------------------------------------
    # Création / Connexions de nœuds
    # ---------------------------------------------------------------------
    def _add_node(self, plugin_class):
        try:
            self.logger.info(f">>> Ajout du nœud : {plugin_class.name}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(200, 200)
            self.scene.addItem(node_item)
            self._raise_node(node_item)
            self.view.centerOn(node_item)
        except Exception as e:
            self.logger.error(f"[ERROR] Failed to create node: {e}")

    def add_node_at(self, plugin_class, pos: QPointF):
        try:
            self.logger.info(f">>> Ajout du nœud : {plugin_class.name} @ {pos.x():.0f},{pos.y():.0f}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(pos)
            self.scene.addItem(node_item)
            self._raise_node(node_item)
            self.view.centerOn(node_item)
            return node_item
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ add_node_at({plugin_class}): {e}")
            return None

    # ---------------- Connexion tolérante par nom de pin -------------------
    def _list_pin_names(self, node_item, is_output):
        names = []
        try:
            d = node_item.output_pins if is_output else node_item.input_pins
            if isinstance(d, list):
                names.extend([p.name for p in d if hasattr(p, "name")])
        except Exception:
            pass
        try:
            getter = node_item.get_output_pin_names if is_output else node_item.get_input_pin_names
            names.extend(list(getter()))
        except Exception:
            pass
        return sorted(set(str(n) for n in names))

    def _resolve_pin(self, node_item, wanted_name, is_output):
        wanted_name = str(wanted_name)
        get = node_item.get_output_pin_by_name if is_output else node_item.get_input_pin_by_name

        # exact
        pin = get(wanted_name)
        if pin:
            return pin

        # case-insensitive
        names = self._list_pin_names(node_item, is_output)
        for n in names:
            if n.lower() == wanted_name.lower():
                return get(n)

        # synonymes
        syns = self.PIN_SYNONYMS.get(wanted_name.lower(), [])
        for syn in syns:
            pin = get(syn)
            if pin:
                return pin
            for n in names:
                if n.lower() == syn.lower():
                    return get(n)

        return None

    def connect_by_name(self, src_node_item, src_pin_name: str, dst_node_item, dst_pin_name: str) -> bool:
        try:
            out_pin = self._resolve_pin(src_node_item, src_pin_name, True)
            in_pin  = self._resolve_pin(dst_node_item, dst_pin_name, False)

            if not out_pin or not in_pin:
                out_names = self._list_pin_names(src_node_item, True)
                in_names  = self._list_pin_names(dst_node_item, False)
                self.logger.error(f"[Templates] ❌ Échec connexion {src_node_item.plugin.name}.{src_pin_name} → "
                                  f"{dst_node_item.plugin.name}.{dst_pin_name}")
                self.logger.error(f"           ├─ sorties dispo: {out_names}")
                self.logger.error(f"           └─ entrées  dispo: {in_names}")
                return False

            conn_item = ConnectionItem(out_pin, in_pin)

            try:
                if conn_item.scene() is None:
                    self.scene.addItem(conn_item)
            except Exception:
                pass

            try:
                conn_item.track_both_pins()
                conn_item.setZValue(-1000)
            except Exception:
                pass

            try:
                out_pin.set_connected(True)
                in_pin.set_connected(True)
            except Exception:
                pass

            self.logger.info(f"✅ Connecté: {src_node_item.plugin.name}.{out_pin.name} → {dst_node_item.plugin.name}.{in_pin.name}")
            return True
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ connect_by_name: {e}")
            return False

    # ---------------------------------------------------------------------
    # Événements / suppression
    # ---------------------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            for item in self.scene.selectedItems():
                if hasattr(item, "plugin"):
                    # connexions
                    to_remove = []
                    for obj in self.scene.items():
                        if isinstance(obj, QGraphicsPathItem) and hasattr(obj, "output_pin") and hasattr(obj, "input_pin"):
                            if obj.output_pin.node == item or obj.input_pin.node == item:
                                to_remove.append(obj)

                    for conn in to_remove:
                        if hasattr(conn, "cleanup"):
                            conn.cleanup()
                            if hasattr(conn, "input_pin") and conn.input_pin and hasattr(conn.input_pin, "node"):
                                input_node = conn.input_pin.node
                                if hasattr(input_node, "plugin"):
                                    input_node.plugin.set_input(conn.input_pin.name, None)
                        self.scene.removeItem(conn)

                    # nœud
                    item.plugin.cleanup()
                    self.scene.removeItem(item)

                elif isinstance(item, QGraphicsPathItem):
                    if hasattr(item, "cleanup"):
                        item.cleanup()
                        if hasattr(item, "input_pin") and item.input_pin and hasattr(item.input_pin, "node"):
                            input_node = item.input_pin.node
                            if hasattr(input_node, "plugin"):
                                input_node.plugin.set_input(item.input_pin.name, None)
                    self.scene.removeItem(item)
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------------------
    # Workflows
    # ---------------------------------------------------------------------
    def _clear_scene_only(self):
        try:
            self.scene.selectionChanged.disconnect(self._on_scene_selection_changed)
        except Exception:
            pass

        for obj in list(self.scene.items()):
            if isinstance(obj, ConnectionItem) or (isinstance(obj, QGraphicsPathItem) and hasattr(obj, "output_pin")):
                try:
                    if hasattr(obj, "cleanup"): obj.cleanup()
                    if hasattr(obj, "input_pin") and obj.input_pin and hasattr(obj, "node"):
                        input_node = obj.input_pin.node
                        if hasattr(input_node, "plugin"):
                            input_node.plugin.set_input(obj.input_pin.name, None)
                except Exception:
                    pass
                try:
                    self.scene.removeItem(obj)
                except Exception:
                    pass

        for it in list(self.scene.items()):
            if isinstance(it, NodeItem):
                try:
                    if hasattr(it.plugin, "on_remove") and callable(it.plugin.on_remove): it.plugin.on_remove()
                except Exception:
                    pass
                try:
                    it.plugin.cleanup()
                except Exception:
                    pass
                try:
                    self.scene.removeItem(it)
                except Exception:
                    pass
            else:
                try:
                    self.scene.removeItem(it)
                except Exception:
                    pass

        try:
            self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        except Exception:
            pass

    def _action_new_workflow_from_template(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Nouveau workflow…")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Choisissez un modèle de pipeline :"))

        lst = QListWidget(dlg)
        items = [("blank", "Vierge (vide)")] + [(k, TEMPLATES[k]["title"]) for k in TEMPLATES.keys()]
        for _key, title in items:
            lst.addItem(title)
        lst.setCurrentRow(0)
        layout.addWidget(lst)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return

        idx = lst.currentRow()
        if idx < 0:
            return
        key = items[idx][0]

        self._clear_scene_only()
        self.nodes = []
        self.connections = []
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()

        if key == "blank":
            self.logger.info("🆕 Nouveau workflow vierge")
            self._update_workflow_label()
            return

        if not TEMPLATES:
            self.logger.warning("⚠️ Aucun template disponible (workflow_templates.py manquant).")
            self._update_workflow_label()
            return

        self.logger.info("[Templates] clés disponibles : %s", list(TEMPLATES.keys()))
        try:
            created, title = instantiate_template(self, key)
            self.logger.info(f"[MainWindow] ✅ Workflow modèle: {title} — {len(created)} nœuds instanciés.")
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ échec instanciation template '{key}': {e}")

        self._update_workflow_label()

    def _new_workflow(self):
        self._clear_scene_only()
        self.nodes = []
        self.connections = []
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()
        self._update_workflow_label()

    # ---------- helpers config (save/load) ----------
    def _gather_node_config(self, plugin) -> dict:
        try:
            if hasattr(plugin, "export_config") and callable(plugin.export_config):
                cfg = plugin.export_config() or {}
                if isinstance(cfg, dict):
                    return cfg
        except Exception:
            pass
        try:
            outs = getattr(plugin, "outputs", None)
            if isinstance(outs, dict) and "config_out" in outs:
                val = getattr(outs["config_out"], "value", None)
                if isinstance(val, dict):
                    return val.get("config", val)
        except Exception:
            pass
        return {}

    def _apply_config_to_node(self, plugin, cfg: dict):
        ok = False
        try:
            if hasattr(plugin, "import_config") and callable(plugin.import_config):
                plugin.import_config(cfg); ok = True
        except Exception:
            ok = False
        if not ok:
            try:
                ins = getattr(plugin, "inputs", None)
                if isinstance(ins, dict) and "config_in" in ins and hasattr(ins["config_in"], "on_next"):
                    ins["config_in"].on_next(cfg); ok = True
            except Exception:
                ok = False
        if not ok and isinstance(cfg, dict):
            changed = False
            def _flatten(d: dict, parent=""):
                flat = {}
                for k, v in (d or {}).items():
                    key = f"{parent}.{k}" if parent else str(k)
                    if isinstance(v, dict):
                        flat.update(_flatten(v, key))
                    else:
                        flat[key] = v
                return flat
            flat = _flatten(cfg)
            for k, v in flat.items():
                try:
                    if hasattr(plugin, k) and isinstance(v, (int, float, bool, str, list, tuple)):
                        setattr(plugin, k, v); changed = True
                except Exception:
                    pass
            ok = changed
        try:
            if ok and hasattr(plugin, "_emit_config") and callable(plugin._emit_config):
                plugin._emit_config()
        except Exception:
            pass
        return ok

    def _save_workflow(self):
        if not self.current_workflow_path:
            return self._save_workflow_as()
        self._write_workflow_to_file(self.current_workflow_path)
        self._update_workflow_label()

    def _save_workflow_as(self):
        suggested = self.temp_suggested_path if hasattr(self, "temp_suggested_path") else ""
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le workflow sous...", suggested, "JSON Files (*.json)")
        if path:
            self.current_workflow_path = path
            self._write_workflow_to_file(path)
            self._update_workflow_label()

    # --------- Convertit récursivement en objets JSON-sérialisables ---------
    def _json_safe(self, obj, *, max_array_elems: int = 2000):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {str(self._json_safe(k)): self._json_safe(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._json_safe(x) for x in obj]
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "__fspath__"):
            try: return os.fspath(obj)
            except Exception: return str(obj)
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            if obj.size <= max_array_elems:
                return obj.tolist()
            return {"__ndarray__": True, "shape": list(obj.shape), "dtype": str(obj.dtype)}
        if isinstance(obj, QPointF):
            return [float(obj.x()), float(obj.y())]
        try:
            return str(obj)
        except Exception:
            return repr(obj)

    def _write_workflow_to_file(self, path):
        data = {"version": 2, "nodes": [], "connections": []}

        for item in self.scene.items():
            if isinstance(item, NodeItem):
                plugin = getattr(item, "plugin", None)
                cfg = self._gather_node_config(plugin) if plugin else {}
                data["nodes"].append({
                    "name": plugin.name if plugin else "Unknown",
                    "type": type(plugin).__name__ if plugin else "Unknown",
                    "position": [item.pos().x(), item.pos().y()],
                    "config": cfg
                })

        for item in self.scene.items():
            if isinstance(item, ConnectionItem):
                out_pin = item.output_pin
                in_pin = item.input_pin
                if not out_pin or not in_pin:
                    continue
                data["connections"].append({
                    "from": out_pin.parentItem().plugin.name,
                    "from_pin": out_pin.name,
                    "to": in_pin.parentItem().plugin.name,
                    "to_pin": in_pin.name
                })

        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        data_safe = self._json_safe(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_safe, f, indent=2, ensure_ascii=False)
        self.logger.info(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()

    def _load_workflow(self):
        self.logger.info("📂 Charger workflow")
        path, _ = QFileDialog.getOpenFileName(self, "Charger un workflow", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            data = self._load_json_lenient(path)
        except Exception as e:
            self.logger.error(f"❌ Échec de lecture JSON: {e}")
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erreur JSON", f"Impossible de charger le workflow:\n\n{e}")
            return

        self._new_workflow()
        self.logger.info(f"➡️ Données lues depuis le JSON : {list(data.keys())}")

        node_map = {}

        # Reconstruction des nœuds
        for node_data in data.get("nodes", []):
            node_type = node_data.get("type")
            node_name = node_data.get("name")
            pos = node_data.get("position", [200, 200])
            cfg = node_data.get("config", {}) or {}

            found = False
            for plugin_class in self.all_plugins:
                if plugin_class.__name__ == node_type:
                    self.logger.info(f"✅ Plugin trouvé : {plugin_class.__name__}")
                    node_item = NodeItem(plugin_class)
                    node_item.setPos(pos[0], pos[1])
                    self.scene.addItem(node_item)
                    self._raise_node(node_item)

                    try:
                        if cfg:
                            ok = self._apply_config_to_node(node_item.plugin, cfg)
                            self.logger.info(f"   ↳ Config appliquée: {ok}")
                        else:
                            self.logger.info("   ↳ Aucun paramètre de config à appliquer.")
                    except Exception as e:
                        self.logger.error(f"   ↳ Erreur application config: {e}")

                    node_map[node_name] = node_item
                    found = True
                    break
            if not found:
                self.logger.warning(f"⚠️ Plugin introuvable pour type={node_type}")

        # Reconstruction des connexions
        for conn in data.get("connections", []):
            from_node = node_map.get(conn.get("from"))
            to_node = node_map.get(conn.get("to"))
            if from_node and to_node:
                ok = self.connect_by_name(from_node, conn.get("from_pin"), to_node, conn.get("to_pin"))
                if ok:
                    self.logger.info(f"✅ Connexion recréée : {conn}")
            else:
                self.logger.warning(f"⚠️ Nœuds introuvables : {conn.get('from')} ou {conn.get('to')}")

        self.logger.info(f"✅ Workflow chargé : {path}")
        self.current_workflow_path = path
        self._update_workflow_label()

    def _show_lowcode_creator(self):
        self.lowcode_window = LowCodeCreator(main_window=self)
        self.lowcode_window.show()

    def _update_workflow_label(self):
        if self.current_workflow_path:
            self.workflow_label.setText(f"🗂️ Fichier courant : {self.current_workflow_path}")
        elif hasattr(self, "temp_suggested_path"):
            self.workflow_label.setText(f"🗂️ Nouveau fichier : {self.temp_suggested_path} (non enregistré)")
        else:
            self.workflow_label.setText("🗂️ Aucun fichier")

    def _generate_temp_filename(self):
        base_name = "workflow"
        os.makedirs("workflows", exist_ok=True)
        i = 1
        while True:
            candidate = os.path.join("workflows", f"{base_name}_{i:04d}.json")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    # ---------------- JSON loader tolérant ----------------
    def _read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()

    def _json_lenient_cleanup(self, s: str) -> str:
        txt = s
        txt = re.sub(r'//.*?$', '', txt, flags=re.MULTILINE)
        txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.DOTALL)
        txt = re.sub(r'\bNaN\b', 'null', txt)
        txt = re.sub(r'\bInfinity\b', 'null', txt)
        txt = re.sub(r'\b-Infinity\b', 'null', txt)
        txt = re.sub(r',(\s*[\}\]])', r'\1', txt)
        last_brace = txt.rfind('}')
        if last_brace != -1:
            tail = txt[last_brace+1:].strip()
            if tail:
                txt = txt[:last_brace+1]
        return txt

    def _load_json_lenient(self, path: str):
        raw = self._read_text(path)
        try:
            return json.loads(raw)
        except JSONDecodeError:
            pass
        cleaned = self._json_lenient_cleanup(raw)
        try:
            return json.loads(cleaned)
        except JSONDecodeError as e:
            line, col = e.lineno, e.colno
            lines = cleaned.splitlines()
            start = max(0, line-3); end = min(len(lines), line+2)
            context = "\n".join(f"{i+1:>4}: {lines[i]}" for i in range(start, end))
            msg = (f"JSON invalide (ligne {line}, colonne {col}): {e.msg}\nContexte proche:\n{context}")
            raise RuntimeError(msg) from e
