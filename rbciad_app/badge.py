
# rbciad_app/badge.py
from __future__ import annotations
from PyQt5.QtWidgets import QGraphicsEllipseItem, QGraphicsSimpleTextItem, QGraphicsItem, QWidget
from PyQt5.QtGui import QBrush, QColor, QPen
from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF

from rbciad_app.node_quick_help import NodeHelpDialog

BADGE_KEY = "_rbciad_help_badge"
BADGE_W = 18.0
BADGE_H = 18.0
MARGIN = 4.0
STACK_STEP = 18.0  # vertical stacking step if corners are busy

def _resolve_parent_window(scene, main_window):
    """Return a QWidget suitable as dialog parent."""
    if isinstance(main_window, QWidget):
        return main_window
    # main_window might be a bound method (e.g., .window); call it if so
    try:
        if callable(main_window):
            w = main_window()
            if isinstance(w, QWidget):
                return w
    except Exception:
        pass
    # Try first view's window
    try:
        views = scene.views()
        if views:
            return views[0].window()
    except Exception:
        pass
    return None

class HelpBadgeItem(QGraphicsEllipseItem):
    def __init__(self, parent_item: QGraphicsItem, plugin_obj, scene, main_window):
        super().__init__(0, 0, BADGE_W, BADGE_H, parent_item)
        self.setZValue(10_000)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setAcceptHoverEvents(True)

        self.setBrush(QBrush(QColor("#2563eb")))  # blue-600
        self.setPen(QPen(Qt.NoPen))
        self.setToolTip("Quick Help (Ctrl+F1)")

        t = QGraphicsSimpleTextItem("?", self)
        t.setBrush(QBrush(QColor("white")))
        t.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        t.setPos(BADGE_W*0.35, BADGE_H*0.05)

        self._plugin = plugin_obj
        self._scene = scene
        self._mw = _resolve_parent_window(scene, main_window)

    def mousePressEvent(self, event):
        dlg = NodeHelpDialog(self._plugin, parent=self._mw)
        dlg.exec_()
        event.accept()

def _candidate_positions(item: QGraphicsItem):
    """Prefer TOP-LEFT first (reserve TOP-RIGHT for language badge)."""
    br: QRectF = item.boundingRect()
    pts = [
        QPointF(br.left() + MARGIN, br.top() + MARGIN),                           # TL (preferred)
        QPointF(br.left() + MARGIN, br.bottom() - BADGE_H - MARGIN),              # BL
        QPointF(br.right() - BADGE_W - MARGIN, br.bottom() - BADGE_H - MARGIN),   # BR
        QPointF(br.right() - BADGE_W - MARGIN, br.top() + MARGIN),                # TR (last)
    ]
    return pts

def _rect_at(pos: QPointF) -> QRectF:
    return QRectF(pos.x(), pos.y(), BADGE_W, BADGE_H)

def _intersects_siblings(item: QGraphicsItem, r_local: QRectF, exclude: QGraphicsItem = None) -> bool:
    """Check if r_local (in parent coords of item) collides with any small overlay child."""
    for ch in item.childItems():
        if ch is exclude:
            continue
        sbr = ch.mapRectToParent(ch.boundingRect())
        if sbr.width() <= 64 and sbr.height() <= 24:
            if sbr.intersects(r_local):
                return True
    return False

def _position_badge(item: QGraphicsItem, badge: HelpBadgeItem):
    br = item.boundingRect()
    # Try preferred corners in order
    for p in _candidate_positions(item):
        r = _rect_at(p)
        if not _intersects_siblings(item, r, exclude=badge):
            badge.setPos(p)
            return
    # If all busy, stack below top-left
    p0 = QPointF(br.left() + MARGIN, br.top() + MARGIN)
    for k in range(1, 6):
        p = QPointF(p0.x(), p0.y() + k * STACK_STEP)
        r = _rect_at(p)
        if not _intersects_siblings(item, r, exclude=badge):
            badge.setPos(p)
            return
    # Fallback
    badge.setPos(p0)

def _ensure_for_item(item: QGraphicsItem, scene, main_window):
    if not hasattr(item, "plugin"):
        return
    b = getattr(item, BADGE_KEY, None)
    if b is None:
        b = HelpBadgeItem(item, item.plugin, scene, main_window)
        setattr(item, BADGE_KEY, b)
    _position_badge(item, b)

def install_node_badges(scene, main_window):
    """Attach '?' badges to node items (those that expose .plugin)."""
    # Resolve and cache a good parent window
    parent_win = _resolve_parent_window(scene, main_window)
    setattr(scene, "_rbciad_parent_window", parent_win)

    # Initial pass
    for it in scene.items():
        _ensure_for_item(it, scene, parent_win)

    # Reposition on scene changes
    try:
        scene.changed.connect(lambda *_: _reposition_all(scene))
    except Exception as e:
        print("[rbciad_app] scene.changed hook failed:", e)

    # Periodic reposition
    timer = QTimer(scene)
    timer.setInterval(400)
    timer.timeout.connect(lambda: _reposition_all(scene))
    timer.start()
    setattr(scene, "_rbciad_badge_timer", timer)

def _reposition_all(scene):
    parent_win = getattr(scene, "_rbciad_parent_window", None) or _resolve_parent_window(scene, None)
    for it in scene.items():
        b = getattr(it, BADGE_KEY, None)
        if b is not None:
            _position_badge(it, b)
        else:
            _ensure_for_item(it, scene, parent_win)
