
# rbciad_app/integrate_help.py
from __future__ import annotations
from PyQt5.QtWidgets import QAction, QMessageBox, QMenu, QShortcut
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import QObject, QEvent, Qt

from rbciad_app.help_utils import open_help, open_node_help_in_docs
from rbciad_app.node_quick_help import NodeHelpDialog
try:
    from rbciad_app.badge import install_node_badges
except Exception:
    install_node_badges = None
try:
    from rbciad_app.help_editor import mount_help_editor_dock
except Exception:
    mount_help_editor_dock = None

def setup_help(main_window, scene=None):
    if getattr(main_window, "_rbciad_help_installed", False):
        return
    setattr(main_window, "_rbciad_help_installed", True)

    # ---- Menus -----------------------------------------------------------------
    if callable(getattr(main_window, "menuBar", None)):
        help_menu = main_window.menuBar().addMenu("&Help")

        act_help = QAction("Help (User/Developer)", main_window)
        act_help.triggered.connect(lambda: open_help())
        help_menu.addAction(act_help)

        act_ctx = QAction("Context Help (Selected Node)", main_window)
        act_ctx.triggered.connect(lambda: _open_context_help(main_window))
        help_menu.addAction(act_ctx)

        act_qh = QAction("Quick Help (Selected Node)", main_window)
        act_qh.triggered.connect(lambda: _open_quick_help(main_window))
        help_menu.addAction(act_qh)

        # Tools menu for the Help Editor
        tools_menu = main_window.menuBar().addMenu("&Tools")
        if mount_help_editor_dock:
            act_editor = QAction("Help Editor", main_window)
            act_editor.triggered.connect(lambda: mount_help_editor_dock(main_window))
            tools_menu.addAction(act_editor)

    # ---- Shortcuts --------------------------------------------------------------
    s1 = QShortcut(QKeySequence(Qt.Key_F1), main_window)
    s1.setContext(Qt.ApplicationShortcut)
    s1.activated.connect(lambda: open_help())

    s2 = QShortcut(QKeySequence("Shift+F1"), main_window)
    s2.setContext(Qt.ApplicationShortcut)
    s2.activated.connect(lambda: _open_context_help(main_window))

    s3 = QShortcut(QKeySequence("Ctrl+F1"), main_window)
    s3.setContext(Qt.ApplicationShortcut)
    s3.activated.connect(lambda: _open_quick_help(main_window))

    setattr(main_window, "_rbciad_shortcuts", (s1, s2, s3))

    # ---- '?' badges on nodes (if available) ------------------------------------
    if scene is not None and install_node_badges:
        try:
            install_node_badges(scene, main_window)
        except Exception as e:
            print("[rbciad_app] Badge installation failed:", e)

def _get_selected_node(main_window):
    scene = getattr(main_window, "scene", None)
    if scene and hasattr(scene, "selectedItems"):
        items = scene.selectedItems()
        for it in items:
            if hasattr(it, "plugin"):
                return it
    return None

def _open_context_help(main_window):
    node = _get_selected_node(main_window)
    if node and hasattr(node, "plugin"):
        dn = getattr(node.plugin, "display_name", None)
        if dn:
            open_node_help_in_docs(dn)
            return
    open_help("user/nodes")

def _open_quick_help(main_window):
    node = _get_selected_node(main_window)
    if node and hasattr(node, "plugin"):
        dlg = NodeHelpDialog(node.plugin, parent=main_window)
        dlg.exec_()
    else:
        QMessageBox.information(main_window, "Quick Help", "Select a node first.")
