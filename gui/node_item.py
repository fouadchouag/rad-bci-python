# gui/node_item.py

from PyQt5.QtWidgets import (
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem,
    QGraphicsProxyWidget
)
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtCore import Qt
from .pin_item import PinItem


class NodeItem(QGraphicsRectItem):
    def __init__(self, plugin_class):
        super().__init__(-60, -30, 120, 60)
        self.setBrush(QBrush(QColor(50, 50, 70)))
        self.setPen(QPen(Qt.black))
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)

        self.plugin = plugin_class()

        self._draw_label(plugin_class.name)
        self._draw_pins()
        self._add_custom_widget()  # ✅ Ajoute le widget du plugin si disponible

        print(f">>> Création du NodeItem pour : {plugin_class.__name__}")

    def _draw_label(self, name):
        self.label = QGraphicsTextItem(name, self)
        self.label.setDefaultTextColor(Qt.white)
        self.label.setPos(-50, -25)

    def _draw_pins(self):
        spacing = 20

        # Entrées
        for i, input_name in enumerate(self.plugin.inputs):
            pin = PinItem(name=input_name, is_output=False, parent=self)
            pin.setPos(-65, i * spacing)
            pin.setToolTip(f"Input: {input_name}")
            pin.node = self
            pin.pin_name = input_name

        # Sorties
        for i, output_name in enumerate(self.plugin.outputs):
            pin = PinItem(name=output_name, is_output=True, parent=self)
            pin.setPos(65, i * spacing)
            pin.setToolTip(f"Output: {output_name}")
            pin.node = self
            pin.pin_name = output_name

    def _add_custom_widget(self):
        """Ajoute un widget custom (ex: bouton, matplotlib, etc) si le plugin en fournit un."""
        if hasattr(self.plugin, "build_widget"):
            widget = self.plugin.build_widget()
            if widget:
                self.proxy = QGraphicsProxyWidget(self)
                self.proxy.setWidget(widget)
                self.proxy.setPos(-55, 20)  # Position ajustable
