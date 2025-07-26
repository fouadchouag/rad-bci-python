from PyQt5.QtWidgets import QGraphicsItem, QGraphicsTextItem
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtCore import QRectF, Qt
from gui.pin_item import PinItem


class NodeItem(QGraphicsItem):
    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self.plugin._node_item = self  # 🔁 Permet au plugin d’accéder au NodeItem
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )

        
        
        self.input_pins = []
        self.output_pins = []

        # 🔷 Titre principal
        label_title = QGraphicsTextItem(plugin.name, self)
        label_title.setDefaultTextColor(QColor("white"))
        label_title.setPos(10, 5)

        # 🔷 Langage
        label_lang = QGraphicsTextItem(f"[{plugin.language}]", self)
        label_lang.setDefaultTextColor(QColor("lightgray"))
        label_lang.setPos(10, 20)

        pin_start_y = 45
        y_offset = pin_start_y

        for inp in plugin.inputs:
            pin = PinItem(self, inp, is_output=False)
            pin.setPos(0, y_offset)
            self.input_pins.append(pin)
            y_offset += 20

        y_offset = pin_start_y
        for out in plugin.outputs:
            pin = PinItem(self, out, is_output=True)
            pin.setPos(140, y_offset)
            self.output_pins.append(pin)
            y_offset += 20

        total_pins = max(len(self.input_pins), len(self.output_pins))
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
                for pin in self.input_pins + self.output_pins:
                    for conn in scene.items():
                        if hasattr(conn, "start_pin") and conn.start_pin == pin:
                            conn.update_path()
                        if hasattr(conn, "end_pin") and conn.end_pin == pin:
                            conn.update_path()
        return super().itemChange(change, value)

    def propagate(self, value_map):
        """Exécute ce node et propage ses outputs vers les nodes suivants."""
        if not hasattr(self.plugin, "execute"):
            return

        # Collecte des entrées
        inputs = {}
        for pin in self.input_pins:
            key = (self, pin.name)
            inputs[pin.name] = value_map.get(key, None)

        # Exécution
        outputs = self.plugin.execute(inputs)
        print(f"Node: {self.plugin.name} -> Output: {outputs}")

        # Propagation à chaque pin de sortie
        for output_pin in self.output_pins:
            val = outputs.get(output_pin.name)
            for item in self.scene().items():
                if hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                    if item.start_pin == output_pin:
                        dest_pin = item.end_pin
                        dest_node = dest_pin.parentItem()
                        value_map[(dest_node, dest_pin.name)] = val
                        dest_node.propagate(value_map)
