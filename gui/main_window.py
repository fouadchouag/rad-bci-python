from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame, QGraphicsPathItem
)
from PyQt5.QtCore import Qt
from core.plugin_registry import discover_plugins
from .node_item import NodeItem
from gui.lowcode_creator import LowCodeCreator


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

    def _init_ui(self):
        # --- Conteneur principal vertical ---
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # --- Barre d’outils horizontale ---
        toolbar = QHBoxLayout()

        btn_new = QPushButton("🆕 Nouveau")
        btn_load = QPushButton("📂 Charger")
        btn_save = QPushButton("💾 Sauvegarder")
        btn_lowcode = QPushButton("🛠️ Dev Mode (➕ Ajouter un Node)")

        for btn in [btn_new, btn_load, btn_save, btn_lowcode]:
            toolbar.addSpacing(10)
            toolbar.addWidget(btn)
            btn.setMinimumHeight(40)
            btn.setStyleSheet("font-weight: bold; font-size: 14px;")

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setFixedHeight(60)
        main_layout.addWidget(toolbar_widget)

        # --- Partie centrale : palette + éditeur ---
        center_layout = QHBoxLayout()

        # Palette latérale
        palette_frame = QFrame()
        palette_layout = QVBoxLayout(palette_frame)
        palette_frame.setLayout(palette_layout)

        for category, plugin_list in self.plugins_by_category.items():
            cat_label = QLabel(f"📁 {category}")
            cat_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
            palette_layout.addWidget(cat_label)

            for plugin_class in plugin_list:
                btn = QPushButton(plugin_class.name)
                btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))
                palette_layout.addWidget(btn)

        # dev_button = QPushButton("🛠️ Dev Mode")
        # dev_button.clicked.connect(self.open_lowcode_editor)
        # palette_layout.addWidget(dev_button)

        palette_scroll = QScrollArea()
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setWidget(palette_frame)
        palette_scroll.setFixedWidth(220)

        center_layout.addWidget(palette_scroll)
        center_layout.addWidget(self.view, stretch=1)

        main_layout.addLayout(center_layout)

        # Connexions des boutons
        btn_new.clicked.connect(self._new_workflow)
        btn_load.clicked.connect(self._load_workflow)
        btn_save.clicked.connect(self._save_workflow)
        btn_lowcode.clicked.connect(self._show_lowcode_creator)

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

    def open_lowcode_editor(self):
        self.lowcode_window = LowCodeCreator()
        self.lowcode_window.show()

    def _new_workflow(self):
        print("🆕 Nouveau workflow")

    def _load_workflow(self):
        print("📂 Charger workflow")

    def _save_workflow(self):
        print("💾 Sauvegarder workflow")

    def _show_lowcode_creator(self):
        self.open_lowcode_editor()
