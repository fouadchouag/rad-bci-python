# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsPathItem
from PyQt5.QtGui import QBrush, QPen, QColor, QPainterPath
from PyQt5.QtCore import Qt, QPointF
import math

# Astuce : pas d'import de ConnectionItem ici pour éviter tout cycle.
# On fera l'import à la volée au moment de créer la connexion.


class PinItem(QGraphicsEllipseItem):
    """Pin circulaire pour connecter des nœuds par drag&drop (avec prévisualisation + snap)."""

    RADIUS  = 8.0
    SNAP_PX = 28.0  # rayon de capture au relâchement

    def __init__(self, name: str, is_output: bool, parent=None):
        super().__init__(parent)

        # Identité / rétro-compat
        self.name = str(name)
        self._pin_name = self.name  # compat .pin_name (certains appels externes)
        self.is_output = bool(is_output)
        self.node = parent

        # Style
        self._connected = False
        self._hover = False

        # Drag preview
        self._dragging = False
        self._preview: QGraphicsPathItem = None

        # Géométrie
        self.setRect(-self.RADIUS, -self.RADIUS, 2 * self.RADIUS, 2 * self.RADIUS)
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setZValue(10)

        # Couleurs
        self._col_fill_in  = QColor(60, 180, 110)   # inputs
        self._col_fill_out = QColor(220, 80, 80)    # outputs
        self._col_stroke   = QColor(20, 20, 20)
        self._col_hover    = QColor(255, 230, 120)

        self._apply_style()

    # ---- rétro-compat .pin_name ----
    @property
    def pin_name(self):
        return self.name

    @pin_name.setter
    def pin_name(self, v):
        self.name = str(v)

    # -------------------- état visuel --------------------
    def set_connected(self, b: bool):
        self._connected = bool(b)
        self._apply_style()

    def _apply_style(self):
        base = self._col_fill_out if self.is_output else self._col_fill_in
        fill = QColor(base)
        if self._connected:
            fill = fill.darker(115)
        if self._hover:
            fill = self._col_hover
        self.setBrush(QBrush(fill))
        self.setPen(QPen(self._col_stroke, 1.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

    def hoverEnterEvent(self, ev):
        self._hover = True
        self._apply_style()
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):
        self._hover = False
        self._apply_style()
        super().hoverLeaveEvent(ev)

    # -------------------- drag & snap --------------------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            # Démarre un drag : on dessine une “ligne fantôme”
            self._dragging = True
            sc = self.scene()
            if sc is not None:
                self._preview = QGraphicsPathItem()
                self._preview.setZValue(-500)  # sous les nœuds
                self._preview.setPen(QPen(QColor(240, 200, 20, 180), 2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
                sc.addItem(self._preview)
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._dragging or self.scene() is None or self._preview is None:
            return super().mouseMoveEvent(ev)

        p0 = self.scenePos()                    # pin d'origine
        p1 = ev.scenePos()                      # curseur
        dx = (p1.x() - p0.x()) * 0.5
        path = QPainterPath(p0)
        path.cubicTo(QPointF(p0.x()+dx, p0.y()), QPointF(p1.x()-dx, p1.y()), p1)
        self._preview.setPath(path)
        ev.accept()

    def mouseReleaseEvent(self, ev):
        sc = self.scene()
        if self._dragging and sc is not None:
            # Retire la preview
            if self._preview is not None:
                try:
                    sc.removeItem(self._preview)
                except Exception:
                    pass
                self._preview = None

            # Chercher le pin compatible le plus proche (snap)
            target = self._find_compatible_target(ev.scenePos())
            if target is not None:
                self._create_connection(self, target)

        self._dragging = False
        ev.accept()  # évite de déplacer le node pendant la manip

    # -------------------- helpers --------------------
    def _find_compatible_target(self, pos_scene: QPointF):
        """Retourne le PinItem compatible le plus proche dans un rayon SNAP_PX."""
        sc = self.scene()
        if sc is None:
            return None

        best_pin = None
        best_d2 = (self.SNAP_PX + 1) ** 2  # distance² min

        for it in sc.items():
            if it is self:
                continue
            if not isinstance(it, PinItem):
                continue
            if it.is_output == self.is_output:
                continue
            # pas sur le même node
            if it.parentItem() is self.parentItem():
                continue

            d2 = (it.scenePos().x() - pos_scene.x()) ** 2 + (it.scenePos().y() - pos_scene.y()) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_pin = it

        return best_pin

    def _create_connection(self, pin_a, pin_b):
        """Crée la connexion graphique + abonnement Rx."""
        # déterminer sens
        output_pin = pin_a if pin_a.is_output else pin_b
        input_pin  = pin_b if pin_a.is_output else pin_a

        try:
            from .connection_item import ConnectionItem  # import local => pas de cycle
            sc = self.scene()
            if sc is None:
                return
            conn = ConnectionItem(output_pin, input_pin)
            sc.addItem(conn)
            conn.track_both_pins()

            # feedback visuel
            output_pin.set_connected(True)
            input_pin.set_connected(True)
        except Exception as e:
            print(f"[PinItem] Warning: failed to create connection: {e}")
