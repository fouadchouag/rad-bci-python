# rbciad_app/node_quick_help.py
from __future__ import annotations
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton
from PyQt5.QtCore import Qt
from rbciad_app.help_utils import open_node_help_in_docs

def _section(title: str, body: str) -> str:
    return f"<h3>{title}</h3><div>{body}</div>"

def _table(d: dict) -> str:
    if not d: return "<i>None</i>"
    rows = ''.join([f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in d.items()])
    return f"<table border='1' cellpadding='6'>{rows}</table>"

class NodeHelpDialog(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{getattr(plugin, 'display_name', 'Node')} — Help")
        self.setWindowModality(Qt.NonModal)
        self.resize(520, 480)
        v = QVBoxLayout(self)
        tb = QTextBrowser(self)
        v.addWidget(tb)
        btn_docs = QPushButton("Open full docs", self)
        btn_close = QPushButton("Close", self)
        btn_docs.clicked.connect(lambda: open_node_help_in_docs(getattr(plugin, 'display_name', 'Nodes')))
        btn_close.clicked.connect(self.close)
        v.addWidget(btn_docs); v.addWidget(btn_close)

        h = getattr(plugin, 'help', {}) or {}
        html = []
        html.append(_section("Summary", h.get("summary", "No summary available.")))
        html.append(_section("Inputs", _table(h.get("inputs", {}))))
        html.append(_section("Outputs", _table(h.get("outputs", {}))))
        params = h.get("parameters", [])
        if params:
            header = "<tr><th>Name</th><th>Type</th><th>Default</th><th>Unit</th><th>Description</th></tr>"
            rows = ''.join([
                f"<tr><td>{p.get('name','')}</td><td>{p.get('type','')}</td><td>{p.get('default','')}</td>"
                f"<td>{p.get('unit','')}</td><td>{p.get('desc','')}</td></tr>"
                for p in params
            ])
            html.append(_section("Parameters", f"<table border='1' cellpadding='6'>{header}{rows}</table>"))
        if h.get("usage"): html.append(_section("Typical usage", h["usage"]))
        if h.get("gotchas"): html.append(_section("Gotchas", "<ul>" + ''.join([f"<li>{g}</li>" for g in h["gotchas"]]) + "</ul>"))
        tb.setHtml('\n'.join(html))
