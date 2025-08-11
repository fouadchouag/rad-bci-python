from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame, 
    QGraphicsPathItem, QFileDialog, QAction  # ← ajouté QAction
)
from PyQt5.QtCore import Qt
from core.plugin_registry import discover_plugins
from .node_item import NodeItem
from gui.lowcode_creator import LowCodeCreator

import json
from .connection_item import ConnectionItem
import os

# ← ajout
from utils.eval_log import log_evt


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RBciAD – Reactive BCI Builder")
        self.setGeometry(100, 100, 1200, 800)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 3000, 3000)
        self.view = QGraphicsView(self.scene)

        self.plugins_by_category = discover_plugins()

        self._init_ui()
        self.category_widgets = {}
        self.current_workflow_path = None


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

        # ← bouton pour démarrer le chrono TTFP
        btn_ttfp = QPushButton("⏱ Start TTFP (F9)")
        btn_ttfp.clicked.connect(lambda: log_evt("START_TTFP"))

        for btn in [btn_new, btn_load, btn_save, btn_save_as, btn_lowcode, btn_ttfp]:
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

        self._populate_palette()

        self.all_plugins = []
        for plugin_list in self.plugins_by_category.values():
            self.all_plugins.extend(plugin_list)

        print("📦 Plugins chargés dans all_plugins :")
        for cls in self.all_plugins:
            print(f"   - {cls.__name__}")

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
        btn_new.clicked.connect(self._new_workflow)
        btn_load.clicked.connect(self._load_workflow)
        btn_save.clicked.connect(self._save_workflow)
        btn_lowcode.clicked.connect(self._show_lowcode_creator)
        btn_save_as.clicked.connect(self._save_workflow_as)

        # ← Raccourci clavier F9 pour TTFP
        self.actionStartTTFP = QAction("Start TTFP", self)
        self.actionStartTTFP.setShortcut("F9")
        self.actionStartTTFP.triggered.connect(lambda: log_evt("START_TTFP"))
        self.addAction(self.actionStartTTFP)

    def _populate_palette(self):
        self.plugins_by_category = discover_plugins()

        print("📦 Plugins détectés :")
        for cat, plugins in self.plugins_by_category.items():
            print(f"  📁 {cat} : {[cls.__name__ for cls in plugins]}")

        for i in reversed(range(self.palette_layout.count())):
            widget = self.palette_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        for category, plugin_list in self.plugins_by_category.items():
            cat_label = QLabel(f"📁 {category}")
            cat_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            self.palette_layout.addWidget(cat_label)

            for plugin_class in plugin_list:
                btn = QPushButton(plugin_class.name)
                btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
                self.palette_layout.addWidget(btn)
        # ✅ AJOUTE CETTE LIGNE ICI
        #self.all_plugins = list(self.plugins_by_category.get("Node de base", [])) + list(self.plugins_by_category.get("Custom", []))
        


    def add_plugin_to_palette(self, category, plugin_class):
        # Vérifie si la catégorie existe déjà
        if category not in self.category_widgets:
            # Nouveau layout pour cette catégorie
            label = QLabel(f"📁 {category}")
            label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            self.palette_layout.addWidget(label)

            layout = QVBoxLayout()
            container = QWidget()
            container.setLayout(layout)
            self.palette_layout.addWidget(container)

            self.category_widgets[category] = layout  # Sauvegarde le layout

        # Ajoute le plugin dans la catégorie correspondante
        layout = self.category_widgets[category]
        btn = QPushButton(plugin_class.name)
        btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
        layout.addWidget(btn)



    def _add_node(self, plugin_class):
        try:
            print(f">>> Ajout du nœud : {plugin_class.name}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(200, 200)
            self.scene.addItem(node_item)
            self.view.centerOn(node_item)
        except Exception as e:
            print(f"[ERROR] Failed to create node: {e}")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            for item in self.scene.selectedItems():
                if hasattr(item, "plugin"):
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

    
    # def _new_workflow(self):
    #     print("🆕 Nouveau workflow")
    #     self.scene.clear()
    #     self.nodes = []
    #     self.connections = []

    def _new_workflow(self):
        print("🆕 Nouveau workflow")
        self.scene.clear()
        self.nodes = []
        self.connections = []

        # Génère un nom temporaire mais ne le considère pas encore comme sauvegardé
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()
        self._update_workflow_label()


    def _save_workflow(self):
        if not self.current_workflow_path:
            return self._save_workflow_as()  # Suggère un chemin si pas encore sauvegardé

        self._write_workflow_to_file(self.current_workflow_path)

        #print(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()

    def _save_workflow_as(self):
        suggested = self.temp_suggested_path if hasattr(self, "temp_suggested_path") else ""
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le workflow sous...", suggested, "JSON Files (*.json)")
        if path:
            self.current_workflow_path = path
            self._write_workflow_to_file(path)

            #print(f"✅ Workflow enregistré : {path}")
            self._update_workflow_label()


    
    def _write_workflow_to_file(self, path):
        data = {
            "nodes": [],
            "connections": []
        }

        for item in self.scene.items():
            if isinstance(item, NodeItem):
                data["nodes"].append({
                    "name": item.plugin.name,
                    "type": type(item.plugin).__name__,
                    "position": [item.pos().x(), item.pos().y()]
                })

        for item in self.scene.items():
            if isinstance(item, ConnectionItem):
                source_pin = item.input_pin
                dest_pin = item.output_pin

                if source_pin.is_output:
                    output_node = source_pin.parentItem().plugin.name
                    output_pin = source_pin.name
                    input_node = dest_pin.parentItem().plugin.name
                    input_pin = dest_pin.name
                else:
                    output_node = dest_pin.parentItem().plugin.name
                    output_pin = dest_pin.name
                    input_node = source_pin.parentItem().plugin.name
                    input_pin = source_pin.name

                data["connections"].append({
                    "from": output_node,
                    "from_pin": output_pin,
                    "to": input_node,
                    "to_pin": input_pin
                })

        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()






    def _load_workflow(self):
        print("📂 Charger workflow")
        path, _ = QFileDialog.getOpenFileName(self, "Charger un workflow", "", "JSON Files (*.json)")
        if not path:
            return

        with open(path, "r") as f:
            data = json.load(f)

        self._new_workflow()  # Réinitialiser
        print(f"➡️ Données lues depuis le JSON : {data}")

        node_map = {}

        # --- Reconstruction des nœuds
        for node_data in data["nodes"]:
            node_type = node_data["type"]       # ex: EEGFilterPlugin
            node_name = node_data["name"]       # ex: EEGFilterPlugin_b384b5
            pos = node_data["position"]

            found = False
            for plugin_class in self.all_plugins:
                if plugin_class.__name__ == node_type:
                    print(f"✅ Plugin trouvé : {plugin_class.__name__}")
                    node_item = NodeItem(plugin_class)
                    node_item.setPos(pos[0], pos[1])
                    self.scene.addItem(node_item)
                    node_map[node_name] = node_item  # clé = nom unique
                    found = True
                    break
            if not found:
                print(f"⚠️ Plugin introuvable pour type={node_type}")

        # --- Reconstruction des connexions
        for conn in data["connections"]:
            from_node = node_map.get(conn["from"])
            to_node = node_map.get(conn["to"])
            if from_node and to_node:
                from_pin = from_node.get_output_pin_by_name(conn["from_pin"])
                to_pin = to_node.get_input_pin_by_name(conn["to_pin"])
                if from_pin and to_pin:
                    conn_item = ConnectionItem(from_pin, to_pin)
                    self.scene.addItem(conn_item)
                    conn_item.track_both_pins()
                    from_pin.set_connected(True)
                    to_pin.set_connected(True)
                    print(f"✅ Connexion recréée : {conn}")
                else:
                    print(f"⚠️ Pins introuvables : {conn['from_pin']} → {conn['to_pin']}")
            else:
                print(f"⚠️ Nœuds introuvables : {conn['from']} ou {conn['to']}")

        print(f"✅ Workflow chargé : {path}")
        self.current_workflow_path = path
        #print(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()





    def _show_lowcode_creator(self):
        self.lowcode_window = LowCodeCreator(main_window=self)
        self.lowcode_window.show()

    # def _update_workflow_label(self):
    #     if self.current_workflow_path:
    #         filename = os.path.basename(self.current_workflow_path)
    #         self.workflow_label.setText(f"🗂️ Fichier courant : {filename}")
    #     else:
    #         self.workflow_label.setText("🗂️ Aucun fichier")
    
    def _update_workflow_label(self):
        if self.current_workflow_path:
            self.workflow_label.setText(f"🗂️ Fichier courant : {self.current_workflow_path}")
        elif hasattr(self, "temp_suggested_path"):
            self.workflow_label.setText(f"🗂️ Nouveau fichier : {self.temp_suggested_path} (non enregistré)")
        else:
            self.workflow_label.setText("🗂️ Aucun fichier")




    def _generate_temp_filename(self):
        base_name = "workflow"
        i = 1
        while True:
            candidate = os.path.join("workflows", f"{base_name}_{i:04d}.json")
            if not os.path.exists(candidate):
                return candidate
            i += 1


