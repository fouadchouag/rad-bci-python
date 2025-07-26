from PyQt5.QtWidgets import QGraphicsItem, QGraphicsTextItem
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtCore import QRectF, Qt
from gui.pin_item import PinItem


class NodeItem(QGraphicsItem):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )

        self.inputs = []
        self.outputs = []

        # 🔷 Titre principal : nom du plugin
        label_title = QGraphicsTextItem(plugin.name, self)
        label_title.setDefaultTextColor(QColor("white"))
        label_title.setPos(10, 5)

        # 🔷 Sous-titre : langage
        label_lang = QGraphicsTextItem(f"[{plugin.language}]", self)
        label_lang.setDefaultTextColor(QColor("lightgray"))
        label_lang.setPos(10, 20)

        # 🔷 Espace réservé avant les pins
        pin_start_y = 45

        y_offset = pin_start_y
        for inp in plugin.inputs:
            pin = PinItem(self, inp, is_output=False)
            pin.setPos(0, y_offset)
            self.inputs.append(pin)
            y_offset += 20

        y_offset = pin_start_y
        for out in plugin.outputs:
            pin = PinItem(self, out, is_output=True)
            pin.setPos(140, y_offset)  # À droite du node
            self.outputs.append(pin)
            y_offset += 20

        # 🔷 Hauteur dynamique
        total_pins = max(len(self.inputs), len(self.outputs))
        height = pin_start_y + total_pins * 20 + 10
        self.rect = QRectF(0, 0, 150, height)

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
