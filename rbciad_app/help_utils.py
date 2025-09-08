# rbciad_app/help_utils.py
from __future__ import annotations
import os, sys, socket, threading, http.server, socketserver
from pathlib import Path
from typing import Optional
from PyQt5.QtCore import QUrl
from PyQt5.QtGui import QDesktopServices

# --- Resolve docs ----------------------------------------------------------------
def _resolve_docs_base() -> Path:
    env = os.environ.get("RBCIAD_DOCS_PATH")
    if env and Path(env).exists():
        return Path(env)
    here = Path(__file__).resolve()
    cand = (here.parent / "docs_site").resolve()
    if (cand / "index.html").exists():
        return cand
    for root in (Path.cwd(), Path.cwd().parent):
        for cand in ("rbciad_app/docs_site", "docs/site", "site"):
            p = (root / cand).resolve()
            if (p / "index.html").exists():
                return p
    return Path.cwd()

# --- Tiny HTTP server so search works (fetch) ------------------------------------
_SERVER = {"httpd": None, "port": None, "base": None}

def _find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs):  # silence console
        pass

def _ensure_server(doc_base: Path) -> str:
    """Start or reuse a tiny HTTP server for docs; return base URL."""
    global _SERVER
    if _SERVER["httpd"] and _SERVER["base"] == str(doc_base):
        return f"http://127.0.0.1:{_SERVER['port']}"
    port = _find_free_port()
    Handler = lambda *a, **k: _QuietHandler(*a, directory=str(doc_base), **k)  # py3.10+ 'directory' arg
    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _SERVER.update({"httpd": httpd, "port": port, "base": str(doc_base)})
    return f"http://127.0.0.1:{port}"

# --- URL builders ----------------------------------------------------------------
def _build_http_url(base_url: str, rel: Optional[str], anchor: Optional[str]) -> QUrl:
    if not rel:
        url = f"{base_url}/index.html"
    else:
        rel = rel.strip("/")
        # if you used use_directory_urls: false, pages are *.html
        url = f"{base_url}/{rel}.html"
        # but accept folder style too:
        if not Path(_resolve_docs_base() / f"{rel}.html").exists():
            url = f"{base_url}/{rel}/index.html"
    if anchor:
        url += f"#{anchor}"
    return QUrl(url)

# --- Public API ------------------------------------------------------------------
def open_help(rel: Optional[str] = None, anchor: Optional[str] = None) -> None:
    base = _resolve_docs_base()
    base_url = _ensure_server(base)  # serve docs over HTTP so search works
    QDesktopServices.openUrl(_build_http_url(base_url, rel, anchor))

def slugify(text: str) -> str:
    import re
    s = text.lower()
    s = re.sub(r"[^a-z0-9\s\-_/]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s

def open_node_help_in_docs(display_name: str) -> None:
    anchor = slugify(display_name)
    open_help("user/nodes", anchor)
