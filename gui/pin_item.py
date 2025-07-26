# gui/pin_item.py

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

        # Label du pin
        label = QGraphicsTextItem(name, self)
        label.setDefaultTextColor(QColor("white"))
        label.setPos(-55 if is_output else 12, -5)

    def mousePressEvent(self, event):
        scene = self.scene()
        if not scene or not hasattr(scene, "main_window"):
            return

        mw = scene.main_window

        if mw.pending_connection is None:
            # ✅ Nouvelle connexion
            conn = ConnectionItem(self, self.scenePos())
            conn.track_pin(self)
            mw.set_pending_connection(conn)

            # 🔒 Ne pas ajouter deux fois
            if conn.scene() is None:
                scene.addItem(conn)
        else:
            # ✅ Connexion existante → finalisation
            mw.pending_connection.set_end_pin(self)
            mw.pending_connection.track_both_pins()

            if mw.pending_connection.scene() is None:
                scene.addItem(mw.pending_connection)

            # 🧠 Exécution automatique après création de lien
            mw._auto_run_graph()
            mw.pending_connection = None

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        scene = self.scene()
        if hasattr(scene, "main_window"):
            conn = scene.main_window.pending_connection
            if conn:
                conn.set_end_pos(event.scenePos())
        super().mouseMoveEvent(event)
