from PyQt5.QtWidgets import QGraphicsPathItem
from PyQt5.QtGui import QPainterPath, QPen, QColor
from PyQt5.QtCore import Qt, QTimer, QPointF

class ConnectionItem(QGraphicsPathItem):
    def __init__(self, output_pin, input_pin):
        super().__init__()
        self.setZValue(-1)
        self.output_pin = output_pin
        self.input_pin = input_pin
        self.subscription = None

        self.setPen(QPen(QColor(240, 200, 20), 2))
        self.update_path()

        # 🔁 Animation si tu veux
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_path)
        self.timer.start(30)

        self.scene = output_pin.scene()
        if self.scene:
            self.scene.addItem(self)

        self.setFlag(QGraphicsPathItem.ItemIsSelectable)

        # 🔁 Active Rx
        self._connect_rx()

    def _connect_rx(self):
        out_node = self.output_pin.parentItem().plugin
        in_node = self.input_pin.parentItem().plugin
        out_pin_name = self.output_pin.name
        in_pin_name = self.input_pin.name

        source = out_node.get_output(out_pin_name)
        if source:
            print(f"[Connection] Subscribe: {out_node.name}.{out_pin_name} → {in_node.name}.{in_pin_name}")
            self.subscription = source.subscribe(
                lambda val: in_node.set_input(in_pin_name, val)
            )

    def cleanup(self):
        if self.subscription:
            print(f"[Connection] Cleanup subscription")
            self.subscription.dispose()
            self.subscription = None

        # 🔁 Force update logique : entrée = None
        plugin = self.input_pin.parentItem().plugin
        pin_name = self.input_pin.name
        plugin.set_input(pin_name, None)



    def update_path(self):
        p1 = self.output_pin.scenePos()
        p2 = self.input_pin.scenePos()

        dx = (p2.x() - p1.x()) * 0.5
        ctrl1 = p1 + QPointF(dx, 0)
        ctrl2 = p2 - QPointF(dx, 0)

        path = QPainterPath()
        path.moveTo(p1)
        path.cubicTo(ctrl1, ctrl2, p2)
        self.setPath(path)
