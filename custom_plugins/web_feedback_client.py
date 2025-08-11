# plugins/web_feedback_client.py
# Client HTTP simple : POST /feedback (JSON)
# Dépendance : pip install requests

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel, QHBoxLayout
from PyQt5.QtCore import Qt
import time

try:
    import requests
except Exception:
    requests = None


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
        w = QWidget(); v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_edit = QLineEdit("8000")
        row.addWidget(QLabel("Host:")); row.addWidget(self.host_edit)
        row.addWidget(QLabel("Port:")); row.addWidget(self.port_edit)
        v.addLayout(row)

        self.btn_test = QPushButton("Test")
        self.lbl_status = QLabel("status: —"); self.lbl_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.btn_test); v.addWidget(self.lbl_status)

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
        try: self._ui["host"].setText(host); self._ui["port"].setText(str(port))
        except Exception: pass

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
