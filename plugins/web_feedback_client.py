# plugins/web_feedback_client.py
# Client HTTP simple : POST /feedback (JSON)
# Dépendance : pip install requests

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, QHBoxLayout, QToolButton, QLayout, QSizePolicy
from PyQt5.QtCore import Qt
import time

try:
    import requests
except Exception:
    requests = None


class _CollapsibleSection(QWidget):
    """Section repliable qui retire vraiment la hauteur quand fermée."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()
        from PyQt5.QtWidgets import QVBoxLayout as _V
        self._wrap_l = _V(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0)
        self._wrap_l.setSpacing(0)
        self._content = content or QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._wrap_l.addWidget(self._content)

        root = _V(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed)
        self._on_toggled(self._btn.isChecked())

    def _poke_ancestors(self):
        w = self
        while w is not None:
            if w.layout():
                w.layout().invalidate()
            w.adjustSize()
            w.updateGeometry()
            w = w.parentWidget()

    def _on_toggled(self, expanded: bool):
        self._btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._wrap.setVisible(expanded)
        if expanded:
            self.setMaximumHeight(16777215)
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self._wrap.setMaximumHeight(16777215)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        else:
            header_h = self._btn.sizeHint().height() + 6
            self._wrap.setMaximumHeight(0)
            self._wrap.setMinimumHeight(0)
            self._wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMaximumHeight(header_h)
            self.setMinimumHeight(header_h)
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._poke_ancestors()


class WebFeedbackClient(BasePlugin):
    """
    Entrées:
      - host:str (def 127.0.0.1)
      - port:int (def 8000)
      - label:str
      - confidence:float (opt)
      - payload:dict (opt)
    Sorties:
      - status:str

    execute(...) retourne TOUJOURS {"status": ...} (pas d'autres clés !)
    """
    name = "WebFeedbackClient"
    language = "Python"
    category = "Web Nodes"

    def setup(self):
        self.inputs["host"] = BehaviorSubject("127.0.0.1")
        self.inputs["port"] = BehaviorSubject(8000)
        self.inputs["label"] = BehaviorSubject(None)
        self.inputs["confidence"] = BehaviorSubject(None)
        self.inputs["payload"] = BehaviorSubject(None)

        self.outputs["status"] = BehaviorSubject(None)
        self._ui = {}

    def build_widget(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # panneau repliable
        panel = QWidget()
        v = QVBoxLayout(panel); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        row = QHBoxLayout()
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_edit = QLineEdit("8000")
        row.addWidget(QLabel("Host:")); row.addWidget(self.host_edit)
        row.addWidget(QLabel("Port:")); row.addWidget(self.port_edit)
        v.addLayout(row)

        self.btn_test = QPushButton("Test")
        self.lbl_status = QLabel("status: —"); self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.btn_test)
        v.addWidget(self.lbl_status)

        sec = _CollapsibleSection("Paramètres & Statut", panel, collapsed=True)
        root.addWidget(sec)

        self.btn_test.clicked.connect(self._on_test)
        self._ui = dict(host=self.host_edit, port=self.port_edit, status=self.lbl_status)
        return w

    def _on_test(self):
        host = (self.host_edit.text().strip() or "127.0.0.1")
        try: port = int(self.port_edit.text().strip() or "8000")
        except Exception: port = 8000
        self.set_input("host", host)
        self.set_input("port", port)
        self.set_input("label", "TEST")

    def execute(self, *args, **kwargs):
        # Normalisation robuste
        inp = {}
        if args and isinstance(args[0], dict): inp.update(args[0])
        if kwargs: inp.update(kwargs)

        host = (inp.get("host", self._values.get("host")) or "127.0.0.1").strip()
        try: port = int(inp.get("port", self._values.get("port")) or 8000)
        except Exception: port = 8000
        label = inp.get("label", self._values.get("label"))
        confidence = inp.get("confidence", self._values.get("confidence"))
        payload = inp.get("payload", self._values.get("payload"))

        # sync UI
        try:
            self._ui["host"].setText(host)
            self._ui["port"].setText(str(port))
        except Exception:
            pass

        status = "missing_fields"
        if label is None or not host or not port:
            pass
        elif requests is None:
            status = "error: requests missing"
        else:
            url = f"http://{host}:{port}/feedback"
            # message
            if isinstance(payload, dict):
                msg = dict(payload)
                msg.setdefault("label", str(label))
                msg.setdefault("ts", time.time())
                if confidence is not None:
                    try: msg.setdefault("confidence", float(confidence))
                    except Exception: pass
            else:
                msg = {"label": str(label), "ts": time.time()}
                if confidence is not None:
                    try: msg["confidence"] = float(confidence)
                    except Exception: pass
            # envoi
            try:
                r = requests.post(url, json=msg, timeout=2.0)
                status = "sent" if r.ok else f"error: HTTP {r.status_code}"
            except Exception as e:
                status = f"error: {e}"

        self._emit("status", status)
        try: self._ui["status"].setText(f"status: {status}")
        except Exception: pass

        # >>> TOUJOURS un dict avec UNIQUEMENT les sorties déclarées
        return {"status": status}

    def _emit(self, name, value):
        if name in self.outputs:
            self.outputs[name].on_next(value)
