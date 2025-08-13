# utils/ui.py
# Section repliable "propre" qui n'occupe aucun espace quand fermée.

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QToolButton, QSizePolicy


class CollapsibleSection(QWidget):
    """
    En-tête (flèche ▶/▼ + titre) + contenu.
    - collapsed=True : repliée par défaut
    - .setExpanded(bool) pour ouvrir/fermer
    - .content_widget pour accéder au contenu
    """
    def __init__(self, title="Paramètres", content: QWidget = None,
                 collapsed: bool = True, parent=None):
        super().__init__(parent)

        self._btn = QToolButton(self)
        self._btn.setText(title)
        self._btn.setCheckable(True)
        self._btn.setAutoRaise(True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget(self)
        v = QVBoxLayout(self._wrap)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        self._content = content or QWidget(self._wrap)
        v.addWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed)
        self._on_toggled(self._btn.isChecked())

    @property
    def content_widget(self) -> QWidget:
        return self._content

    def setExpanded(self, expanded: bool):
        if self._btn.isChecked() != bool(expanded):
            self._btn.setChecked(bool(expanded))

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)

        if expanded:
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        else:
            header_h = self._btn.sizeHint().height() + 6
            self._wrap.setMaximumHeight(0)
            self._wrap.setMinimumHeight(0)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMaximumHeight(header_h)
            self.setMinimumHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self._poke_ancestors()

    def _poke_ancestors(self):
        w = self
        while w is not None:
            lay = w.layout()
            if lay:
                lay.invalidate()
            w.adjustSize()
            w.updateGeometry()
            w = w.parentWidget()
