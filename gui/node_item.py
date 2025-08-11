from PyQt5.QtWidgets import (
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem, QGraphicsProxyWidget, QWidget
)
from PyQt5.QtGui import QBrush, QColor, QPen, QFontMetricsF, QFont
from PyQt5.QtCore import Qt
from .pin_item import PinItem


class NodeItem(QGraphicsRectItem):
    # métriques simples
    HEADER_H = 28
    ROW_H = 22
    PADDING_X = 12
    PADDING_Y = 8
    PIN_RADIUS = 8            # ~ rayon visuel du pin
    LABEL_GAP = 6             # espace pin <-> texte

    def __init__(self, plugin_class):
        super().__init__()

        self.plugin = plugin_class()
        self.input_pins = []
        self.output_pins = []
        self._title_item = None
        self.proxy = None

        # Style général (on garde ton thème)
        self.setBrush(QBrush(QColor(50, 50, 70)))
        self.setPen(QPen(Qt.black))
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)

        # polices
        self._font_title = QFont("Arial", 10, QFont.Bold)
        self._font_io = QFont("Arial", 9)

        # construire
        self._draw_label(self.plugin.__class__.name if hasattr(self.plugin.__class__, "name") else self.plugin.__class__.__name__)
        base_h = self._draw_pins_and_size()   # calcule largeur/hauteur en fonction des libellés
        self._center_title()                  # centre le titre une fois la taille connue
        self._add_custom_widget(base_h)       # place le widget sous les pins si présent

        print(f">>> Création du NodeItem pour : {plugin_class.__name__}")

    # --------------------- Titre ---------------------
    def _draw_label(self, name: str):
        self._title_item = QGraphicsTextItem(name, self)
        self._title_item.setDefaultTextColor(Qt.white)
        self._title_item.setFont(self._font_title)

    def _center_title(self):
        # centre horizontalement le titre dans la zone header (pas de clipping)
        if not self._title_item:
            return
        fm = QFontMetricsF(self._title_item.font())
        text_w = fm.width(self._title_item.toPlainText())
        text_h = fm.height()
        rect = self.rect()
        x = rect.x() + (rect.width() - text_w) / 2.0
        y = rect.y() + (self.HEADER_H - text_h) / 2.0
        self._title_item.setPos(x, y)

    # --------------- Pins + dimensionnement ----------
    def _draw_pins_and_size(self):
        """Place les pins SOUS le titre et dimensionne le node pour éviter tout chevauchement."""
        # Nettoyage si refresh
        for p in self.input_pins + self.output_pins:
            try:
                p.setParentItem(None)
            except Exception:
                pass
        self.input_pins.clear()
        self.output_pins.clear()

        fm_title = QFontMetricsF(self._font_title)
        fm_io = QFontMetricsF(self._font_io)

        # Largeur minimale imposée par le titre
        title_w = fm_title.width(self._title_item.toPlainText()) + 2 * self.PADDING_X

        # Largeur des libellés (gauche/droite)
        max_in_w = max((fm_io.width(str(n)) for n in getattr(self.plugin, "inputs", [])), default=0.0)
        max_out_w = max((fm_io.width(str(n)) for n in getattr(self.plugin, "outputs", [])), default=0.0)

        # Colonnes :
        # - gauche : [PADDING_X] + pin + LABEL_GAP + label + [PADDING_X]
        # - droite : [PADDING_X] + label + LABEL_GAP + pin + [PADDING_X]
        left_col_w = self.PADDING_X + self.PIN_RADIUS + self.LABEL_GAP + max_in_w + self.PADDING_X
        right_col_w = self.PADDING_X + max_out_w + self.LABEL_GAP + self.PIN_RADIUS + self.PADDING_X

        content_w = max(160.0, title_w, left_col_w + right_col_w)

        # Coordonnées X des pins
        left_pin_x = self.PADDING_X + self.PIN_RADIUS
        right_pin_x = content_w - (self.PADDING_X + self.PIN_RADIUS)

        # Y de départ (juste sous le header)
        y_top = self.HEADER_H + self.PADDING_Y
        lines = max(len(getattr(self.plugin, "inputs", [])), len(getattr(self.plugin, "outputs", [])))

        # --- Inputs (gauche) ---
        for i, name in enumerate(getattr(self.plugin, "inputs", [])):
            cy = y_top + i * self.ROW_H + self.ROW_H / 2.0
            pin = PinItem(name=name, is_output=False, parent=self)
            pin.setPos(left_pin_x, cy)
            pin.node = self
            pin.pin_name = name
            self.input_pins.append(pin)

            # libellé à droite du pin
            text = QGraphicsTextItem(str(name), self)
            text.setDefaultTextColor(Qt.green)
            text.setFont(self._font_io)
            text.setPos(left_pin_x + self.PIN_RADIUS + self.LABEL_GAP, cy - fm_io.height() / 2.0)

        # --- Outputs (droite) ---
        for i, name in enumerate(getattr(self.plugin, "outputs", [])):
            cy = y_top + i * self.ROW_H + self.ROW_H / 2.0
            pin = PinItem(name=name, is_output=True, parent=self)
            pin.setPos(right_pin_x, cy)
            pin.node = self
            pin.pin_name = name
            self.output_pins.append(pin)

            # libellé à gauche du pin, aligné à droite -> pas de chevauchement
            text_w = fm_io.width(str(name))
            text = QGraphicsTextItem(str(name), self)
            text.setDefaultTextColor(Qt.red)
            text.setFont(self._font_io)
            text.setPos(right_pin_x - self.PIN_RADIUS - self.LABEL_GAP - text_w, cy - fm_io.height() / 2.0)

        # Hauteur de base (titre + pins)
        base_h = self.HEADER_H + self.PADDING_Y + lines * self.ROW_H + self.PADDING_Y
        self.setRect(0, 0, content_w, max(base_h, self.HEADER_H + 2 * self.PADDING_Y))
        return base_h

    # ----------------- Widget en bas ------------------
    def _add_custom_widget(self, base_h: float):
        """Place un éventuel widget SOUS les pins (et redimensionne le node)."""
        if not hasattr(self.plugin, "build_widget"):
            return
        w = self.plugin.build_widget()
        if not isinstance(w, QWidget):
            return

        # créer le proxy
        if self.proxy is None:
            self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(w)

        # largeur dispo et hauteur suggérée
        target_w = max(60, int(self.rect().width() - 2 * self.PADDING_X))
        hint = w.sizeHint()
        target_h = hint.height() if hint.isValid() else 80
        try:
            w.resize(target_w, target_h)
        except Exception:
            pass

        # positionner sous les pins
        y = base_h + self.PADDING_Y
        self.proxy.setPos(self.PADDING_X, y)

        # étendre le node pour inclure le widget
        new_h = y + target_h + self.PADDING_Y
        self.setRect(0, 0, self.rect().width(), new_h)

        # recentrer le titre après resize
        self._center_title()

    # --------------- API existante --------------------
    def _auto_resize(self):
        # la taille est entièrement gérée par _draw_pins_and_size() + _add_custom_widget()
        pass

    def get_input_pin_by_name(self, name):
        for pin in self.input_pins:
            if pin.name == name:
                return pin
        return None

    def get_output_pin_by_name(self, name):
        for pin in self.output_pins:
            if pin.name == name:
                return pin
        return None
