from PyQt5.QtWidgets import QGraphicsItem, QGraphicsTextItem
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtCore import QRectF, Qt
from gui.pin_item import PinItem


class NodeItem(QGraphicsItem):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)



        self.rect = QRectF(0, 0, 150, 80 + 20 * max(len(plugin.inputs), len(plugin.outputs)))

        self.inputs = []
        self.outputs = []

        y_offset = 30
        for inp in plugin.inputs:
            pin = PinItem(self, inp, is_output=False)
            pin.setPos(0, y_offset)
            self.inputs.append(pin)
            y_offset += 20

        y_offset = 30
        for out in plugin.outputs:
            pin = PinItem(self, out, is_output=True)
            pin.setPos(self.rect.width() - 10, y_offset)
            self.outputs.append(pin)
            y_offset += 20

        label = QGraphicsTextItem(f"{plugin.name}", self)
        label.setDefaultTextColor(QColor("white"))
        label.setPos(10, 5)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        painter.setBrush(QBrush(QColor("#2980b9")))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRoundedRect(self.rect, 5, 5)

    
    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            scene = self.scene()
            if scene is not None:
                for pin in self.inputs + self.outputs:
                    for conn in scene.items():
                        if hasattr(conn, "start_pin") and conn.start_pin == pin:
                            conn.update_path()
                        if hasattr(conn, "end_pin") and conn.end_pin == pin:
                            conn.update_path()
        return super().itemChange(change, value)


