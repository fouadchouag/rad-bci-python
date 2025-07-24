from PySide6.QtWidgets import QGraphicsItem, QGraphicsTextItem
from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtCore import QRectF, Qt
from gui.pin_item import PinItem

class NodeItem(QGraphicsItem):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
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

        self.label = QGraphicsTextItem(f"{plugin.name}\n({plugin.language})", self)
        self.label.setDefaultTextColor(QColor("white"))
        self.label.setPos(10, 5)

    def boundingRect(self):
        return self.rect

    def paint(self, painter, option, widget=None):
        painter.setBrush(QBrush(QColor("#2980b9")))
        painter.setPen(QPen(Qt.black, 1))
        painter.drawRoundedRect(self.rect, 5, 5)
