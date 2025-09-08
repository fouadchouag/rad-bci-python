
# rbciad_app/lowcode_hooks.py
from __future__ import annotations
from typing import Any, Dict, List
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPlainTextEdit, QDialogButtonBox, QMessageBox, QWidget
from PyQt5.QtCore import Qt
from pathlib import Path

from rbciad_app.help_autofill import build_help_from_spec, inject_help_into_source, normalize_spec

class _QuickHelpDialog(QDialog):
    def __init__(self, spec: Dict[str,Any], parent: QWidget|None=None):
        super().__init__(parent)
        self.setWindowTitle("Describe your node")
        self.setModal(True)
        self.setMinimumWidth(520)

        ns = normalize_spec(spec)

        v = QVBoxLayout(self)
        form = QFormLayout()
        self.ed_summary = QLineEdit()
        self.ed_summary.setPlaceholderText(f'One-line: What does "{ns["display_name"]}" do?')
        self.ed_usage = QPlainTextEdit()
        self.ed_usage.setPlaceholderText("How to use it in a pipeline (where to place it, typical settings, upstream/downstream)?")
        form.addRow("Summary:", self.ed_summary)
        form.addRow("Usage:", self.ed_usage)
        v.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        return self.ed_summary.text().strip(), self.ed_usage.toPlainText().strip()

def after_node_created(spec: Dict[str,Any], wrapper_path: str|Path, parent: QWidget|None=None, ask: bool=True) -> bool:
    """Call this right after your lowcode creator generates the wrapper file.
    - spec: the spec dict you already have (display_name, category, inputs, outputs, parameters ... any shape)
    - wrapper_path: path to the generated .py file
    - parent: parent widget (MainWindow) for the small capture dialog
    - ask: if True, pop a tiny dialog to capture Summary/Usage; if False, will auto-fill a generic summary
    Returns True if file updated."""
    p = Path(wrapper_path)
    if not p.exists():
        QMessageBox.warning(parent, "Wrapper not found", f"{p} does not exist.")
        return False

    summary = f"{normalize_spec(spec)['display_name']}: custom node."
    usage = "Connect as required by its inputs/outputs; adjust parameters as needed."

    if ask:
        dlg = _QuickHelpDialog(spec, parent=parent)
        if dlg.exec_() != QDialog.Accepted:
            # user canceled -> keep defaults (still inject to standardize)
            pass
        else:
            s,u = dlg.values()
            if s: summary = s
            if u: usage = u

    helpd = build_help_from_spec(spec, summary=summary, usage=usage)
    src = p.read_text(encoding="utf-8", errors="ignore")
    new_src = inject_help_into_source(src, helpd)

    if new_src != src:
        bak = p.with_suffix(p.suffix + ".bak")
        if not bak.exists():
            bak.write_text(src, encoding="utf-8")
        p.write_text(new_src, encoding="utf-8")
        return True
    return False
