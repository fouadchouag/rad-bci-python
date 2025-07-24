from PySide6.QtWidgets import QGraphicsPathItem
from PySide6.QtGui import QPainterPath, QPen, QColor
from PySide6.QtCore import QPointF, QEvent

class ConnectionItem(QGraphicsPathItem):
    def __init__(self, start_pin, end_pos):
        super().__init__()
        self.setZValue(-1)
        self.start_pin = start_pin
        self.end_pin = None
        self.end_pos = end_pos
        self.setPen(QPen(QColor("#f1c40f"), 2))

    def set_end_pos(self, pos):
        self.end_pos = pos
        self.update_path()

    def set_end_pin(self, pin):
        self.end_pin = pin
        self.update_path()

    def update_path(self):
        start = self.start_pin.scenePos()
        end = self.end_pin.scenePos() if self.end_pin else self.end_pos
        path = QPainterPath(start)
        dx = (end.x() - start.x()) * 0.5
        ctrl1 = QPointF(start.x() + dx, start.y())
        ctrl2 = QPointF(end.x() - dx, end.y())
        path.cubicTo(ctrl1, ctrl2, end)
        self.setPath(path)

    def track_pin(self, pin):
        node = pin.parentItem()
        if node and node.scene() == self.scene():
            node.installSceneEventFilter(self)

    def track_both_pins(self):
        self.track_pin(self.start_pin)
        if self.end_pin:
            self.track_pin(self.end_pin)

    def sceneEventFilter(self, watched, event):
        if event.type() in (QEvent.GraphicsSceneMouseMove, QEvent.GraphicsSceneMouseRelease):
            self.update_path()
        return False
