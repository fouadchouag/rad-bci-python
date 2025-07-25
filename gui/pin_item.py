from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsTextItem
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtCore import Qt
from gui.connection_item import ConnectionItem


class PinItem(QGraphicsEllipseItem):
    def __init__(self, parent, name, is_output=False):
        super().__init__(-5, -5, 10, 10, parent)
        self.setBrush(QBrush(QColor("#2ecc71") if is_output else QColor("#e74c3c")))
        self.setFlag(QGraphicsEllipseItem.ItemIsSelectable)
        self.setFlag(QGraphicsEllipseItem.ItemIsMovable, False)
        self.name = name
        self.is_output = is_output
        self.temp_connection = None

        label = QGraphicsTextItem(name, parent)
        label.setDefaultTextColor(QColor("white"))
        label.setPos(15 if not is_output else -50, self.y() - 5)

    def mousePressEvent(self, event):
        self.temp_connection = ConnectionItem(self, self.scenePos())
        self.temp_connection.track_pin(self)

        scene = self.scene()
        if hasattr(scene, "main_window") and hasattr(scene.main_window, "set_pending_connection"):
            scene.main_window.set_pending_connection(self.temp_connection)

        scene.addItem(self.temp_connection)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.temp_connection:
            self.temp_connection.set_end_pos(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.temp_connection:
            self.temp_connection = None
        super().mouseReleaseEvent(event)
