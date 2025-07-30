from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame, QGraphicsPathItem
)
from PyQt5.QtCore import Qt
from core.plugin_registry import discover_plugins
from .node_item import NodeItem  # à créer juste après



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
        central_widget = QWidget()
        central_layout = QHBoxLayout()
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)

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

        palette_scroll = QScrollArea()
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setWidget(palette_frame)
        palette_scroll.setFixedWidth(220)

        # Layout final
        central_layout.addWidget(palette_scroll)
        central_layout.addWidget(self.view, stretch=1)

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
                # ✅ Suppression d'un nœud (ex: Adder)
                if hasattr(item, "plugin"):
                    to_remove = []
                    for obj in self.scene.items():
                        if isinstance(obj, QGraphicsPathItem) and hasattr(obj, "output_pin") and hasattr(obj, "input_pin"):
                            if obj.output_pin.node == item or obj.input_pin.node == item:
                                to_remove.append(obj)

                    for conn in to_remove:
                        if hasattr(conn, "cleanup"):
                            conn.cleanup()

                            # 🔁 Mise à jour du nœud cible même si la source est supprimée
                            if hasattr(conn, "input_pin") and conn.input_pin and hasattr(conn.input_pin, "node"):
                                input_node = conn.input_pin.node
                                if hasattr(input_node, "plugin"):
                                    input_node.plugin.set_input(conn.input_pin.name, None)

                        self.scene.removeItem(conn)

                    # Nettoie le plugin (ex: BehaviorSubject)
                    item.plugin.cleanup()
                    self.scene.removeItem(item)

                # ✅ Suppression d’un lien directement sélectionné
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
