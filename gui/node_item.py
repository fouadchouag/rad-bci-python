from PyQt5.QtWidgets import (
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsItem, QGraphicsProxyWidget, QWidget,
    QGraphicsView
)
from PyQt5.QtGui import QBrush, QColor, QPen, QFontMetricsF, QFont, QPainterPath
from PyQt5.QtCore import Qt, QPointF
from .pin_item import PinItem

# Échelle globale des badges (palette + nœuds)
BADGE_SCALE = 0.85  # 85% du size d’origine

# --- Badge langage : code court + couleur ---
LANG_BADGE = {
    "Python":  ("PY", QColor(40, 120, 200)),
    "Rust":    ("RS", QColor(230, 120, 40)),
    "Node.js": ("JS", QColor(60, 160, 60)),
    "C++":     ("C++", QColor(90, 90, 160)),
    "C":       ("C", QColor(90, 160, 160)),
    "R":       ("R", QColor(100, 100, 200)),
    "Julia":   ("JL", QColor(160, 80, 160)),
    "Go":      ("GO", QColor(60, 160, 200)),
    "Shell":   ("SH", QColor(100, 100, 100)),
}


class NodeItem(QGraphicsRectItem):
    # métriques simples
    HEADER_H = 28
    ROW_H = 22
    PADDING_X = 12
    PADDING_Y = 8
    PIN_RADIUS = 8
    LABEL_GAP = 6

    # --- mapping familles (cohérent avec ConnectionItem) ---
    _PIN_FAMILIES = {
        "raw": {"raw", "data", "eeg", "x"},  # + "data" ajouté
        "segment": {"segment", "segments", "window", "trial", "epoch", "sample"},
        "sfreq": {"sfreq", "fs", "sampling_rate", "sample_rate", "sf"},
        "ch_names": {"ch_names", "channels", "chan_names", "labels", "names"},
        "features": {"features", "feature", "embedding", "vec", "x_vec"},
        "cov": {"cov", "covariance", "c"},
        "model": {"model", "clf", "classifier", "estimator"},
        "label": {"label", "labels", "y", "target", "class"},
        "status": {"status"},
        "feature_transform": {"feature_transform", "csp", "feat_transform"},
        "ts_transform": {"ts_transform", "tspace", "tangent"},
    }

    def __init__(self, plugin_class):
        super().__init__()

        self.plugin = plugin_class()
        self.input_pins = []
        self.output_pins = []
        self._title_item = None
        self._title_raw = ""
        self.proxy = None

        self._dragging = False
        self._old_viewport_mode = None

        # --- Langage du plugin ---
        self.lang = self._detect_language(self.plugin)

        # Dimensions du badge
        self._badge_font = QFont("Arial")
        self._badge_font.setPointSizeF(9.0 * BADGE_SCALE)
        self._badge_font.setBold(True)
        self._recompute_badge_size()

        # Style général
        self.setBrush(QBrush(QColor(50, 50, 70)))
        self.setPen(QPen(Qt.black))
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)

        # polices
        self._font_title = QFont("Arial", 10, QFont.Bold)
        self._font_io = QFont("Arial", 9)

        # construire
        display_name = self.plugin.__class__.name if hasattr(self.plugin.__class__, "name") else self.plugin.__class__.__name__
        self._draw_label(display_name)
        base_h = self._draw_pins_and_size()
        self._update_title_elision()
        self._center_title()
        self._add_custom_widget(base_h)

        print(f">>> Création du NodeItem pour : {plugin_class.__name__} (lang={self.lang})")

    # --------------------- helpers famille/hint ---------------------
    def _normalize(self, s: str) -> str:
        return (s or "").strip().lower()

    def _family_from_name(self, name: str) -> str:
        n = self._normalize(name)
        for fam, names in self._PIN_FAMILIES.items():
            if n == fam or n in names:
                return fam
        return n

    def _apply_family_hint(self, pin: PinItem):
        """Pose pin.family_hint depuis le plugin (PIN_FAMILY_HINTS) ou via le nom."""
        hints = getattr(self.plugin, "PIN_FAMILY_HINTS", {}) or {}
        pin_name = getattr(pin, "name", "") or getattr(pin, "pin_name", "")
        for k, fam in hints.items():
            if self._normalize(str(k)) == self._normalize(pin_name):
                pin.family_hint = self._normalize(str(fam))
                pin.setToolTip(f"{'output' if pin.is_output else 'input'}: {pin_name} • famille: {pin.family_hint}")
                return
        # fallback par nom
        pin.family_hint = self._family_from_name(pin_name)
        pin.setToolTip(f"{'output' if pin.is_output else 'input'}: {pin_name} • famille: {pin.family_hint}")

    # --------------------- Titre ---------------------
    def _draw_label(self, name: str):
        self._title_raw = name
        self._title_item = QGraphicsTextItem(name, self)
        self._title_item.setDefaultTextColor(Qt.white)
        self._title_item.setFont(self._font_title)

    def _update_title_elision(self):
        if not self._title_item:
            return
        fm = QFontMetricsF(self._title_item.font())
        avail = max(20.0, self.rect().width() - (self._badge_w + self._badge_margin + 2 * self.PADDING_X + 8.0))
        elided = fm.elidedText(self._title_raw, Qt.ElideRight, int(avail))
        self._title_item.setPlainText(elided)

    def _center_title(self):
        if not self._title_item:
            return
        fm = QFontMetricsF(self._title_item.font())
        text = self._title_item.toPlainText()
        text_w = fm.width(text) if hasattr(fm, "width") else fm.horizontalAdvance(text)
        text_h = fm.height()
        rect = self.rect()
        available_right = rect.right() - (self._badge_w + self._badge_margin + 4.0)
        x_center = rect.x() + (rect.width() - text_w) / 2.0
        x = max(rect.x() + self.PADDING_X, min(x_center, available_right - text_w))
        y = rect.y() + (self.HEADER_H - text_h) / 2.0
        self._title_item.setPos(x, y)

    # --------------- Pins + dimensionnement ----------
    def _draw_pins_and_size(self):
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

        title_w = fm_title.width(self._title_raw) + 2 * self.PADDING_X

        max_in_w = max((fm_io.width(str(n)) for n in getattr(self.plugin, "inputs", [])), default=0.0)
        max_out_w = max((fm_io.width(str(n)) for n in getattr(self.plugin, "outputs", [])), default=0.0)

        left_col_w = self.PADDING_X + self.PIN_RADIUS + self.LABEL_GAP + max_in_w + self.PADDING_X
        right_col_w = self.PADDING_X + max_out_w + self.LABEL_GAP + self.PIN_RADIUS + self.PADDING_X

        content_w = max(160.0, title_w, left_col_w + right_col_w)

        left_pin_x = self.PADDING_X + self.PIN_RADIUS
        right_pin_x = content_w - (self.PADDING_X + self.PIN_RADIUS)

        y_top = self.HEADER_H + self.PADDING_Y
        lines = max(len(getattr(self.plugin, "inputs", [])), len(getattr(self.plugin, "outputs", [])))

        # --- Inputs (gauche) ---
        for i, name in enumerate(getattr(self.plugin, "inputs", [])):
            cy = y_top + i * self.ROW_H + self.ROW_H / 2.0
            pin = PinItem(name=name, is_output=False, parent=self)
            pin.setPos(left_pin_x, cy)
            pin.node = self
            pin.pin_name = name
            self._apply_family_hint(pin)
            self.input_pins.append(pin)

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
            self._apply_family_hint(pin)
            self.output_pins.append(pin)

            text_w = fm_io.width(str(name))
            text = QGraphicsTextItem(str(name), self)
            text.setDefaultTextColor(Qt.red)
            text.setFont(self._font_io)
            text.setPos(right_pin_x - self.PIN_RADIUS - self.LABEL_GAP - text_w, cy - fm_io.height() / 2.0)

        base_h = self.HEADER_H + self.PADDING_Y + lines * self.ROW_H + self.PADDING_Y
        self.setRect(0, 0, content_w, max(base_h, self.HEADER_H + 2 * self.PADDING_Y))
        return base_h

    # ----------------- Widget en bas ------------------
    def _add_custom_widget(self, base_h: float):
        if not hasattr(self.plugin, "build_widget"):
            self._update_title_elision()
            self._center_title()
            return

        w = self.plugin.build_widget()
        if not isinstance(w, QWidget):
            self._update_title_elision()
            self._center_title()
            return

        if self.proxy is None:
            self.proxy = QGraphicsProxyWidget(self)
        self.proxy.setWidget(w)

        target_w = max(60, int(self.rect().width() - 2 * self.PADDING_X))
        hint = w.sizeHint()
        target_h = hint.height() if hint.isValid() else 80
        try:
            w.resize(target_w, target_h)
        except Exception:
            pass

        y = base_h + self.PADDING_Y
        self.proxy.setPos(self.PADDING_X, y)

        new_h = y + target_h + self.PADDING_Y
        self.setRect(0, 0, self.rect().width(), new_h)

        self._update_title_elision()
        self._center_title()

    # ----------------- Rafraîchissement pendant déplacement -----------------
    def _view(self):
        sc = self.scene()
        if sc:
            try:
                views = sc.views()
                if views:
                    return views[0]
            except Exception:
                pass
        return None

    def mousePressEvent(self, ev):
        self._dragging = True
        v = self._view()
        if v is not None:
            try:
                self._old_viewport_mode = v.viewportUpdateMode()
                v.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
            except Exception:
                pass
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        sc = self.scene()
        if sc is not None:
            try:
                sc.invalidate(sc.sceneRect())
            except Exception:
                pass
        v = self._view()
        if v is not None:
            try:
                v.viewport().repaint()
            except Exception:
                pass

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        self._dragging = False
        v = self._view()
        if v is not None and self._old_viewport_mode is not None:
            try:
                v.setViewportUpdateMode(self._old_viewport_mode)
            except Exception:
                pass
        sc = self.scene()
        if sc is not None:
            try:
                sc.invalidate(sc.sceneRect())
            except Exception:
                pass

    # --------------- API existante --------------------
    def _auto_resize(self):
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

    # ----------------- Badge langage ------------------
    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)

        label, color = self._badge_label_color()

        painter.save()
        painter.setFont(self._badge_font)

        fm = QFontMetricsF(self._badge_font)
        tw = fm.width(label) if hasattr(fm, "width") else fm.horizontalAdvance(label)
        th = fm.height()
        w = self._badge_w
        h = self._badge_h
        r = 7.0 * BADGE_SCALE

        x, y = self._badge_topright()
        path = QPainterPath()
        path.addRoundedRect(x, y, w, h, r, r)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

        painter.setPen(Qt.white)
        tx = x + (w - tw) / 2.0
        ty = y + (h + th * 0.35) / 2.0
        painter.drawText(QPointF(tx, ty), label)
        painter.restore()

    # ----------------- Helpers langage/badge ------------------
    def _badge_label_color(self):
        return LANG_BADGE.get(self.lang, (self.lang.upper()[:2], QColor(40, 120, 200)))

    def _recompute_badge_size(self):
        label, _ = self._badge_label_color()
        fm = QFontMetricsF(self._badge_font)
        tw = fm.width(label) if hasattr(fm, "width") else fm.horizontalAdvance(label)
        pad_x, pad_y = 6.0 * BADGE_SCALE, 3.0 * BADGE_SCALE
        self._badge_w = tw + 2 * pad_x
        self._badge_h = fm.height() + 2 * pad_y
        self._badge_margin = 6.0 * BADGE_SCALE

    def _badge_topright(self):
        rect = self.rect()
        x = rect.right() - self._badge_w - self._badge_margin
        y = rect.top() + self._badge_margin
        return x, y

    def _detect_language(self, plugin):
        lang = (getattr(plugin, "language", None)
                or getattr(plugin.__class__, "language", None)
                or getattr(plugin, "lang", None)
                or getattr(plugin.__class__, "lang", None))
        if isinstance(lang, str) and lang.strip():
            return self._canon_language(lang)

        cname = plugin.__class__.__name__.lower()
        mod   = getattr(plugin.__class__, "__module__", "").lower()
        hint  = " ".join([cname, mod, str(getattr(plugin, "__file__", "")), str(getattr(plugin, "exe_path", ""))])

        if any(k in hint for k in ["rust", "cargo", "target/release"]): return "Rust"
        if any(k in hint for k in ["node", "node.js", "javascript"]):   return "Node.js"
        if any(k in hint for k in ["cpp", "c++"]):                      return "C++"
        if "julia" in hint:                                             return "Julia"
        if "rscript" in hint or " r " in (" " + hint + " "):            return "R"
        if any(k in hint for k in ["bash", "shell", "sh "]):            return "Shell"
        return "Python"

    def _canon_language(self, s: str) -> str:
        s = (s or "").strip().lower()
        if s in ("py", "python"): return "Python"
        if s in ("rs", "rust"): return "Rust"
        if s in ("js", "node", "nodejs", "node.js", "javascript"): return "Node.js"
        if s in ("c++", "cpp"): return "C++"
        if s in ("jl", "julia"): return "Julia"
        if s in ("r", "r-lang", "rscript"): return "R"
        if s in ("sh", "bash", "shell"): return "Shell"
        if s in ("go", "golang"): return "Go"
        if s in ("c",): return "C"
        return s.capitalize()
