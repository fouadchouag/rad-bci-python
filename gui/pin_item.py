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

        # Label affiché près du pin
        label = QGraphicsTextItem(name, self)
        label.setDefaultTextColor(QColor("white"))

        if is_output:
            label.setPos(-55, -5)
        else:
            label.setPos(12, -5)

    def mousePressEvent(self, event):
        scene = self.scene()
        if scene is None or not hasattr(scene, "main_window"):
            return

        mw = scene.main_window

        if mw.pending_connection is None:
            # Démarre une nouvelle connexion
            conn = ConnectionItem(self, self.scenePos())
            conn.track_pin(self)
            mw.set_pending_connection(conn)

            if conn.scene() is None:
                print("[DEBUG] Ajout de ConnectionItem à la scène")
                scene.addItem(conn)
        else:
            # Termine la connexion
            mw.pending_connection.set_end_pin(self)
            mw.pending_connection.track_both_pins()
            mw.pending_connection = None

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if hasattr(scene, "main_window"):
            conn = scene.main_window.pending_connection
            if conn:
                conn.set_end_pos(event.scenePos())
        super().mouseMoveEvent(event)
