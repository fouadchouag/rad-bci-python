# gui/node_item.py
from PyQt5.QtCore import Qt, QPointF, QTimer
from PyQt5.QtWidgets import (
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsSimpleTextItem, QGraphicsItem,
    QGraphicsEllipseItem, QDialog, QVBoxLayout, QLabel, QWidget,
    QScrollArea, QToolButton, QMainWindow
)
from PyQt5.QtGui import QBrush, QColor, QPen, QFontMetricsF, QFont, QPainterPath, QCursor

from .pin_item import PinItem

BADGE_SCALE = 0.85

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


class _HidingDialog(QDialog):
    def closeEvent(self, ev):
        try:
            self.hide()
            ev.ignore()
        except Exception:
            super().closeEvent(ev)


class _CircleIcon(QGraphicsEllipseItem):
    """Petit bouton circulaire cliquable – handler void (pas d’erreur SIP)."""
    def __init__(self, parent, text, *, r=9.0, bg=QColor(45, 120, 210), fg=Qt.white, tooltip="", on_click=None, tag=None):
        super().__init__(parent)
        self._r = float(r)
        self._on_click = on_click
        self.setRect(-r, -r, 2*r, 2*r)
        self.setBrush(QBrush(bg))
        self.setPen(QPen(QColor(25, 70, 150)))
        self.setZValue(1e6)
        self.setAcceptHoverEvents(True)
        self.setData(0, tag or "")  # 'icon:settings' / 'icon:help'
        if tooltip:
            self.setToolTip(tooltip)

        self._label = QGraphicsTextItem(text, self)
        f = QFont("Arial", 9, QFont.Bold)
        self._label.setFont(f)
        self._label.setDefaultTextColor(fg)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
        h = fm.height()
        self._label.setPos(-w/2.0, -h/2.0 - 1)

    def hoverEnterEvent(self, e):
        self.setCursor(QCursor(Qt.PointingHandCursor))
        super().hoverEnterEvent(e)

    def mousePressEvent(self, e):
        try:
            if callable(self._on_click):
                self._on_click()
        except Exception:
            pass
        super().mousePressEvent(e)


class NodeItem(QGraphicsRectItem):
    HEADER_H = 28
    ROW_H = 22
    PADDING_X = 12
    PADDING_Y = 8
    PIN_RADIUS = 8
    LABEL_GAP = 6

    def __init__(self, plugin_class):
        super().__init__()

        self.plugin = plugin_class()
        self.input_pins = []
        self.output_pins = []

        self._title_item = None
        self._title_raw = ""
        self._param_dialog = None
        self._param_widget = None

        self._btn_settings = None  # ⚙️ (officiel)
        self._btn_help = None      # ❓ (officiel)

        self.lang = self._detect_language(self.plugin)
        self._badge_font = QFont("Arial"); self._badge_font.setPointSizeF(9.0 * BADGE_SCALE); self._badge_font.setBold(True)
        self._recompute_badge_size()

        self.setBrush(QBrush(QColor(50, 50, 70)))
        self.setPen(QPen(Qt.black))
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        self._font_title = QFont("Arial", 10, QFont.Bold)
        self._font_io = QFont("Arial", 9)

        display_name = getattr(self.plugin.__class__, "name", self.plugin.__class__.__name__)
        self._draw_label(display_name)
        self._rebuild_geometry()

        # purge agressive dès l’init (contre anciens “?”)
        self._purge_stray_marks()

        self._create_header_icons()
        self._dedupe_icons()

        self._ensure_ui_initialized()

    # ---------------- purge/dédup ----------------
    def _iter_children_recursive(self, root):
        stack = list(root.childItems())
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.childItems())

    def _is_stray_mark(self, it) -> bool:
        # icône officielle ?
        if isinstance(it, _CircleIcon):
            tag = (it.data(0) or "")
            return tag not in ("icon:settings", "icon:help")
        # ellipse avec texte '?'/'⚙'
        if isinstance(it, QGraphicsEllipseItem):
            for sub in it.childItems():
                if isinstance(sub, (QGraphicsTextItem, QGraphicsSimpleTextItem)):
                    t = (sub.toPlainText() if hasattr(sub, "toPlainText") else sub.text()).strip()
                    if t in ("?", "⚙"):
                        return True
        # texte isolé '?'/'⚙'
        if isinstance(it, (QGraphicsTextItem, QGraphicsSimpleTextItem)):
            try:
                t = it.toPlainText()
            except Exception:
                try:
                    t = it.text()
                except Exception:
                    t = ""
            if (t or "").strip() in ("?", "⚙"):
                return True
        # toolTip “help/aide” et tout petit item (souvent anciens boutons dessinés)
        try:
            tip = (it.toolTip() or "").lower()
            if any(k in tip for k in ("help", "aide")):
                br = it.boundingRect()
                if br.width() <= 24 and br.height() <= 24:
                    tag = (it.data(0) or "")
                    if tag not in ("icon:settings", "icon:help"):
                        return True
        except Exception:
            pass
        return False

    def _purge_stray_marks(self):
        kill = []
        for it in self._iter_children_recursive(self):
            if it in (self._btn_settings, self._btn_help):
                continue
            if self._is_stray_mark(it):
                kill.append(it)
        for it in kill:
            try:
                if it.scene(): it.scene().removeItem(it)
            except Exception:
                try: it.setParentItem(None)
                except Exception: pass

    def _dedupe_icons(self):
        buckets = {"icon:settings": [], "icon:help": []}
        for it in self._iter_children_recursive(self):
            if isinstance(it, _CircleIcon):
                tag = (it.data(0) or "")
                if tag in buckets:
                    buckets[tag].append(it)
        for tag, lst in buckets.items():
            if len(lst) > 1:
                keep = lst[-1]
                for it in lst[:-1]:
                    if it is keep: continue
                    try:
                        if it.scene(): it.scene().removeItem(it)
                    except Exception:
                        try: it.setParentItem(None)
                        except Exception: pass

    # ---------------- icônes header ----------------
    def _create_header_icons(self):
        if self._btn_settings is None:
            self._btn_settings = _CircleIcon(
                self, "⚙", r=8.5, bg=QColor(70, 140, 230),
                tooltip="Paramètres", on_click=self.open_params_dialog, tag="icon:settings"
            )
        if self._btn_help is None:
            self._btn_help = _CircleIcon(
                self, "?", r=8.5, bg=QColor(120, 120, 120),
                tooltip="Aide", on_click=self.open_help_dialog, tag="icon:help"
            )
        self._position_header_buttons()

    def _position_header_buttons(self):
        if self._btn_settings:
            r = self._btn_settings._r
            self._btn_settings.setPos(self.PADDING_X + r, self.PADDING_Y + r)
        if self._btn_help:
            r = self._btn_help._r
            bx, _ = self._badge_topright()
            cx = bx - 6.0 - r
            cy = self.PADDING_Y + r
            rect = self.rect()
            cx = max(rect.left() + r + self.PADDING_X, min(cx, rect.right() - r - self.PADDING_X))
            cy = max(rect.top() + r + self.PADDING_Y, min(cy, rect.bottom() - r - self.PADDING_Y))
            self._btn_help.setPos(cx, cy)

    # ---------------- paramètres ----------------
    def _normalize_plugin_widget(self, w: QWidget) -> QWidget:
        if isinstance(w, QMainWindow):
            cw = w.centralWidget()
            if cw is not None:
                cw.setParent(None)
                try: w.close(); w.deleteLater()
                except Exception: pass
                return cw
            return QWidget()
        if isinstance(w, QDialog):
            tmp = QWidget()
            lay = QVBoxLayout(tmp)
            lay.addWidget(QLabel("Ce plugin retourne un QDialog; contenu non imbriqué."))
            try: w.close(); w.deleteLater()
            except Exception: pass
            return tmp
        return w

    def _expand_all_params(self, root: QWidget):
        for btn in root.findChildren(QToolButton):
            try:
                if btn.isCheckable() and btn.arrowType() in (Qt.RightArrow, Qt.DownArrow):
                    if not btn.isChecked():
                        btn.setChecked(True)
                        try: btn.toggled.emit(True)
                        except Exception: pass
            except Exception:
                pass

    def _ensure_ui_initialized(self):
        if self._param_widget is not None:
            return
        if hasattr(self.plugin, "build_widget"):
            try:
                try:
                    w = self.plugin.build_widget(self)
                except TypeError:
                    w = self.plugin.build_widget()
            except Exception:
                w = None
            if isinstance(w, QWidget):
                w = self._normalize_plugin_widget(w)
                self._expand_all_params(w)
                w.hide(); w.setParent(None)
                self._param_widget = w

    # ---------------- géométrie ----------------
    def _draw_label(self, name: str):
        self._title_raw = name
        self._title_item = QGraphicsTextItem(name, self)
        self._title_item.setDefaultTextColor(Qt.white)
        self._title_item.setFont(self._font_title)

    def _rebuild_geometry(self):
        for it in list(self.childItems()):
            if isinstance(it, PinItem):
                it.setParentItem(None)
        self.input_pins.clear(); self.output_pins.clear()

        fm_title = QFontMetricsF(self._font_title)
        fm_io = QFontMetricsF(self._font_io)

        title_w = (fm_title.horizontalAdvance(self._title_raw) if hasattr(fm_title, "horizontalAdvance")
                   else fm_title.width(self._title_raw)) + 2 * self.PADDING_X

        max_in_w  = max((fm_io.horizontalAdvance(str(n)) if hasattr(fm_io, "horizontalAdvance") else fm_io.width(str(n))
                        for n in getattr(self.plugin, "inputs", [])), default=0.0)
        max_out_w = max((fm_io.horizontalAdvance(str(n)) if hasattr(fm_io, "horizontalAdvance") else fm_io.width(str(n))
                        for n in getattr(self.plugin, "outputs", [])), default=0.0)

        left_col_w  = self.PADDING_X + self.PIN_RADIUS + self.LABEL_GAP + max_in_w  + self.PADDING_X
        right_col_w = self.PADDING_X + max_out_w + self.LABEL_GAP + self.PIN_RADIUS + self.PADDING_X
        content_w = max(220.0, title_w, left_col_w + right_col_w)

        left_pin_x  = self.PADDING_X + self.PIN_RADIUS
        right_pin_x = content_w - (self.PADDING_X + self.PIN_RADIUS)

        y_top = self.HEADER_H + self.PADDING_Y
        lines = max(len(getattr(self.plugin, "inputs", [])), len(getattr(self.plugin, "outputs", [])))

        for i, name in enumerate(getattr(self.plugin, "inputs", [])):
            cy = y_top + i * self.ROW_H + self.ROW_H / 2.0
            pin = PinItem(name=name, is_output=False, parent=self)
            pin.setPos(left_pin_x, cy); pin.node = self; pin.pin_name = name
            self.input_pins.append(pin)
            txt = QGraphicsTextItem(str(name), self)
            txt.setDefaultTextColor(Qt.green); txt.setFont(self._font_io)
            txt.setPos(left_pin_x + self.PIN_RADIUS + self.LABEL_GAP, cy - QFontMetricsF(self._font_io).height() / 2.0)

        for i, name in enumerate(getattr(self.plugin, "outputs", [])):
            cy = y_top + i * self.ROW_H + self.ROW_H / 2.0
            pin = PinItem(name=name, is_output=True, parent=self)
            pin.setPos(right_pin_x, cy); pin.node = self; pin.pin_name = name
            self.output_pins.append(pin)
            tw = (fm_io.horizontalAdvance(str(name)) if hasattr(fm_io, "horizontalAdvance") else fm_io.width(str(name)))
            txt = QGraphicsTextItem(str(name), self)
            txt.setDefaultTextColor(Qt.red); txt.setFont(self._font_io)
            txt.setPos(right_pin_x - self.PIN_RADIUS - self.LABEL_GAP - tw, cy - QFontMetricsF(self._font_io).height() / 2.0)

        base_h = self.HEADER_H + self.PADDING_Y + lines * self.ROW_H + self.PADDING_Y
        self.setRect(0, 0, content_w, max(base_h, self.HEADER_H + 2 * self.PADDING_Y))

        self._update_title_elision()
        self._center_title()
        self._position_header_buttons()

    def _update_title_elision(self):
        if not self._title_item: return
        fm = QFontMetricsF(self._title_item.font())
        avail = max(20.0, self.rect().width() - (self._badge_w + self._badge_margin + 2 * self.PADDING_X + 8.0))
        self._title_item.setPlainText(fm.elidedText(self._title_raw, Qt.ElideRight, int(avail)))

    def _center_title(self):
        if not self._title_item: return
        fm = QFontMetricsF(self._title_item.font())
        text = self._title_item.toPlainText()
        text_w = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
        text_h = fm.height(); rect = self.rect()
        available_right = rect.right() - (self._badge_w + self._badge_margin + 4.0)
        x_center = rect.x() + (rect.width() - text_w) / 2.0
        x = max(rect.x() + self.PADDING_X, min(x_center, available_right - text_w))
        y = rect.y() + (self.HEADER_H - text_h) / 2.0
        self._title_item.setPos(x, y)

    # ---------------- badge + repaint safe ----------------
    def paint(self, painter, option, widget=None):
        # (ré)position + purge à chaque repaint pour être 100% sûr
        self._position_header_buttons()
        self._purge_stray_marks()
        self._dedupe_icons()

        super().paint(painter, option, widget)

        label, color = self._badge_label_color()
        painter.save()
        painter.setFont(self._badge_font)
        fm = QFontMetricsF(self._badge_font)
        tw = fm.horizontalAdvance(label) if hasattr(fm, "horizontalAdvance") else fm.width(label)
        th = fm.height()
        w = self._badge_w; h = self._badge_h; r = 7.0 * BADGE_SCALE
        x, y = self._badge_topright()
        path = QPainterPath(); path.addRoundedRect(x, y, w, h, r, r)
        painter.setPen(Qt.NoPen); painter.setBrush(color); painter.drawPath(path)
        painter.setPen(Qt.white)
        tx = x + (w - tw) / 2.0; ty = y + (h + th * 0.35) / 2.0
        painter.drawText(QPointF(tx, ty), label)
        painter.restore()

    def _badge_label_color(self):
        return LANG_BADGE.get(self.lang, (self.lang.upper()[:2], QColor(40, 120, 200)))

    def _recompute_badge_size(self):
        label, _ = self._badge_label_color()
        fm = QFontMetricsF(self._badge_font)
        tw = fm.horizontalAdvance(label) if hasattr(fm, "horizontalAdvance") else fm.width(label)
        pad_x, pad_y = 6.0 * BADGE_SCALE, 3.0 * BADGE_SCALE
        self._badge_w = tw + 2 * pad_x
        self._badge_h = fm.height() + 2 * pad_y
        self._badge_margin = 6.0 * BADGE_SCALE

    def _badge_topright(self):
        rect = self.rect()
        return rect.right() - self._badge_w - self._badge_margin, rect.top() + self._badge_margin

    # ---------------- interactions ----------------
    def mouseDoubleClickEvent(self, event):
        self.open_params_dialog()
        super().mouseDoubleClickEvent(event)

    def _remax_main_window_if_needed(self, parent_window):
        try:
            if parent_window and parent_window.isMaximized():
                QTimer.singleShot(0, parent_window.showMaximized)
        except Exception:
            pass

    def open_params_dialog(self):
        parent = None
        try:
            views = self.scene().views()
            if views:
                parent = views[0].window()
        except Exception:
            parent = None

        self._ensure_ui_initialized()
        if isinstance(self._param_widget, QWidget):
            self._expand_all_params(self._param_widget)

        if self._param_dialog is not None:
            try:
                self._param_dialog.show(); self._param_dialog.raise_(); self._param_dialog.activateWindow()
                self._remax_main_window_if_needed(parent)
                return
            except Exception:
                self._param_dialog = None

        dlg = _HidingDialog(parent)
        dlg.setWindowTitle(f"{self.plugin.name} — Paramètres")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setMinimumSize(560, 380)

        lay = QVBoxLayout(dlg)
        if isinstance(self._param_widget, QWidget):
            if self._param_widget.parent() is not None: self._param_widget.setParent(None)
            area = QScrollArea(); area.setWidgetResizable(True); area.setWidget(self._param_widget)
            lay.addWidget(area, 1)
        else:
            lay.addWidget(QLabel("Ce nœud n’expose pas d’interface de paramètres."))

        self._param_dialog = dlg
        dlg.show()
        self._remax_main_window_if_needed(parent)

    def open_help_dialog(self):
        text = ""
        try:
            h = getattr(self.plugin, "help", None)
            if isinstance(h, dict): text = "\n".join([f"• {k}: {v}" for k, v in h.items()])
            elif isinstance(h, str): text = h
        except Exception:
            pass
        if not text:
            text = (self.plugin.__class__.__doc__ or "").strip() or "Aucune aide disponible."

        parent = None
        try:
            views = self.scene().views()
            if views:
                parent = views[0].window()
        except Exception:
            parent = None

        dlg = QDialog(parent)
        dlg.setWindowTitle(f"{self.plugin.name} — Aide")
        lay = QVBoxLayout(dlg)
        area = QScrollArea(); area.setWidgetResizable(True)
        w = QWidget(); v = QVBoxLayout(w); lbl = QLabel(text); lbl.setWordWrap(True)
        v.addWidget(lbl); v.addStretch(1); area.setWidget(w); lay.addWidget(area)
        dlg.resize(480, 360); dlg.show()
        self._remax_main_window_if_needed(parent)

    # ---------------- API util ----------------
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

    def get_input_pin_names(self): return [p.name for p in self.input_pins]
    def get_output_pin_names(self): return [p.name for p in self.output_pins]

    # ---------------- langue ----------------
    def _detect_language(self, plugin):
        lang = (getattr(plugin, "language", None)
                or getattr(plugin.__class__, "language", None)
                or getattr(plugin, "lang", None)
                or getattr(plugin.__class__, "lang", None))
        if isinstance(lang, str) and lang.strip(): return self._canon_language(lang)
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
