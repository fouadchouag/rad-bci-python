# core/ui_kit.py
from PyQt5.QtWidgets import QPushButton, QApplication, QStyle, QWidget
from PyQt5.QtCore import QSize, Qt

class UiKit:
    ROLES = {"default":"", "primary":"primary", "danger":"danger", "success":"success", "ghost":"ghost"}

    # Thème "outline" lisible (texte foncé), avec états hover/pressed/disabled/checked
    STYLESHEET = """
    QPushButton {
        background: #ffffff;
        border: 1px solid #d0d7de;
        border-radius: 8px;
        padding: 6px 12px;
        font-weight: 600;
        color: #111827;
    }
    QPushButton:hover   { background: #f6f8fb; border-color: #c2cbd6; }
    QPushButton:pressed { background: #eef2f7; }
    QPushButton:disabled{
        color: #9aa6b2; background: #f9fafb; border-color: #e5e9f0;
    }
    /* Etat actif pour les boutons checkables (ex: Pause) */
    QPushButton:checked { background: #eaeef5; border-color: #9db0cc; }

    /* Variantes */
    QPushButton#primary        { background: #eaf2ff; border-color: #9dc2ff; color: #0f3e9e; }
    QPushButton#primary:hover  { background: #e2ecff; border-color: #87b3ff; }
    QPushButton#primary:pressed{ background: #d8e5ff; }
    QPushButton#primary:checked{ background: #d7e6ff; border-color: #7db0ff; }

    QPushButton#danger         { background: #ffeeee; border-color: #ffc2c7; color: #8a1120; }
    QPushButton#danger:hover   { background: #ffe5e7; border-color: #ffaab1; }
    QPushButton#danger:pressed { background: #ffdadd; }
    QPushButton#danger:checked { background: #ffd3d7; border-color: #ff9aa3; }

    QPushButton#success        { background: #e9f9f0; border-color: #9fe0bf; color: #0f5e39; }
    QPushButton#success:hover  { background: #e2f6ec; border-color: #8fd9b5; }
    QPushButton#success:pressed{ background: #d9f2e6; }
    QPushButton#success:checked{ background: #d2f0e0; border-color: #87d2aa; }
    """

    @classmethod
    def apply_app_style(cls):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(app.styleSheet() + "\n" + cls.STYLESHEET)

    @classmethod
    def apply_node_style(cls, root: QWidget):
        root.setStyleSheet(root.styleSheet() + "\n" + cls.STYLESHEET)

    @staticmethod
    def make_btn(text: str, role: str = "default", icon_sp=None, checkable: bool=False) -> QPushButton:
        b = QPushButton(text)
        if icon_sp is not None:
            b.setIcon(QApplication.style().standardIcon(icon_sp))
            b.setIconSize(QSize(18, 18))
        name = UiKit.ROLES.get(role, "")
        if name:
            b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(28)
        b.setAutoDefault(False)
        b.setDefault(False)
        b.setCheckable(checkable)   # ← permet un vrai état visuel (Pause)
        b.setFlat(False)
        return b
