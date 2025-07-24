from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QListWidget, QGraphicsView, QGraphicsScene, QSplitter
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView
from runtime.plugin_manager import PluginManager
from gui.node_item import NodeItem
from gui.connection_item import ConnectionItem


class MainWindow(QMainWindow):
    _instance = None  # Private singleton reference

    def __init__(self):
        super().__init__()
        MainWindow._instance = self
        self.setWindowTitle("PyFlowBCI - No-Code RAD Tool")
        self.setMinimumSize(1000, 600)

        self._init_ui()
        self._load_plugins()
        self.pending_connection = None

    @staticmethod
    def instance():
        return MainWindow._instance

    def _init_ui(self):
        central = QWidget()
        layout = QHBoxLayout(central)

        splitter = QSplitter()

        self.palette = QListWidget()
        self.palette.setMinimumWidth(120)
        self.palette.setMaximumWidth(250)
        self.palette.setResizeMode(QListWidget.Adjust)
        self.palette.itemDoubleClicked.connect(self._add_node_from_palette)

        self.scene = QGraphicsScene()
        self.canvas = QGraphicsView(self.scene)

        self._add_delete_shortcut()
        self.scene.mouseReleaseEvent = self._handle_scene_mouse_release

        splitter.addWidget(self.palette)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)
        self.setCentralWidget(central)

    def _add_delete_shortcut(self):
        def delete_selected():
            for item in self.scene.selectedItems():
                # Also remove any ConnectionItems attached to the node
                if isinstance(item, NodeItem):
                    for conn in list(self.scene.items()):
                        if isinstance(conn, ConnectionItem):
                            if conn.start_pin.parentItem() == item or (
                                conn.end_pin and conn.end_pin.parentItem() == item
                            ):
                                self.scene.removeItem(conn)
                self.scene.removeItem(item)

        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.canvas.keyPressEvent = lambda event: delete_selected() if event.key() == Qt.Key_Delete else QGraphicsView.keyPressEvent(self.canvas, event)

    def _load_plugins(self):
        self.plugins = PluginManager.load_all_plugins("plugins/examples")
        for plugin in self.plugins:
            self.palette.addItem(f"{plugin.name} [{plugin.language}]")

    def _add_node_from_palette(self, item):
        name = item.text()
        plugin = next((p for p in self.plugins if f"{p.name} [{p.language}]" == name), None)
        if plugin:
            node = NodeItem(plugin)
            node.setPos(100, 100)
            self.scene.addItem(node)

    def _handle_scene_mouse_release(self, event):
        if self.pending_connection:
            from gui.pin_item import PinItem
            items = self.scene.items(event.scenePos())
            for item in items:
                if isinstance(item, PinItem) and item != self.pending_connection.start_pin:
                    if item.is_output != self.pending_connection.start_pin.is_output:
                        self.pending_connection.set_end_pin(item)
                        self.pending_connection.track_both_pins()
                        self.scene.addItem(self.pending_connection)
                        break
            else:
                self.scene.removeItem(self.pending_connection)
            self.pending_connection = None
        QGraphicsScene.mouseReleaseEvent(self.scene, event)

    def set_pending_connection(self, connection):
        self.pending_connection = connection
