# gui/pin_item.py

from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtGui import QBrush, QColor, QPen, QPainterPath
from PyQt5.QtCore import Qt, QPointF
from .connection_item import ConnectionItem


class PinItem(QGraphicsEllipseItem):
    def __init__(self, name, is_output=False, parent=None):
        super().__init__(-5, -5, 10, 10, parent)
        self.setBrush(QBrush(QColor(200, 100, 100) if is_output else QColor(100, 200, 100)))
        self.setPen(QPen(Qt.black))
        self.setZValue(1)

        self.name = name
        self.is_output = is_output
        self.setAcceptHoverEvents(True)
        self.setFlag(self.ItemSendsScenePositionChanges)

        self.drag_path_item = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = self.scenePos()
            self.drag_path_item = self.scene().addPath(self._create_drag_path(event.scenePos()), QPen(Qt.yellow, 2))
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_path_item:
            path = self._create_drag_path(event.scenePos())
            self.drag_path_item.setPath(path)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.drag_path_item:
            end_items = self.scene().items(event.scenePos())
            for item in end_items:
                if isinstance(item, PinItem) and item != self:
                    if self.is_output != item.is_output:
                        output_pin = self if self.is_output else item
                        input_pin = item if self.is_output else self

                        # Crée la connexion visuelle et logique
                        ConnectionItem(output_pin, input_pin)

                        # Connexion Rx : output → input
                        out_node = output_pin.node.plugin
                        in_node = input_pin.node.plugin

                        source = out_node.get_output(output_pin.pin_name)
                        if source:
                            source.subscribe(lambda val: in_node.set_input(input_pin.pin_name, val))

                        break

            # Nettoyage visuel
            self.scene().removeItem(self.drag_path_item)
            self.drag_path_item = None
            event.accept()

    def _create_drag_path(self, end_pos):
        path = QPainterPath()
        path.moveTo(self.scenePos())
        dx = (end_pos.x() - self.scenePos().x()) * 0.5
        ctrl1 = self.scenePos() + QPointF(dx, 0)
        ctrl2 = end_pos - QPointF(dx, 0)
        path.cubicTo(ctrl1, ctrl2, end_pos)
        return path
