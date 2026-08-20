# plugins/server_http_launcher_plugin.py
# Serveur HTTP simple : sert un dossier statique + POST /feedback, GET /last
import os, json, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial
from typing import Optional

from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLineEdit, QPushButton,
                             QLabel, QHBoxLayout, QFileDialog, QToolButton, QLayout, QSizePolicy)
from PyQt5.QtCore import Qt


class _FeedbackHandler(SimpleHTTPRequestHandler):
    server_version = "RAD-HTTP/1.0"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.rstrip("/") == "/last":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self._cors(); self.end_headers()
            try:
                plugin = getattr(self.server, "plugin", None)
                payload = getattr(plugin, "_last_feedback", None) if plugin else None
            except Exception:
                payload = None
            self.wfile.write(json.dumps(payload or {}).encode("utf-8"))
        else:
            return super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/feedback":
            self.send_response(404); self._cors(); self.end_headers(); return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            data = {"_error": "invalid_json"}

        try:
            plugin = getattr(self.server, "plugin", None)
            if plugin is not None:
                plugin._on_feedback(data)
        except Exception:
            pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors(); self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "received": data}).encode("utf-8"))


class _CollapsibleSection(QWidget):
    """Section repliable qui retire vraiment la hauteur quand fermée."""
    def __init__(self, title="Paramètres", content: QWidget = None, collapsed=True, parent=None):
        super().__init__(parent)
        self._btn = QToolButton(text=title, checkable=True, autoRaise=True)
        self._btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        self._wrap = QWidget()
        self._wrap_l = QVBoxLayout(self._wrap)
        self._wrap_l.setContentsMargins(0, 0, 0, 0)
        self._wrap_l.setSpacing(0)
        self._content = content or QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._wrap_l.addWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.addWidget(self._btn)
        root.addWidget(self._wrap)

        self._btn.toggled.connect(self._on_toggled)
        self._btn.setChecked(not collapsed if isinstance(collapsed, bool) else True)  # backward-safe
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


class ServerHttpLauncherPlugin(BasePlugin):
    help = {
        'summary': 'Embedded HTTP server that serves a static directory and receives POST /feedback from a web client.',
        'inputs': {
            'host': 'str — bind address (default "127.0.0.1")',
            'port': 'int — port number (default 8000)',
            'workdir': 'str — directory to serve as static files (must contain index.html)',
            'start': 'bool — True to start the server, False to stop it',
        },
        'outputs': {
            'http_url': 'str or None — full URL of the running server (e.g. "http://127.0.0.1:8000/")',
            'is_running': 'bool — True while the server thread is alive',
            'log': 'str — last log/status message',
            'last_feedback': 'dict or None — most recently received POST /feedback JSON payload',
        },
        'parameters': [
            {'name': 'host', 'type': 'str', 'default': '127.0.0.1', 'desc': 'Bind address for the HTTP server.'},
            {'name': 'port', 'type': 'int', 'default': 8000, 'desc': 'Port number for the HTTP server.'},
            {'name': 'workdir', 'type': 'str', 'default': '(cwd)', 'desc': 'Directory to serve. Must contain index.html for the web UI.'},
            {'name': 'start', 'type': 'bool', 'default': False, 'desc': 'Set to True to start, False to stop.'},
        ],
        'gotchas': [
            'The server runs in a daemon thread — it stops automatically when the process exits.',
            'Do NOT select a node_modules directory as the served folder.',
            'GET /last returns the most recent feedback dict as JSON.',
            'POST /feedback accepts a JSON body; the server replies with {"status":"ok","received":...}.',
            'CORS is enabled (Access-Control-Allow-Origin: *) for cross-origin web clients.',
            'If the port is already in use, binding will fail and an error is logged.',
            'The server object is removed cleanly when the node is deleted (on_remove).',
        ],
        'usage': 'Set the directory containing your web app (index.html), then set start=True or click "Démarrer". Web clients can POST feedback to /feedback and read it back via GET /last.',
    }
    """
    UI: Host, Port, Dossier, Démarrer/Arrêter, Log (repliables)
    Sorties:
      - http_url: str | None
      - is_running: bool
      - log: str
      - last_feedback: dict | None

    IMPORTANT: execute() retourne TOUJOURS un dict avec ces 4 clés.
    """
    name = "ServerHttpLauncher"
    language = "Python"
    category = "Web Nodes"

    def setup(self):
        self.inputs["host"] = BehaviorSubject("127.0.0.1")
        self.inputs["port"] = BehaviorSubject(8000)
        self.inputs["workdir"] = BehaviorSubject(os.getcwd())
        self.inputs["start"] = BehaviorSubject(False)

        self.outputs["http_url"] = BehaviorSubject(None)
        self.outputs["is_running"] = BehaviorSubject(False)
        self.outputs["log"] = BehaviorSubject("")
        self.outputs["last_feedback"] = BehaviorSubject(None)

        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_feedback = None
        self._last_log = ""

        self._ui = {}

    def build_widget(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        # Panel repliable
        panel = QWidget()
        v = QVBoxLayout(panel); v.setContentsMargins(8, 8, 8, 8); v.setSpacing(6)

        form = QFormLayout()
        self.host_edit = QLineEdit("127.0.0.1")
        self.port_edit = QLineEdit("8000")
        self.dir_edit  = QLineEdit(os.getcwd())
        self.btn_dir   = QPushButton("Parcourir…")
        dir_row = QHBoxLayout(); dir_row.addWidget(self.dir_edit, 1); dir_row.addWidget(self.btn_dir, 0)
        form.addRow("Host", self.host_edit)
        form.addRow("Port", self.port_edit)
        form.addRow("Dossier", dir_row)
        v.addLayout(form)

        row = QHBoxLayout()
        self.btn_start = QPushButton("Démarrer")
        self.btn_stop  = QPushButton("Arrêter")
        row.addWidget(self.btn_start); row.addWidget(self.btn_stop)
        v.addLayout(row)

        self.lbl_url = QLabel("http://127.0.0.1:8000/"); self.lbl_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_log = QLabel("—"); self.lbl_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.lbl_url); v.addWidget(self.lbl_log)

        sec = _CollapsibleSection("Paramètres & Statut", panel, collapsed=True)
        root.addWidget(sec)

        self.btn_dir.clicked.connect(self._on_browse)
        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        self._ui = dict(host=self.host_edit, port=self.port_edit, dir=self.dir_edit,
                        url=self.lbl_url, log=self.lbl_log, start=self.btn_start, stop=self.btn_stop)
        return w

    def _on_browse(self):
        dlg = QFileDialog(); dlg.setFileMode(QFileDialog.Directory); dlg.setOption(QFileDialog.ShowDirsOnly, True)
        if dlg.exec_():
            paths = dlg.selectedFiles()
            if paths: self.dir_edit.setText(paths[0])

    def _on_start_clicked(self):
        host = (self.host_edit.text() or "127.0.0.1").strip()
        port = self._safe_int(self.port_edit.text(), 8000)
        workdir = self.dir_edit.text().strip() or os.getcwd()
        self.set_input("host", host)
        self.set_input("port", port)
        self.set_input("workdir", workdir)
        self.set_input("start", True)

    def _on_stop_clicked(self):
        self.set_input("start", False)

    def execute(self, *args, **kwargs):
        # normalisation
        inp = {}
        if args and isinstance(args[0], dict): inp.update(args[0])
        if kwargs: inp.update(kwargs)

        host = (inp.get("host", self._values.get("host")) or "127.0.0.1").strip()
        port = self._safe_int(inp.get("port", self._values.get("port")), 8000)
        workdir = inp.get("workdir", self._values.get("workdir")) or os.getcwd()
        start = bool(inp.get("start", self._values.get("start")))

        # sync UI
        try:
            self._ui["host"].setText(host)
            self._ui["port"].setText(str(port))
            self._ui["dir"].setText(workdir)
            self._ui["url"].setText(f"http://{host}:{port}/")
        except Exception:
            pass

        # start/stop
        if start and not self._running:
            self._start_server(host, port, workdir)
        elif (not start) and self._running:
            self._stop_server()

        # émettre sorties
        url = f"http://{host}:{port}/" if self._running else None
        self._emit("http_url", url)
        self._emit("is_running", self._running)
        self._emit("log", self._last_log)
        self._emit("last_feedback", self._last_feedback)

        # UI enable/disable
        try:
            self._ui["start"].setEnabled(not self._running)
            self._ui["stop"].setEnabled(self._running)
        except Exception:
            pass

        # >>> TOUJOURS retourner un dict avec les sorties déclarées
        return {
            "http_url": url,
            "is_running": self._running,
            "log": self._last_log,
            "last_feedback": self._last_feedback
        }

    # ---------- Impl ----------
    def _start_server(self, host: str, port: int, workdir: str):
        if self._running: return
        if workdir.lower().endswith("node_modules"):
            self._log("Dossier invalide: choisis le dossier qui contient ton index.html (pas node_modules).")
            return
        try:
            Handler = partial(_FeedbackHandler, directory=workdir)
            self._server = ThreadingHTTPServer((host, int(port)), Handler)
            self._server.plugin = self
        except Exception as e:
            self._log(f"HTTP bind échoué: {e}")
            self._server = None
            return

        def run():
            try:
                self._log(f"HTTP démarré: http://{host}:{port}/  (serve: {workdir})")
                self._server.serve_forever()
            except Exception as e:
                self._log(f"HTTP loop error: {e}")
            finally:
                try: self._server.server_close()
                except Exception: pass
                self._running = False
                self._log("HTTP arrêté.")

        self._running = True
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def _stop_server(self):
        if not self._running or not self._server: return
        try: self._server.shutdown()
        except Exception: pass
        self._running = False

    def _on_feedback(self, data: dict):
        self._last_feedback = data
        self._emit("last_feedback", data)
        self._log(f"Feedback reçu: {data}")

    # ---------- Utils ----------
    def _safe_int(self, v, default):
        try: return int(v)
        except Exception: return int(default)

    def _log(self, msg: str):
        self._last_log = msg
        try: self.outputs["log"].on_next(msg)
        except Exception: pass
        try: self._ui.get("log").setText(msg)
        except Exception: pass
        print(f"[ServerHTTP] {msg}")

    def _emit(self, name, value):
        if name in self.outputs:
            self.outputs[name].on_next(value)

    def on_remove(self):
        # assurer l’arrêt propre si le node est supprimé
        try: self._stop_server()
        except Exception: pass
