from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsTextItem, QApplication
from PySide6.QtGui import QBrush, QColor
from PySide6.QtCore import QRectF, Qt, QEvent
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
        if is_output:
            label.setPos(parent.boundingRect().width() - 60, self.y() - 5)
        else:
            label.setPos(15, self.y() - 5)

    def mousePressEvent(self, event):
        self.temp_connection = ConnectionItem(self, self.scenePos())
        self.temp_connection.track_pin(self)  # Always track source node
        main_window = QApplication.activeWindow()
        if main_window:
            main_window.set_pending_connection(self.temp_connection)
        self.scene().addItem(self.temp_connection)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.temp_connection:
            self.temp_connection.set_end_pos(event.scenePos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.temp_connection:
            self.temp_connection = None
        super().mouseReleaseEvent(event)
