# gui/node_config_dialog.py
# -*- coding: utf-8 -*-
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea, QWidget
from PyQt5.QtCore import Qt

class NodeConfigDialog(QDialog):
    """
    Fenêtre générique qui embarque le widget de configuration du plugin (build_widget()).
    On le crée à la demande (lazy) et on le réutilise.
    """
    def __init__(self, plugin, parent=None, title=None):
        super().__init__(parent)
        self.setWindowTitle(title or f"Réglages — {getattr(plugin, 'name', type(plugin).__name__)}")
        self.setModal(False)  # non-bloquant
        self._plugin = plugin
        self._inner = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        holder = QWidget()
        self._holder_layout = QVBoxLayout(holder)
        self._holder_layout.setContentsMargins(0, 0, 0, 0)
        self._holder_layout.setSpacing(0)
        sc.setWidget(holder)
        root.addWidget(sc, 1)

        bar = QHBoxLayout()
        bar.addStretch(1)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.close)
        bar.addWidget(btn_close)
        root.addLayout(bar)

        self._ensure_inner()

        self.resize(720, 520)
        self.setAttribute(Qt.WA_DeleteOnClose, False)  # on réutilise la même fenêtre

    def _ensure_inner(self):
        if self._inner is not None:
            return
        try:
            # Les plugins RBciAD exposent build_widget()
            self._inner = self._plugin.build_widget()
        except Exception:
            self._inner = QWidget()
        self._holder_layout.addWidget(self._inner)
