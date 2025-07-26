from PyQt5.QtWidgets import QGraphicsPathItem
from PyQt5.QtGui import QPainterPath, QPen
from PyQt5.QtCore import Qt, QPointF


class ConnectionItem(QGraphicsPathItem):
   
    def __init__(self, start_pin, end_pos):
        super().__init__()
        self.start_pin = start_pin
        self.end_pin = None
        self.end_pos = end_pos
        self.setZValue(-1)
        self.setPen(QPen(Qt.black, 2))
        self.setFlags(self.flags() | self.ItemIsSelectable)
        self.track_pin(start_pin)


    def track_pin(self, pin):
        self.start_pin = pin
        self.update_path()

    def set_end_pos(self, pos):
        self.end_pos = pos
        self.update_path()

    def set_end_pin(self, pin):
        self.end_pin = pin
        self.end_pos = pin.scenePos()

    def track_both_pins(self):
        if self.start_pin and self.end_pin:
            self.update_path()

    def update_path(self):
        if not self.start_pin:
            return

        start_pos = self.start_pin.scenePos()
        end_pos = self.end_pos

        if self.end_pin:
            end_pos = self.end_pin.scenePos()

        path = QPainterPath()
        path.moveTo(start_pos)

        dx = (end_pos.x() - start_pos.x()) * 0.5
        ctrl1 = QPointF(start_pos.x() + dx, start_pos.y())
        ctrl2 = QPointF(end_pos.x() - dx, end_pos.y())

        path.cubicTo(ctrl1, ctrl2, end_pos)
        self.setPath(path)
