from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QListWidget, QGraphicsView,
    QGraphicsScene, QVBoxLayout, QSplitter
)
from PyQt5.QtCore import Qt
from gui.node_item import NodeItem
from runtime.graph_executor import GraphExecutor


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RAD BCI Python")
        self.setGeometry(100, 100, 1000, 600)

        self._init_ui()
        self._load_plugins()

        self.pending_connection = None  # <== Connexion temporaire

    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        self.setCentralWidget(main_widget)

        splitter = QSplitter()

        # Palette latérale
        self.palette = QListWidget()
        self.palette.setMaximumWidth(200)
        self.palette.itemDoubleClicked.connect(self._add_node_from_palette)

        # Vue graphique
        self.scene = QGraphicsScene()
        self.scene.main_window = self
        self.scene.setSceneRect(0, 0, 2000, 2000)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())

        # Gérer les connexions à la souris
        self.scene.mouseReleaseEvent = self._handle_scene_mouse_release

        splitter.addWidget(self.palette)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter)
        self.view.setStyleSheet("background-color: white;")
         # 🎯 Activation de la suppression avec la touche Delete
        self.view.keyPressEvent = self._handle_key_press



    def _load_plugins(self):
        from plugins.registry import PLUGIN_REGISTRY

        self.plugins = [cls() for cls in PLUGIN_REGISTRY]

        for plugin in self.plugins:
            self.palette.addItem(f"{plugin.name} [{plugin.language}]")


    def _add_node_from_palette(self, item):
        name = item.text()
        for plugin in self.plugins:
            if plugin.name in name:
                node = NodeItem(plugin)
                node.setPos(300, 300)  # 🟢 Position visible dans la scène
                self.scene.addItem(node)

                # 🟢 Centrer la vue sur le nouveau node
                self.view.centerOn(node)

                self._auto_run_graph()
                break


    def _auto_run_graph(self):
        executor = GraphExecutor(self.scene)
        executor.execute()

    def _handle_scene_mouse_release(self, event):
        if self.pending_connection:
            items = self.scene.items(event.scenePos())
            found_valid_pin = False

            for item in items:
                if hasattr(item, "is_output") and item != self.pending_connection.start_pin:
                    # 🔒 Refuser les connexions entre deux pins de même type
                    if item.is_output == self.pending_connection.start_pin.is_output:
                        print("[DEBUG] Connexion refusée : même type de pin (input → input ou output → output)")
                        break

                    # 🔒 Refuser si un lien existe déjà vers ce pin d'entrée
                    if not item.is_output:  # uniquement pour les inputs
                        for conn in self.scene.items():
                            if hasattr(conn, "end_pin") and conn.end_pin == item:
                                print("[DEBUG] Connexion refusée : un pin d’entrée ne peut avoir qu’une seule source")
                                break
                        else:
                            # ✅ Autorisé
                            self.pending_connection.set_end_pin(item)
                            self.pending_connection.track_both_pins()
                            found_valid_pin = True
                            break
                    else:
                        # ✅ Cas rare mais possible (connexion depuis un input vers un output)
                        self.pending_connection.set_end_pin(item)
                        self.pending_connection.track_both_pins()
                        found_valid_pin = True
                        break

            if not found_valid_pin:
                print("[DEBUG] Connexion annulée")
                self.scene.removeItem(self.pending_connection)

            self.pending_connection = None

        QGraphicsScene.mouseReleaseEvent(self.scene, event)


    
    def _handle_key_press(self, event):
        if event.key() == Qt.Key_Delete:
            selected_items = self.scene.selectedItems()
            for item in selected_items:
                if hasattr(item, "plugin"):  # Si c'est un NodeItem
                    # Supprimer les connexions attachées
                    for conn in self.scene.items():
                        if hasattr(conn, "start_pin") and hasattr(conn, "end_pin"):
                            if conn.start_pin and conn.start_pin.parentItem() == item:
                                self.scene.removeItem(conn)
                            elif conn.end_pin and conn.end_pin.parentItem() == item:
                                self.scene.removeItem(conn)
                    self.scene.removeItem(item)

                elif hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                    # C’est une ConnectionItem
                    self.scene.removeItem(item)

            self._auto_run_graph()
        else:
            # Si une autre touche est pressée
            QGraphicsView.keyPressEvent(self.view, event)


    def set_pending_connection(self, connection):
        self.pending_connection = connection
