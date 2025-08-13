# utils/collapsible.py
from PyQt5.QtWidgets import QWidget, QToolButton, QFrame, QVBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt

class CollapsibleSection(QWidget):
    """
    Section repliable simple :
      - header bouton "Paramètres" (checkable) avec flèche
      - contenu (QWidget) masqué/affiché
      - état initial configurable
    """
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._content = content or QFrame()
        self._content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._btn = QToolButton(text=title, checkable=True, checked=not collapsed)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._btn.setArrowType(Qt.DownArrow if not collapsed else Qt.RightArrow)
        self._btn.toggled.connect(self._on_toggled)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._btn)
        lay.addWidget(self._content)

        self._content.setVisible(not collapsed)

    def setContent(self, w: QWidget):
        if self._content is not None:
            self.layout().removeWidget(self._content)
            self._content.deleteLater()
        self._content = w
        self.layout().addWidget(self._content)
        self._content.setVisible(self._btn.isChecked())

    def content(self) -> QWidget:
        return self._content

    def _on_toggled(self, checked: bool):
        self._btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        if self._content:
            self._content.setVisible(checked)
