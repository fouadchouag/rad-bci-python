# gui/main_window.py
# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame,
    QGraphicsPathItem, QFileDialog, QAction,
    QDialog, QListWidget, QDialogButtonBox
)
from PyQt5.QtCore import Qt, QPointF

import json
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

# BENCH HOOK: logger d’événements (fallback silencieux si absent)
try:
    from utils.eval_log import log_evt
except Exception:
    def log_evt(*_a, **_k): pass

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

        # ✅ activer des valeurs par défaut rapides pour BLAS (évite UI qui rame)
        try:
            init_fast_defaults(blas_threads=1)
        except Exception:
            pass

        self.setWindowTitle("RBciAD – Reactive BCI Builder")
        self.setGeometry(100, 100, 1200, 800)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 3000, 3000)
        self.view = QGraphicsView(self.scene)

        # --- Z-order: nœud sélectionné en premier plan
        self._z_counter = 0
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        # Découverte des plugins
        self.plugins_by_category = discover_plugins()
        self.plugin_classes_by_name = {}  # rempli dans _populate_palette()

        # 🔹 Console de logs : créer l'objet AVANT _init_ui (pour pouvoir s'y connecter)
        self.log_dock = None
        self.logger = logging.getLogger("RBciAD")
        self.logger.setLevel(logging.DEBUG)
        if LogConsoleDock is not None:
            try:
                self.log_dock = LogConsoleDock(self, title="Console (logs)")
                # attacher notre logger applicatif à la console
                self.log_dock.attach_logger(name="RBciAD", level=logging.INFO)
            except Exception:
                self.log_dock = None

        self._init_ui()
        self.category_widgets = {}
        self.current_workflow_path = None

        # Construction de la palette
        self._populate_palette()

        # Liste à plat des plugins (pour le chargement de workflow)
        self.all_plugins = []
        for plugin_list in self.plugins_by_category.values():
            self.all_plugins.extend(plugin_list)

        self.logger.info("📦 Plugins chargés dans all_plugins :")
        for cls in self.all_plugins:
            self.logger.info(f"   - {cls.__name__}")

        # BENCH HOOK: état bench (frames)
        self._bench_rendered = 0
        self._bench_first_done = False

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # --- Barre d’outils ---
        toolbar = QHBoxLayout()
        btn_new = QPushButton("🆕 Nouveau")
        btn_load = QPushButton("📂 Charger")
        btn_save = QPushButton("💾 Sauvegarder")
        btn_save_as = QPushButton("💾 Enregistrer sous...")
        btn_lowcode = QPushButton("🛠️ Dev Mode (➕ Ajouter un Node)")

        # Dock logs toggle
        btn_logs = QPushButton("🪵 Logs")
        btn_logs.setCheckable(True)
        # connexion au dock (s'il existe)
        if self.log_dock is not None:
            btn_logs.toggled.connect(lambda vis: self.log_dock.setVisible(vis))

        # BENCH HOOK: démarrer TTFP
        btn_ttfp = QPushButton("⏱ Start TTFP (F9)")
        btn_ttfp.clicked.connect(lambda: log_evt("START_TTFP"))

        # BENCH HOOK: reset bench (compteurs propres)
        btn_bench_reset = QPushButton("▶ Bench (reset)")
        btn_bench_reset.clicked.connect(self._bench_reset)

        for btn in [btn_new, btn_load, btn_save, btn_save_as, btn_lowcode, btn_ttfp, btn_bench_reset, btn_logs]:
            btn.setMinimumHeight(40)
            btn.setStyleSheet("font-weight: bold; font-size: 14px;")
            toolbar.addWidget(btn)

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setFixedHeight(60)
        main_layout.addWidget(toolbar_widget)

        # --- Partie centrale ---
        center_layout = QHBoxLayout()

        # --- Palette latérale ---
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

        # Connexions UI
        btn_new.clicked.connect(self._action_new_workflow_from_template)  # <<< sélecteur modèles
        btn_load.clicked.connect(self._load_workflow)
        btn_save.clicked.connect(self._save_workflow)
        btn_lowcode.clicked.connect(self._show_lowcode_creator)
        btn_save_as.clicked.connect(self._save_workflow_as)

        # Raccourci clavier F9 pour TTFP
        self.actionStartTTFP = QAction("Start TTFP", self)
        self.actionStartTTFP.setShortcut("F9")
        self.actionStartTTFP.triggered.connect(lambda: log_evt("START_TTFP"))
        self.addAction(self.actionStartTTFP)

        # 🔹 Ajouter le dock de logs maintenant que la fenêtre est prête
        if self.log_dock is not None:
            try:
                self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
                self.log_dock.hide()
                # synchroniser l’état du bouton si l’utilisateur ferme le dock
                self.log_dock.visibilityChanged.connect(lambda vis: btn_logs.setChecked(vis))
                self.logger.info("Console de logs initialisée.")
            except Exception as e:
                self.logger.error(f"Erreur ajout dock logs: {e}")

    def _populate_palette(self):
        self.plugins_by_category = discover_plugins()

        # --- Registre {nom -> classe} (double clé: __name__ et .name)
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
                # Registre double entrée (nom de classe Python et .name affiché)
                self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
                try:
                    self.plugin_classes_by_name[plugin_class.name] = plugin_class
                except Exception:
                    pass

                btn = QPushButton(plugin_class.name)
                btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
                self.palette_layout.addWidget(btn)

    def add_plugin_to_palette(self, category, plugin_class):
        # (utilisé par le LowCodeCreator)
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

        # mettre à jour le registre
        self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
        try:
            self.plugin_classes_by_name[plugin_class.name] = plugin_class
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Z-order helpers
    # ---------------------------------------------------------------------
    def _raise_node(self, node_item: NodeItem):
        """Place le nœud au-dessus de tout (UX : ne jamais être masqué)."""
        try:
            self._z_counter += 1
            node_item.setZValue(self._z_counter)
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ raise_node: {e}")

    def _on_scene_selection_changed(self):
        # Dès que la sélection change, monter les nœuds sélectionnés
        for item in self.scene.selectedItems():
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
            self._raise_node(node_item)          # <<< au-dessus dès la création
            self.view.centerOn(node_item)

            # BENCH HOOK: si le plugin expose _bench.frameRendered, on connecte
            try:
                bench_obj = getattr(node_item.plugin, "_bench", None)
                if bench_obj is not None and hasattr(bench_obj, "frameRendered"):
                    bench_obj.frameRendered.connect(self._on_frame_rendered)
            except Exception:
                pass

        except Exception as e:
            self.logger.error(f"[ERROR] Failed to create node: {e}")

    def add_node_at(self, plugin_class, pos: QPointF):
        """
        Crée un NodeItem pour plugin_class et le place à 'pos'.
        """
        try:
            self.logger.info(f">>> Ajout du nœud : {plugin_class.name} @ {pos.x():.0f},{pos.y():.0f}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(pos)
            self.scene.addItem(node_item)
            self._raise_node(node_item)          # <<< au-dessus dès la création
            self.view.centerOn(node_item)

            # BENCH HOOK (même logique que _add_node)
            try:
                bench_obj = getattr(node_item.plugin, "_bench", None)
                if bench_obj is not None and hasattr(bench_obj, "frameRendered"):
                    bench_obj.frameRendered.connect(self._on_frame_rendered)
            except Exception:
                pass

            return node_item
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ add_node_at({plugin_class}): {e}")
            return None

    # ---------------- Connexion tolérante par nom de pin -------------------
    def _list_pin_names(self, node_item, is_output):
        names = []
        # essaie d'accéder aux maps si elles existent
        try:
            d = node_item.output_pins if is_output else node_item.input_pins
            if isinstance(d, dict):
                names.extend(list(d.keys()))
        except Exception:
            pass
        # essaie des getters s'ils existent
        try:
            getter = node_item.get_output_pin_names if is_output else node_item.get_input_pin_names
            names.extend(list(getter()))
        except Exception:
            pass
        return sorted(set(str(n) for n in names))

    def _resolve_pin(self, node_item, wanted_name, is_output):
        """Trouve un pin par nom exact, casse-insensible, puis par synonymes."""
        wanted_name = str(wanted_name)
        get = node_item.get_output_pin_by_name if is_output else node_item.get_input_pin_by_name

        # 1) exact
        pin = get(wanted_name)
        if pin:
            return pin

        # 2) case-insensitive sur les noms déclarés
        names = self._list_pin_names(node_item, is_output)
        for n in names:
            if n.lower() == wanted_name.lower():
                return get(n)

        # 3) synonymes
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
        """
        Connecte visuellement src.output[src_pin_name] → dst.input[dst_pin_name],
        avec correspondance tolérante (casse + synonymes).
        """
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
            self.scene.addItem(conn_item)
            conn_item.track_both_pins()
            try:
                conn_item.setZValue(-1000)  # <<< toujours sous les nœuds
            except Exception:
                pass

            # Marque visuelle
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
                    # supprimer les connexions associées
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

                    # supprimer le nœud
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
    # Workflows: nouveau / enregistrer / charger
    # ---------------------------------------------------------------------
    def _clear_scene_only(self):
        """Nettoie seulement la scène (sans toucher au registre ou à la palette)."""
        for it in list(self.scene.items()):
            self.scene.removeItem(it)

    def _action_new_workflow_from_template(self):
        """
        Ouvre un dialogue proposant :
        - Vierge (vide)
        - Pipeline simple (Bandpower)
        - Pipeline CSP
        - Pipeline Riemann
        """
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

        # Reset workflow courant
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

        # (Log debug utile)
        self.logger.info("[Templates] clés disponibles : %s", list(TEMPLATES.keys()))

        # Instancier le template
        try:
            created, title = instantiate_template(self, key)
            self.logger.info(f"[MainWindow] ✅ Workflow modèle: {title} — {len(created)} nœuds instanciés.")
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ échec instanciation template '{key}': {e}")

        self._update_workflow_label()

    def _new_workflow(self):
        # (déprécié pour le bouton, mais conservé si tu veux l'appeler ailleurs)
        self.logger.info("🆕 Nouveau workflow")
        self.scene.clear()
        self.nodes = []
        self.connections = []
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()
        self._update_workflow_label()

    # ---------- helpers config (save/load) ----------
    def _gather_node_config(self, plugin) -> dict:
        """Essaye export_config, sinon lit outputs['config_out'], sinon {}."""
        # 1) export_config()
        try:
            if hasattr(plugin, "export_config") and callable(plugin.export_config):
                cfg = plugin.export_config() or {}
                if isinstance(cfg, dict):
                    return cfg
        except Exception:
            pass
        # 2) config_out
        try:
            outs = getattr(plugin, "outputs", None)
            if isinstance(outs, dict) and "config_out" in outs:
                val = getattr(outs["config_out"], "value", None)
                if isinstance(val, dict):
                    # si c'est un preset complet {"nodes": ...}, pas utile ici
                    return val.get("config", val)
        except Exception:
            pass
        return {}

    def _apply_config_to_node(self, plugin, cfg: dict):
        """import_config(cfg) sinon entrée config_in, sinon setattr sur types simples."""
        ok = False
        # 1) import_config
        try:
            if hasattr(plugin, "import_config") and callable(plugin.import_config):
                plugin.import_config(cfg); ok = True
        except Exception:
            ok = False
        # 2) config_in pin
        if not ok:
            try:
                ins = getattr(plugin, "inputs", None)
                if isinstance(ins, dict) and "config_in" in ins and hasattr(ins["config_in"], "on_next"):
                    ins["config_in"].on_next(cfg); ok = True
            except Exception:
                ok = False
        # 3) setattr fallback (types simples)
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
        # 4) re-emit config if available
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

    def _write_workflow_to_file(self, path):
        data = {
            "version": 2,
            "nodes": [],
            "connections": []
        }

        # Nœuds
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

        # Connexions (toujours output -> input)
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

        # Écriture fichier
        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.logger.info(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()

    def _load_workflow(self):
        self.logger.info("📂 Charger workflow")
        path, _ = QFileDialog.getOpenFileName(self, "Charger un workflow", "", "JSON Files (*.json)")
        if not path:
            return

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._new_workflow()
        self.logger.info(f"➡️ Données lues depuis le JSON : {data.keys()}")

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
                    self._raise_node(node_item)  # <<< au-dessus après chargement

                    # Appliquer la config sauvegardée si dispo
                    try:
                        if cfg:
                            ok = self._apply_config_to_node(node_item.plugin, cfg)
                            self.logger.info(f"   ↳ Config appliquée: {ok}")
                    except Exception as e:
                        self.logger.error(f"   ↳ Erreur application config: {e}")

                    # BENCH HOOK
                    try:
                        bench_obj = getattr(node_item.plugin, "_bench", None)
                        if bench_obj is not None and hasattr(bench_obj, "frameRendered"):
                            bench_obj.frameRendered.connect(self._on_frame_rendered)
                    except Exception:
                        pass

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
                # utilise la version tolérante pour rattraper d’éventuels écarts de noms
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

    # ---------------------------------------------------------------------
    # BENCH HOOKS
    # ---------------------------------------------------------------------
    def _on_frame_rendered(self):
        self._bench_rendered += 1
        try:
            log_evt("FRAME", f"n={self._bench_rendered}")
            if not self._bench_first_done:
                log_evt("FIRST_FRAME", "frame_id=1")
                self._bench_first_done = True
        except Exception:
            pass

    def _bench_reset(self):
        self._bench_rendered = 0
        self._bench_first_done = False
        try:
            log_evt("RUN", "reset=1")
        except Exception:
            pass
