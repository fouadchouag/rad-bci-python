
# rbciad_app/help_editor.py
from __future__ import annotations
import ast, json, re, pprint, textwrap
from typing import Any, Dict, Optional, Tuple
from pathlib import Path

from PyQt5.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QComboBox, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QFileDialog, QMessageBox, QLabel, QSpinBox, QApplication
)
from PyQt5.QtCore import Qt

CATEGORIES = ["Input","Processing","ML","Output","I/O","Utils"]

def _py_dict_text(d: Dict[str, Any]) -> str:
    return pprint.pformat(d, width=88, compact=False, indent=2)

def _table_to_dict(table: QTableWidget) -> Dict[str, str]:
    out = {}
    for r in range(table.rowCount()):
        name = table.item(r, 0).text().strip() if table.item(r,0) else ""
        desc = table.item(r, 1).text().strip() if table.item(r,1) else ""
        if name:
            out[name] = desc or ""
    return out

def _table_to_params(table: QTableWidget):
    params = []
    for r in range(table.rowCount()):
        name = table.item(r,0).text().strip() if table.item(r,0) else ""
        typ  = table.item(r,1).text().strip() if table.item(r,1) else ""
        default = table.item(r,2).text().strip() if table.item(r,2) else ""
        unit = table.item(r,3).text().strip() if table.item(r,3) else ""
        desc = table.item(r,4).text().strip() if table.item(r,4) else ""
        if name:
            # try to parse default into python type
            val = default
            if default.lower() in ("true","false","none"):
                val = {"true":True,"false":False,"none":None}[default.lower()]
            else:
                try:
                    val = ast.literal_eval(default)
                except Exception:
                    val = default
            params.append({"name":name,"type":typ,"default":val,"unit":unit,"desc":desc})
    return params

def _dict_to_table(d: Dict[str,str], table: QTableWidget):
    table.setRowCount(0)
    for k,v in (d or {}).items():
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r,0,QTableWidgetItem(str(k)))
        table.setItem(r,1,QTableWidgetItem(str(v)))

def _params_to_table(params, table: QTableWidget):
    table.setRowCount(0)
    for p in (params or []):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r,0,QTableWidgetItem(str(p.get("name",""))))
        table.setItem(r,1,QTableWidgetItem(str(p.get("type",""))))
        table.setItem(r,2,QTableWidgetItem(str(p.get("default",""))))
        table.setItem(r,3,QTableWidgetItem(str(p.get("unit",""))))
        table.setItem(r,4,QTableWidgetItem(str(p.get("desc",""))))

class HelpEditorDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Help Editor", parent)
        self.setObjectName("HelpEditorDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        c = QWidget(self); self.setWidget(c)
        v = QVBoxLayout(c)

        # --- Meta ---
        meta = QFormLayout()
        self.ed_display = QLineEdit()
        self.cb_category = QComboBox(); self.cb_category.addItems(CATEGORIES)
        self.ed_summary = QPlainTextEdit(); self.ed_summary.setPlaceholderText("One-line summary for the node...")
        meta.addRow("Display name:", self.ed_display)
        meta.addRow("Category:", self.cb_category)
        meta.addRow(QLabel("Summary:")); meta.addRow(self.ed_summary)
        v.addLayout(meta)

        # --- Inputs/Outputs ---
        self.tbl_inputs = QTableWidget(0,2); self.tbl_inputs.setHorizontalHeaderLabels(["Input name","Description / shape"])
        self.tbl_outputs= QTableWidget(0,2); self.tbl_outputs.setHorizontalHeaderLabels(["Output name","Description / shape"])
        v.addWidget(QLabel("Inputs (name + description):")); v.addWidget(self.tbl_inputs)
        v.addWidget(QLabel("Outputs (name + description):")); v.addWidget(self.tbl_outputs)

        # --- Parameters ---
        self.tbl_params = QTableWidget(0,5); self.tbl_params.setHorizontalHeaderLabels(["Name","Type","Default","Unit","Description"])
        v.addWidget(QLabel("Parameters:")); v.addWidget(self.tbl_params)

        # --- Usage/Gotchas ---
        self.ed_usage = QPlainTextEdit(); self.ed_usage.setPlaceholderText("Typical usage...")
        self.ed_gotchas = QPlainTextEdit(); self.ed_gotchas.setPlaceholderText("One gotcha per line...")
        v.addWidget(QLabel("Usage:")); v.addWidget(self.ed_usage)
        v.addWidget(QLabel("Gotchas (one per line):")); v.addWidget(self.ed_gotchas)

        # --- Buttons ---
        btns = QHBoxLayout()
        b_add_in = QPushButton("+ In"); b_add_in.clicked.connect(lambda: self.tbl_inputs.insertRow(self.tbl_inputs.rowCount()))
        b_add_out= QPushButton("+ Out"); b_add_out.clicked.connect(lambda: self.tbl_outputs.insertRow(self.tbl_outputs.rowCount()))
        b_add_par= QPushButton("+ Param"); b_add_par.clicked.connect(lambda: self.tbl_params.insertRow(self.tbl_params.rowCount()))
        b_preview= QPushButton("Preview Python"); b_preview.clicked.connect(self.on_preview)
        b_copy   = QPushButton("Copy"); b_copy.clicked.connect(self.on_copy)
        b_insert = QPushButton("Insert into wrapper..."); b_insert.clicked.connect(self.on_insert)
        b_load   = QPushButton("Load from file..."); b_load.clicked.connect(self.on_load)
        for b in (b_add_in,b_add_out,b_add_par,b_preview,b_copy,b_insert,b_load):
            btns.addWidget(b)
        v.addLayout(btns)

    # --- Core helpers ---
    def build_help(self) -> Dict[str,Any]:
        gotchas = [ln.strip() for ln in self.ed_gotchas.toPlainText().splitlines() if ln.strip()]
        helpd = {
            "summary": self.ed_summary.toPlainText().strip(),
            "inputs": _table_to_dict(self.tbl_inputs),
            "outputs": _table_to_dict(self.tbl_outputs),
            "parameters": _table_to_params(self.tbl_params),
            "usage": self.ed_usage.toPlainText().strip(),
            "gotchas": gotchas,
        }
        return helpd

    def help_text(self) -> str:
        return _py_dict_text(self.build_help())

    # --- UI actions ---
    def on_preview(self):
        txt = self.help_text()
        dlg = QMessageBox(self)
        dlg.setWindowTitle("Help dict — Python")
        dlg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        dlg.setText(f"Paste this inside your plugin class:\n\nhelp = {txt}")
        dlg.exec_()

    def on_copy(self):
        QApplication.clipboard().setText(f"help = {self.help_text()}")
        QMessageBox.information(self, "Copied", "help = {...} copied to clipboard.")

    def _inject_into_source(self, src: str):
        """Insert or replace a class-level `help = {}` in the first Plugin/Node class."""
        lines = src.splitlines()
        # Find class header
        class_idx = None; indent = ""
        for i, line in enumerate(lines):
            m = re.match(r'^(\s*)class\s+([A-Za-z_][A-Za-z0-9_]*)(\s*\(.*?\))?\s*:\s*$', line)
            if m:
                cname = m.group(2)
                if cname.lower().endswith(("plugin","node")) or "Plugin" in cname or "Node" in cname:
                    class_idx = i; indent = m.group(1); break
        if class_idx is None:
            return src, False
        # Check existing help
        base_depth = len(indent)
        exist_start = None; exist_end = None
        # Find a 'help =' at class indent
        for j in range(class_idx+1, len(lines)):
            ln = lines[j]
            if re.match(r'^\s*class\s+', ln) and (len(ln) - len(ln.lstrip(' '))) <= base_depth:
                break
            if re.match(r'^\s{'+str(base_depth+1)+r',}help\s*=\s*\{', ln):
                # naive brace match in the concatenated string
                s = "\n".join(lines)
                start_pos = s.find(ln)
                brace = s.find("{", start_pos)
                depth = 0; k = brace
                while k < len(s):
                    if s[k] == "{": depth += 1
                    elif s[k] == "}":
                        depth -= 1
                        if depth == 0: k += 1; break
                    k += 1
                exist_start = start_pos
                exist_end = k
                src = s  # work in the joined string
                break
        help_block = textwrap.indent("help = " + self.help_text() + "\n", indent + "    ")
        if exist_start is not None:
            new_s = src[:exist_start] + help_block + src[exist_end:]
            return new_s, True
        else:
            # insert after class header
            insert_idx = sum(len(l)+1 for l in lines[:class_idx+1])
            s = "\n".join(lines)
            new_s = s[:insert_idx] + help_block + s[insert_idx:]
            return new_s, True

    def on_insert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select wrapper file", "", "Python (*.py)")
        if not path: return
        p = Path(path)
        src = p.read_text(encoding="utf-8", errors="ignore")
        new_src, ok = self._inject_into_source(src)
        if not ok:
            QMessageBox.warning(self, "No class?", "Could not find a Plugin/Node class to insert into.")
            return
        # backup
        bak = p.with_suffix(p.suffix + ".bak")
        if not bak.exists():
            bak.write_text(src, encoding="utf-8")
        p.write_text(new_src, encoding="utf-8")
        QMessageBox.information(self, "Done", f"Inserted help dict into:\n{p}")

    def on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load from file", "", "Python (*.py)")
        if not path: return
        p = Path(path)
        src = p.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(src)
        except Exception as e:
            QMessageBox.warning(self, "Parse error", str(e)); return
        help_obj = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "help":
                        try:
                            help_obj = ast.literal_eval(node.value)
                        except Exception:
                            pass
            if help_obj: break
        if not help_obj:
            QMessageBox.information(self, "Not found", "No `help = {...}` found in file.")
            return
        # Fill UI
        self.ed_summary.setPlainText(help_obj.get("summary",""))
        self.ed_usage.setPlainText(help_obj.get("usage",""))
        # display_name/category are class-level usually; keep empty here or user fills
        _dict_to_table(help_obj.get("inputs",{}), self.tbl_inputs)
        _dict_to_table(help_obj.get("outputs",{}), self.tbl_outputs)
        _params_to_table(help_obj.get("parameters",[]), self.tbl_params)
        got = help_obj.get("gotchas", [])
        self.ed_gotchas.setPlainText("\n".join(map(str, got)) if isinstance(got,list) else str(got))

def mount_help_editor_dock(main_window):
    """Create or toggle the Help Editor dock on the given QMainWindow."""
    from PyQt5.QtWidgets import QDockWidget
    existing = main_window.findChild(QDockWidget, "HelpEditorDock")
    if existing:
        existing.setVisible(not existing.isVisible())
        return existing
    dock = HelpEditorDock(main_window)
    main_window.addDockWidget(Qt.RightDockWidgetArea, dock)
    return dock
