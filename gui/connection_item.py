# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QGraphicsPathItem
from PyQt5.QtGui import QPainterPath, QPen, QColor
from PyQt5.QtCore import Qt, QTimer, QPointF


class ConnectionItem(QGraphicsPathItem):
    """Relie un output pin → input pin et s’abonne Rx pour propager les valeurs."""

    def __init__(self, output_pin, input_pin):
        super().__init__()

        self.output_pin = output_pin
        self.input_pin = input_pin
        self.subscription = None

        # Toujours sous les nœuds
        self.setZValue(-1000)

        # Style (surbrillance quand sélectionné)
        self._pen_normal = QPen(QColor(240, 200, 20), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self._pen_selected = QPen(QColor(255, 255, 140), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.setPen(self._pen_normal)

        self.update_path()

        # Suivi des pins
        self._timer = QTimer()
        self._timer.timeout.connect(self.update_path)
        self._timer.start(33)

        # IMPORTANT : n'ajoute pas toi-même à la scène ici.
        self.setFlag(QGraphicsPathItem.ItemIsSelectable, True)

        # Rx
        self._connect_rx()

    # ----------------- Rx -----------------

    def _connect_rx(self):
        out_node = self.output_pin.parentItem().plugin
        in_node  = self.input_pin.parentItem().plugin
        out_pin_name = getattr(self.output_pin, "name", None) or getattr(self.output_pin, "pin_name", None)
        in_pin_name  = getattr(self.input_pin, "name", None) or getattr(self.input_pin, "pin_name", None)
        if not out_pin_name or not in_pin_name:
            return

        source = out_node.get_output(out_pin_name)
        if source:
            print(f"[Connection] Subscribe: {out_node.name}.{out_pin_name} → {in_node.name}.{in_pin_name}")
            self.subscription = source.subscribe(
                lambda val: in_node.set_input(in_pin_name, val)
            )

    def cleanup(self):
        # Stop timer + Rx
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass
        if self.subscription:
            try:
                self.subscription.dispose()
            except Exception:
                pass
            self.subscription = None

        # Couper la chaîne en mettant None côté entrée
        try:
            plugin = self.input_pin.parentItem().plugin
            pin_name = getattr(self.input_pin, "name", None) or getattr(self.input_pin, "pin_name", None)
            if plugin and pin_name:
                plugin.set_input(pin_name, None)
        except Exception:
            pass

    # ----------------- Path / dessin -----------------

    def track_both_pins(self):
        self.track_pin(self.input_pin)
        self.track_pin(self.output_pin)

    def track_pin(self, _pin):
        self.update_path()

    def update_path(self):
        if not self.input_pin or not self.output_pin:
            return
        start_point = self.input_pin.scenePos()
        end_point   = self.output_pin.scenePos()

        path = QPainterPath()
        path.moveTo(start_point)
        dx = (end_point.x() - start_point.x()) * 0.5
        ctrl1 = start_point + QPointF(dx, 0)
        ctrl2 = end_point   - QPointF(dx, 0)
        path.cubicTo(ctrl1, ctrl2, end_point)
        self.setPath(path)

    # Met en évidence quand sélectionné
    def itemChange(self, change, value):
        if change == QGraphicsPathItem.ItemSelectedChange:
            self.setPen(self._pen_selected if value else self._pen_normal)
        return super().itemChange(change, value)
