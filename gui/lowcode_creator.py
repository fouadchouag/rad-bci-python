# gui/lowcode_creator.py
import os
import re
import shutil
import json
from dataclasses import dataclass
from typing import List, Dict, Any
from textwrap import dedent

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QFileDialog, QMessageBox, QApplication,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QFormLayout, QFrame
)
from PyQt5.QtCore import Qt, QPoint


# --- Help autofill (dialog Summary/Usage + injection dans le wrapper)
try:
    from rbciad_app.lowcode_hooks import after_node_created as _lc_after_node_created
except Exception:
    _lc_after_node_created = None



# ---------------- Helpers noms / chemins / langue ----------------

def _slugify(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]+', '_', s).strip('_').lower() or "node"

def _classify(s: str) -> str:
    parts = re.findall(r'[A-Za-z0-9]+', s)
    base = ''.join(p.capitalize() for p in parts) or "CustomNode"
    if base[0].isdigit():
        base = "_" + base
    return base

def _canon_language(s: str) -> str:
    s = (s or "").strip()
    mapping = {
        "Python":"Python","Rust":"Rust",
        "NodeJS":"Node.js","NodeJs":"Node.js","Node.js":"Node.js",
        "Shell":"Shell","R":"R","Julia":"Julia","Octave":"Octave","C":"C","C++":"C++"
    }
    return mapping.get(s, s)

def _dtype_hint(dtype: str) -> str:
    d = (dtype or "").strip().lower()
    if d == "ndarray_2d": return "2D float [ch x samples]"
    if d == "mne_raw":    return "mne.Raw"
    if d == "sfreq":      return "float (Hz)"
    if d == "path":       return "file path"
    if d in ("float","int","bool","str"): return d
    if d == "json":       return "JSON object"
    return dtype or ""



def _samefile_case_insensitive(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except Exception:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))

# ---------------- Types pris en charge ----------------
SUPPORTED_TYPES = [
    "float", "int", "bool", "str", "sfreq",
    "ndarray_2d",       # (N,C) numpy ↔ JSON: [C][N]
    "mne_raw",          # entrée MNE Raw → sérialisé comme ndarray_2d + meta fs
    "json", "path"
]

# Param types pour Option A (UI)
PARAM_TYPES = ["float", "int", "bool", "enum", "str", "sfreq"]

@dataclass
class IOPort:
    name: str
    dtype: str  # in SUPPORTED_TYPES

@dataclass
class ParamSpec:
    name: str
    ptype: str          # in PARAM_TYPES
    default: str = ""   # texte; parsé par le wrapper
    vmin: str = ""
    vmax: str = ""
    step: str = ""
    unit: str = ""
    choices: str = ""   # pour enum: "off,50,60"
    tooltip: str = ""

# ---------------- UI: table d'IO ----------------

class IOTable(QTableWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels([f"{title} name", "type"])
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setMinimumSectionSize(160)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.setEditTriggers(QTableWidget.AllEditTriggers)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)

    def add_row(self, name="input", dtype="ndarray_2d"):
        r = self.rowCount()
        self.insertRow(r)
        name_item = QTableWidgetItem(name)
        self.setItem(r, 0, name_item)
        cb = QComboBox(self)
        cb.addItems(SUPPORTED_TYPES)
        idx = SUPPORTED_TYPES.index(dtype) if dtype in SUPPORTED_TYPES else 0
        cb.setCurrentIndex(idx)
        self.setCellWidget(r, 1, cb)
        self.selectRow(r)

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def move_selected(self, delta: int):
        rows = sorted({idx.row() for idx in self.selectedIndexes()})
        if not rows:
            return
        if delta < 0:
            for r in rows:
                if r == 0: continue
                self._swap_rows(r, r-1)
                self.selectRow(r-1)
        else:
            for r in reversed(rows):
                if r >= self.rowCount()-1: continue
                self._swap_rows(r, r+1)
                self.selectRow(r+1)

    def _swap_rows(self, r1, r2):
        n1 = self.item(r1, 0).text() if self.item(r1, 0) else ""
        n2 = self.item(r2, 0).text() if self.item(r2, 0) else ""
        self.setItem(r1, 0, QTableWidgetItem(n2))
        self.setItem(r2, 0, QTableWidgetItem(n1))
        cb1 = self.cellWidget(r1, 1)
        cb2 = self.cellWidget(r2, 1)
        if cb1 and cb2:
            t1 = cb1.currentText(); t2 = cb2.currentText()
            cb1.setCurrentText(t2)
            cb2.setCurrentText(t1)

    def rows(self) -> List[IOPort]:
        out = []
        for r in range(self.rowCount()):
            name_it = self.item(r, 0)
            name = (name_it.text() if name_it else "").strip()
            if not name:
                continue
            cb = self.cellWidget(r, 1)
            dtype = cb.currentText() if cb else "json"
            out.append(IOPort(name=name, dtype=dtype))
        return out

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_selected()
        elif e.key() == Qt.Key_Up and (e.modifiers() & Qt.ControlModifier):
            self.move_selected(-1)
        elif e.key() == Qt.Key_Down and (e.modifiers() & Qt.ControlModifier):
            self.move_selected(+1)
        else:
            super().keyPressEvent(e)

    def _on_context_menu(self, pos: QPoint):
        m = QMenu(self)
        m.addAction("➕ Ajouter", lambda: self.add_row(f"item{self.rowCount()+1}", "json"))
        m.addAction("➖ Supprimer la sélection", self.remove_selected)
        m.addSeparator()
        m.addAction("⭡ Monter (Ctrl+↑)", lambda: self.move_selected(-1))
        m.addAction("⭣ Descendre (Ctrl+↓)", lambda: self.move_selected(+1))
        m.exec_(self.viewport().mapToGlobal(pos))

# ---------------- UI: table des paramètres ----------------

class ParamTable(QTableWidget):
    COLS = ["name","type","default","min","max","step","unit","choices","tooltip"]
    def __init__(self, parent=None):
        super().__init__(0, len(self.COLS), parent)
        self.setHorizontalHeaderLabels(self.COLS)
        hdr = self.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.Stretch)
        hdr.setMinimumSectionSize(110)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.ExtendedSelection)
        self.setEditTriggers(QTableWidget.AllEditTriggers)

    def add_row(self,
                name="param",
                ptype="float",
                default="",
                vmin="",
                vmax="",
                step="",
                unit="",
                choices="",
                tooltip=""):
        r = self.rowCount()

        def _set(r,c,txt):
            it = QTableWidgetItem(str(txt))
            self.setItem(r,c,it)

        self.insertRow(r)
        _set(r,0,name)
        cb = QComboBox(self)
        cb.addItems(PARAM_TYPES)
        if ptype in PARAM_TYPES:
            cb.setCurrentText(ptype)
        self.setCellWidget(r,1,cb)
        _set(r,2,default); _set(r,3,vmin); _set(r,4,vmax)
        _set(r,5,step); _set(r,6,unit); _set(r,7,choices); _set(r,8,tooltip)
        self.selectRow(r)

    def remove_selected(self):
        rows = sorted({idx.row() for idx in self.selectedIndexes()}, reverse=True)
        for r in rows:
            self.removeRow(r)

    def rows(self) -> List[ParamSpec]:
        out: List[ParamSpec] = []
        for r in range(self.rowCount()):
            name = (self.item(r,0).text() if self.item(r,0) else "").strip()
            if not name:
                continue
            cb = self.cellWidget(r,1)
            ptype = cb.currentText() if cb else "float"
            default = (self.item(r,2).text() if self.item(r,2) else "").strip()
            vmin    = (self.item(r,3).text() if self.item(r,3) else "").strip()
            vmax    = (self.item(r,4).text() if self.item(r,4) else "").strip()
            step    = (self.item(r,5).text() if self.item(r,5) else "").strip()
            unit    = (self.item(r,6).text() if self.item(r,6) else "").strip()
            choices = (self.item(r,7).text() if self.item(r,7) else "").strip()
            tooltip = (self.item(r,8).text() if self.item(r,8) else "").strip()
            out.append(ParamSpec(name, ptype, default, vmin, vmax, step, unit, choices, tooltip))
        return out

# ---------------- LowCode Creator ----------------

class LowCodeCreator(QWidget):
    def __init__(self, main_window=None):
        super().__init__()
        self.setWindowTitle("🧩 LowCode – Création de Node")
        self.setMinimumWidth(1100)
        self.main_window = main_window

        layout = QVBoxLayout(self); layout.setSpacing(10)

        # Nom + Langage + Mode d'exécution
        top = QHBoxLayout()
        top.addWidget(QLabel("Nom du node :"))
        self.name_input = QLineEdit()
        top.addWidget(self.name_input, 1)

        top.addWidget(QLabel("Langage :"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Python", "R", "Julia", "NodeJS", "Shell", "Octave", "C", "C++", "Rust"])
        self.lang_combo.setCurrentText("Rust")
        top.addWidget(self.lang_combo)

        top.addWidget(QLabel("Mode d'exécution :"))
        self.exec_mode_combo = QComboBox()
        # auto: Python(.py) => inprocess, sinon subprocess
        self.exec_mode_combo.addItems(["auto", "inprocess", "subprocess"])
        self.exec_mode_combo.setCurrentText("auto")
        top.addWidget(self.exec_mode_combo)

        layout.addLayout(top)

        # IO tables (départ: VIDES)
        io_bar = QHBoxLayout()
        left = QVBoxLayout(); right = QVBoxLayout()

        left.addWidget(QLabel("Entrées (nom + type)"))
        self.inputs_tbl = IOTable("input")
        left.addWidget(self.inputs_tbl)
        tools_in = QHBoxLayout()
        btn_add_in = QPushButton("➕ Ajouter"); btn_add_in.clicked.connect(lambda: self.inputs_tbl.add_row(f"input{self.inputs_tbl.rowCount()+1}", "json"))
        btn_del_in = QPushButton("➖ Supprimer"); btn_del_in.clicked.connect(self.inputs_tbl.remove_selected)
        tools_in.addWidget(btn_add_in); tools_in.addWidget(btn_del_in); tools_in.addStretch(1)
        left.addLayout(tools_in)

        right.addWidget(QLabel("Sorties (nom + type)"))
        self.outputs_tbl = IOTable("output")
        right.addWidget(self.outputs_tbl)
        tools_out = QHBoxLayout()
        btn_add_out = QPushButton("➕ Ajouter"); btn_add_out.clicked.connect(lambda: self.outputs_tbl.add_row(f"output{self.outputs_tbl.rowCount()+1}", "json"))
        btn_del_out = QPushButton("➖ Supprimer"); btn_del_out.clicked.connect(self.outputs_tbl.remove_selected)
        tools_out.addWidget(btn_add_out); tools_out.addWidget(btn_del_out); tools_out.addStretch(1)
        right.addLayout(tools_out)

        io_bar.addLayout(left, 1); io_bar.addLayout(right, 1)
        layout.addLayout(io_bar)

        # ---------------- Parameters (Option A) ----------------
        layout.addWidget(self._separator("Paramètres (UI auto-générée)"))
        self.params_tbl = ParamTable()
        layout.addWidget(self.params_tbl)
        tools_param = QHBoxLayout()
        btn_add_param = QPushButton("➕ Ajouter"); btn_add_param.clicked.connect(lambda: self.params_tbl.add_row(f"param{self.params_tbl.rowCount()+1}", "float"))
        btn_del_param = QPushButton("➖ Supprimer"); btn_del_param.clicked.connect(self.params_tbl.remove_selected)
        btn_preset_filter = QPushButton("⚡ Préréglage Filter (low/high/notch/q/order)")
        btn_preset_filter.clicked.connect(self._apply_filter_preset)
        tools_param.addWidget(btn_add_param); tools_param.addWidget(btn_del_param); tools_param.addStretch(1); tools_param.addWidget(btn_preset_filter)
        layout.addLayout(tools_param)

        # Préréglage pratique I/O (optionnel)
        preset = QHBoxLayout()
        btn_preset_eeg = QPushButton("⚡ I/O EEG (raw+sfreq → raw)")
        btn_preset_eeg.clicked.connect(self._apply_eeg_preset)
        preset.addWidget(btn_preset_eeg); preset.addStretch(1)
        layout.addLayout(preset)

        # Actions principales
        actions = QHBoxLayout()
        self.btn_generate = QPushButton("🛠️ Générer squelette (copier)")
        self.btn_pick     = QPushButton("📂 Choisir binaire/script…")
        self.btn_add      = QPushButton("➕ Ajouter à la palette")
        actions.addWidget(self.btn_generate)
        actions.addStretch(1)
        actions.addWidget(self.btn_pick)
        actions.addWidget(self.btn_add)
        layout.addLayout(actions)

        # Log
        self.log = QTextEdit(); self.log.setReadOnly(True)
        layout.addWidget(QLabel("Log / Info :"))
        layout.addWidget(self.log)

        # Connect
        self.btn_generate.clicked.connect(self._generate_skeleton)
        self.btn_pick.clicked.connect(self._load_script)
        self.btn_add.clicked.connect(self._add_to_palette)

        self.selected_file = None

    # --------- séparateur visuel ----------
    def _separator(self, title: str) -> QWidget:
        box = QFrame(); box.setFrameShape(QFrame.HLine); box.setFrameShadow(QFrame.Sunken)
        lbl = QLabel(f" {title} "); lbl.setStyleSheet("color:#666;")
        cont = QHBoxLayout(); cont.addWidget(lbl); cont.addWidget(box, 1)
        out = QWidget(); out.setLayout(cont)
        return out

    # --------- Préréglages ----------
    def _apply_eeg_preset(self):
        self.inputs_tbl.add_row("raw", "ndarray_2d")
        self.inputs_tbl.add_row("sfreq", "sfreq")
        self.outputs_tbl.add_row("raw", "ndarray_2d")

    def _apply_filter_preset(self):
        self.params_tbl.add_row("low",   "float", "1.0",  "0.1",  "",    "0.1", "Hz",  "",          "High-pass cutoff")
        self.params_tbl.add_row("high",  "float", "40.0", "1.0",  "nyquist", "0.5", "Hz",  "",      "Low-pass cutoff")
        self.params_tbl.add_row("notch", "enum",  "off",  "",     "",    "",    "",    "off,50,60", "0=off / 50/60 Hz")
        self.params_tbl.add_row("q",     "float", "0.707","0.4",  "1.4", "0.01","",    "",          "Q factor")
        self.params_tbl.add_row("order", "int",   "2",    "1",    "8",   "1",   "",    "",          "Filter order")

    # ---------------- Génération de squelette (externe) ----------------

    def _generate_skeleton(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Erreur", "Veuillez indiquer un nom.")
            return
        lang = _canon_language(self.lang_combo.currentText())
        ins = self.inputs_tbl.rows()
        outs = self.outputs_tbl.rows()
        params = self.params_tbl.rows()
        if not outs:
            QMessageBox.warning(self, "Erreur", "Veuillez définir au moins une sortie.")
            return
        skeleton = self._polyglot_business_skeleton(name, lang, ins, outs, params)
        QApplication.clipboard().setText(skeleton)
        self.log.append(f"✅ Squelette généré pour {name} ({lang}) et copié dans le presse-papiers.")

    def _polyglot_business_skeleton(self, name: str, lang: str, ins: List[IOPort], outs: List[IOPort], params: List[ParamSpec]) -> str:
        def _in_fields():
            f = []
            for p in ins:
                if p.dtype == "ndarray_2d":
                    f.append(f'  "{p.name}": [[...channels...],[...]]  // [C][N] float32')
                elif p.dtype == "mne_raw":
                    f.append(f'  "{p.name}": [[...channels...],[...]], "{p.name}_fs": 250.0')
                elif p.dtype == "sfreq":
                    f.append(f'  "{p.name}": 250.0')
                elif p.dtype in ("float","int","bool","str","path"):
                    f.append(f'  "{p.name}": <{p.dtype}>')
                else:
                    f.append(f'  "{p.name}": {{ ... }}  // json')
            for par in params:
                f.append(f'  "{par.name}": <{par.ptype}>  // UI param')
            return "{\n" + (",\n".join(f) if f else "  // (aucune)") + "\n}"

        def _out_fields():
            f = [f'  "{p.name}": <{p.dtype or "json"}>' for p in outs]
            return "{\n" + (",\n".join(f) if f else "  // (aucune)") + "\n}"

        if lang == "Rust":
            return f"""// === {name} (métier) — Rust CLI ===
// Deux modes supportés par le wrapper Python généré :
//  1) Mode persistant flux: lance le binaire avec --stdio et dialogue via lignes JSON (stdin/stdout)
//  2) Mode fichiers (fallback): --in <file.json> --out <file.json>
//
// Convention d'entrée (exemple):
// {_in_fields()}
// Convention de sortie (exemple):
// {_out_fields()}

use std::fs::File;
use std::io::{{self, Read, Write, BufRead}};
use serde_json::Value;

fn main() {{
    let args: Vec<String> = std::env::args().collect();

    // --- MODE PERSISTANT (--stdio) ---
    if args.iter().any(|a| a == "--stdio") {{
        let stdin = io::stdin();
        let mut stdout = io::stdout();
        for line in stdin.lock().lines() {{
            let Ok(line) = line else {{ break }};
            if line.trim().is_empty() {{ continue; }}
            let mut data: Value = serde_json::from_str(&line).unwrap_or(serde_json::json!({{}}));

            // TODO: lire, traiter, etc.

            let result = serde_json::json!({{
                // "raw": <matrice [C][N]>,
            }});

            writeln!(stdout, "{{}}", result.to_string()).ok();
            stdout.flush().ok();
        }}
        return;
    }}

    // --- MODE FICHIERS (--in/--out) ---
    let in_path  = args.iter().position(|a| a == "--in").and_then(|i| args.get(i+1)).expect("missing --in");
    let out_path = args.iter().position(|a| a == "--out").and_then(|i| args.get(i+1)).expect("missing --out");

    let mut s = String::new();
    File::open(in_path).unwrap().read_to_string(&mut s).unwrap();
    let mut data: Value = serde_json::from_str(&s).unwrap();

    // TODO: traitement...

    let result = serde_json::json!({{
        // "raw": <matrice [C][N]>,
    }});

    let mut f = File::create(out_path).unwrap();
    write!(f, "{{}}", result.to_string()).unwrap();
}}
"""
        if lang == "Python":
            return f'''# === {name} (métier) — Python (in-process friendly) ===
# Le wrapper peut appeler cette fonction **en mémoire** (sans JSON) si mode=inprocess.
# Signature conseillée:
#   def process(payload: dict) -> dict
# Où payload peut contenir:
#   - 'raw' : np.ndarray float32 shape (C,N) si fourni
#   - 'sfreq' : float
#   - vos paramètres UI: low/high/notch/q/order, etc.

import numpy as np

def process(payload: dict) -> dict:
    raw = payload.get("raw", None)       # np.ndarray (C,N) si disponible
    sfreq = float(payload.get("sfreq", 0.0) or 0.0)
    # Exemple params:
    low = float(payload.get("low", 1.0))
    high = float(payload.get("high", 40.0))

    if isinstance(raw, np.ndarray):
        out = raw.copy()  # TODO: votre traitement
        return {{"raw": out}}
    else:
        # si pas de RAW, renvoyer autre chose
        return {{}}
'''
        return f"""# === {name} (métier) — {lang} ===
# Votre programme doit lire --in <file> (JSON) et écrire --out <file> (JSON).
# (Optionnel, recommandé) Supporter un mode persistant --stdio: lire lignes JSON sur stdin, écrire lignes JSON sur stdout.
# Entrée (exemple):
# {_in_fields()}
# Sortie (exemple):
# {_out_fields()}
"""

    # ---------------- Sélection fichier source ----------------

    def _load_script(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Choisir un binaire/script externe", "", "Tous (*.*)")
        if filepath:
            self.selected_file = filepath
            self.log.append(f"📂 Fichier sélectionné : {filepath}")

    # ---------------- Ajout à la palette (génère wrapper) ----------------

    def _add_to_palette(self):
        if not hasattr(self, "selected_file") or not self.selected_file:
            QMessageBox.warning(self, "Erreur", "Veuillez d’abord charger un binaire/script (📂).")
            return

        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Erreur", "Veuillez spécifier un nom.")
            return
        ins = self.inputs_tbl.rows()
        outs = self.outputs_tbl.rows()
        params = self.params_tbl.rows()
        if not outs:
            QMessageBox.warning(self, "Erreur", "Veuillez définir au moins une sortie.")
            return

        lang_disp  = _canon_language(self.lang_combo.currentText())
        class_name = _classify(name)
        slug       = _slugify(name)
        exec_mode  = self.exec_mode_combo.currentText().strip().lower()

        # Copier le binaire sous custom_plugins/external_scripts/
        dest_script_dir = os.path.join("custom_plugins", "external_scripts")
        os.makedirs(dest_script_dir, exist_ok=True)
        src = self.selected_file
        script_name = os.path.basename(src)
        dest_script_path = os.path.join(dest_script_dir, script_name)

        try:
            if _samefile_case_insensitive(src, dest_script_path):
                self.log.append(f"[lowcode] 🔁 Binaire déjà présent, copie ignorée: {dest_script_path}")
            else:
                shutil.copy2(src, dest_script_path)
                self.log.append(f"✅ Script externe copié : {dest_script_path}")
        except shutil.SameFileError:
            self.log.append(f"[lowcode] 🔁 Même fichier source/destination, copie ignorée: {dest_script_path}")
        except Exception as e:
            QMessageBox.warning(self, "Copie échouée", f"Impossible de copier le fichier:\n{e}")
            return

        # Générer le wrapper Python selon les types + paramètres UI
        wrapper_code = self._generate_typed_wrapper(
            display_name=name, class_name=class_name, slug=slug,
            script_path=dest_script_path, inputs=ins, outputs=outs,
            language=lang_disp, params=params, exec_mode=exec_mode
        )
        wrapper_path = os.path.join("custom_plugins", f"{slug}_plugin.py")
        try:
            with open(wrapper_path, "w", encoding="utf-8") as f:
                f.write(wrapper_code)
            self.log.append(f"📦 Wrapper Python généré : {wrapper_path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Écriture du wrapper impossible:\n{e}")
            return

        # === Nouveau : Auto-fill du help (ne demande que Summary + Usage) ===
        try:
            if _lc_after_node_created is None:
                raise RuntimeError("lowcode_hooks not available")
            # spec compatible avec rbciad_app.help_autofill.normalize_spec()
            spec: Dict[str, Any] = {
                "display_name": name,
                "category": "Custom",
                "inputs":  [{"name": p.name, "description": _dtype_hint(p.dtype)} for p in ins],
                "outputs": [{"name": p.name, "description": _dtype_hint(p.dtype)} for p in outs],
                "parameters": [
                    {
                        "name": p.name,
                        "type": p.ptype,
                        "default": p.default,
                        "unit": p.unit,
                        "desc": p.tooltip,
                    } for p in params
                ],
            }
            # ask=True => mini dialogue pour saisir Summary + Usage, puis injection
            _lc_after_node_created(spec, wrapper_path, parent=self, ask=True)
            self.log.append("🧠 Help dict auto-rempli (Summary/Usage saisis).")
        except Exception as e:
            self.log.append(f"[lowcode] (info) Help autofill indisponible: {e}")
        # Importer dynamiquement et ajouter à la palette
        try:
            from importlib import import_module, reload
            mod_name = f"custom_plugins.{slug}_plugin"
            module = import_module(mod_name)
            module = reload(module)
            plugin_class = getattr(module, f"{class_name}Plugin")
            if self.main_window:
                self.main_window.add_plugin_to_palette("Custom", plugin_class)
            self.log.append("🎉 Plugin ajouté dynamiquement à la palette.")
        except Exception as e:
            self.log.append(f"[ERREUR] Ajout échoué : {e}")


    # ---------------- Génération du wrapper typé + UI paramètres ----------------

    def _generate_typed_wrapper(self, display_name: str, class_name: str, slug: str,
                                script_path: str, inputs: List[IOPort], outputs: List[IOPort],
                                language: str, params: List[ParamSpec], exec_mode: str) -> str:
        """
        Wrapper BasePlugin:
          - Crée des pins d'après 'inputs'/'outputs'
          - Génère un panneau de paramètres (build_widget) d'après 'params'
          - Sérialise E/S selon dtype (MNE Raw → ndarray_2d [C][N])
          - Ajoute les paramètres UI dans le payload JSON
          - Garde-fous Nyquist si 'sfreq' présent
          - 🔁 Recalcule automatiquement (debounce 300 ms)
          - ⚡ Mode persistant (stdio) + fallback fichiers
          - 🧠 Cache .tolist() pour RAW inchangé
          - 🚀 Nouveau: mode **inprocess** pour Python (.py) → appel direct `process(payload)`
        """
        script_path_norm = script_path.replace("\\", "/")

        # Pins setup
        def _pin_decl(io: List[IOPort], kind: str) -> str:
            lines = []
            for p in io:
                lines.append(f'self.{kind}["{p.name}"] = BehaviorSubject(None)')
            return "\n        ".join(lines) or "pass"

        # ParamDefs
        def _param_defs_literal(ps: List[ParamSpec]) -> str:
            arr: List[Dict[str, Any]] = []
            for p in ps:
                d = dict(
                    name=p.name, type=p.ptype, default=p.default,
                    min=p.vmin, max=p.vmax, step=p.step, unit=p.unit,
                    choices=p.choices, tooltip=p.tooltip
                )
                arr.append(d)
            arr.append(dict(name="preview", type="bool", default="true",
                            tooltip="Aperçu rapide: envoyer seulement la dernière fenêtre au binaire"))
            arr.append(dict(name="preview_window_s", type="float", default="10.0", min="1", max="60", step="1", unit="s",
                            tooltip="Durée de la fenêtre envoyée en mode aperçu"))
            arr.append(dict(name="preview_decim", type="int", default="1", min="1", max="10", step="1",
                            tooltip="Décimation appliquée avant envoi (1 = aucune)"))
            return json.dumps(arr, ensure_ascii=False)

        param_defs_py = _param_defs_literal(params)

        # Entrées → sérialisation JSON + buffer NP pour inprocess
        in_ser_lines = [
            "payload = {}",
            "payload_np = {}  # pour inprocess (numpy, pas de JSON)",
            "missing = []",
            "def _to_ndarray2d(value):",
            "    import numpy as _np",
            "    try:",
            "        from mne.io.base import BaseRaw as _BaseRaw",
            "        if isinstance(value, _BaseRaw):",
            "            key = id(value)",
            "            if getattr(self, '_mne_cache', None) is None: self._mne_cache = {}",
            "            arr = self._mne_cache.get(key)",
            "            if arr is None:",
            "                arr = value.get_data().astype(_np.float32, copy=False)  # (C,N)",
            "                self._mne_cache[key] = arr",
            "            return arr",
            "    except Exception:",
            "        pass",
            "    arr = _np.asarray(value)",
            "    if arr.ndim != 2:",
            '        raise ValueError("ndarray_2d attendu: array 2D")',
            "    C, N = arr.shape[0], arr.shape[1]",
            "    if not (C > 0 and N > C*2):",
            "        arr = arr.T  # (N,C) → (C,N)",
            "    return arr.astype(_np.float32, copy=False)",
            "__raw_arr_tmp = None",
        ]

        for p in inputs:
            n, t = p.name, p.dtype
            is_required = not n.startswith("opt_")
            if t == "ndarray_2d":
                if n == "raw":
                    in_ser_lines += [
                        f"val = kwargs.get('{n}', None)",
                        f"if val is not None:",
                        f"    __raw_arr_tmp = _to_ndarray2d(val)",
                        "else:",
                        f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                    ]
                else:
                    in_ser_lines += [
                        f"val = kwargs.get('{n}', None)",
                        f"if val is not None:",
                        f"    _arr = _to_ndarray2d(val)",
                        f"    payload_np['{n}'] = _arr  # inprocess",
                        f"    payload['{n}'] = _arr.tolist()  # JSON",
                        "else:",
                        f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                    ]
            elif t == "mne_raw":
                if n == "raw":
                    in_ser_lines += [
                        f"val = kwargs.get('{n}', None)",
                        f"if val is not None:",
                        f"    __raw_arr_tmp = _to_ndarray2d(val)",
                        f"    try:",
                        f"        fs = float(getattr(val, 'info', {{}}).get('sfreq', 0.0) or 0.0)",
                        f"        if fs>0: payload['sfreq'] = fs; payload_np['sfreq'] = fs",
                        f"    except Exception: pass",
                        "else:",
                        f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                    ]
                else:
                    in_ser_lines += [
                        f"val = kwargs.get('{n}', None)",
                        f"if val is not None:",
                        f"    _arr = _to_ndarray2d(val)",
                        f"    payload_np['{n}'] = _arr",
                        f"    payload['{n}'] = _arr.tolist()",
                        f"    try:",
                        f"        fs = float(getattr(val, 'info', {{}}).get('sfreq', 0.0) or 0.0)",
                        f"        if fs>0: payload['{n}_fs'] = fs; payload_np['{n}_fs'] = fs",
                        f"    except Exception: pass",
                        "else:",
                        f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                    ]
            elif t in ('float','sfreq'):
                in_ser_lines += [
                    f"if '{n}' in kwargs and kwargs['{n}'] is not None:",
                    f"    payload['{n}'] = float(kwargs['{n}']); payload_np['{n}'] = float(kwargs['{n}'])",
                    "else:",
                    f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                ]
            elif t == "int":
                in_ser_lines += [
                    f"if '{n}' in kwargs and kwargs['{n}'] is not None:",
                    f"    payload['{n}'] = int(kwargs['{n}']); payload_np['{n}'] = int(kwargs['{n}'])",
                    "else:",
                    f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                ]
            elif t == "bool":
                in_ser_lines += [
                    f"if '{n}' in kwargs and kwargs['{n}'] is not None:",
                    f"    payload['{n}'] = bool(kwargs['{n}']); payload_np['{n}'] = bool(kwargs['{n}'])",
                    "else:",
                    f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                ]
            elif t in ("str","path"):
                in_ser_lines += [
                    f"if '{n}' in kwargs and kwargs['{n}'] is not None:",
                    f"    payload['{n}'] = str(kwargs['{n}']); payload_np['{n}'] = str(kwargs['{n}'])",
                    "else:",
                    f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                ]
            else:
                in_ser_lines += [
                    f"val = kwargs.get('{n}', None)",
                    f"if val is not None:",
                    f"    if isinstance(val, str):",
                    f"        try: val = json.loads(val)",
                    f"        except Exception: pass",
                    f"    payload['{n}'] = val; payload_np['{n}'] = val",
                    "else:",
                    f"    {'missing.append(%r)' % n if is_required else 'pass'}",
                ]

        in_ser_lines += [
            "if missing:",
            "    return {}",
            "",
            "# ⚡ Prévisualisation + cache tolist() uniquement pour JSON",
            "try:",
            "    import numpy as _np",
            "    if __raw_arr_tmp is not None:",
            "        fs = float(kwargs.get('sfreq', 0.0) or payload.get('sfreq', 0.0) or 0.0)",
            "        _p = params or {}",
            "        _quick = bool(str(_p.get('preview','true')).strip().lower() in ('1','true','yes','on'))",
            "        _win   = float(_p.get('preview_window_s', 10.0) or 10.0)",
            "        _dec   = int(_p.get('preview_decim', 1) or 1)",
            "        arr = __raw_arr_tmp",
            "        if _quick and fs > 0.0:",
            "            Nwin = int(max(1, min(arr.shape[1], fs * _win)))",
            "            arr = arr[:, -Nwin:]",
            "            if _dec > 1:",
            "                arr = arr[:, ::_dec]",
            "                payload['sfreq'] = float(fs / _dec); payload_np['sfreq'] = float(fs / _dec)",
            "        # Mettre direct en NP pour inprocess",
            "        payload_np['raw'] = arr",
            "        # JSON: cache tolist()",
            "        _src_obj = kwargs.get('raw', None)",
            "        _src_id = id(_src_obj) if _src_obj is not None else None",
            "        if getattr(self, '_raw_list_cache', None) is None:",
            "            self._raw_list_cache = {'src_id': None, 'lst': None, 'shape': None, 'fs': None}",
            "        use_cache = (self._raw_list_cache['src_id'] == _src_id and",
            "                     self._raw_list_cache.get('shape') == tuple(arr.shape) and",
            "                     abs((self._raw_list_cache.get('fs') or -1.0) - float(payload.get('sfreq',0.0) or 0.0)) < 1e-9)",
            "        if use_cache and self._raw_list_cache['lst'] is not None:",
            "            payload['raw'] = self._raw_list_cache['lst']",
            "        else:",
            "            _lst = arr.astype(_np.float32, copy=False).tolist()",
            "            payload['raw'] = _lst",
            "            self._raw_list_cache = {'src_id': _src_id, 'lst': _lst, 'shape': tuple(arr.shape), 'fs': float(payload.get('sfreq',0.0) or 0.0)}",
            "except Exception:",
            "    pass",
        ]
        in_ser = "\n        ".join(in_ser_lines)

        # Sorties → mapping + option MNE Raw
        out_map_lines = ["out_dict = {}", "import numpy as _np"]
        has_sfreq_input = any(p.name == "sfreq" for p in inputs)
        for p in outputs:
            n, t = p.name, p.dtype
            if t == "ndarray_2d":
                out_map_lines += [
                    f"if '{n}' in result and result['{n}'] is not None:",
                    f"    _arr = result['{n}']",
                    f"    if isinstance(_arr, list):",
                    f"        _C_N = _np.asarray(_arr, dtype=_np.float32)",
                    f"    else:",
                    f"        _C_N = _np.asarray(_arr, dtype=_np.float32)",
                    f"    out_dict['{n}'] = _C_N.T",
                ]
                if n == "raw":
                    out_map_lines += [
                        "    try:",
                        "        import mne",
                        f"        _fs = float(kwargs.get('sfreq', 0.0) or payload.get('sfreq', 0.0) or 0.0) if {str(has_sfreq_input)} else 0.0",
                        "        if _fs > 0:",
                        "            _C, _N = _C_N.shape[0], _C_N.shape[1]",
                        "            _ch_names = [f'ch{i}' for i in range(_C)]",
                        "            _info = mne.create_info(ch_names=_ch_names, sfreq=_fs, ch_types='eeg')",
                        "            out_dict['raw'] = mne.io.RawArray(_C_N, _info)",
                        "    except Exception:",
                        "        pass",
                    ]
            elif t in ("float","sfreq"):
                out_map_lines += [f"if '{n}' in result: out_dict['{n}'] = float(result['{n}'])"]
            elif t == "int":
                out_map_lines += [f"if '{n}' in result: out_dict['{n}'] = int(result['{n}'])"]
            elif t == "bool":
                out_map_lines += [f"if '{n}' in result: out_dict['{n}'] = bool(result['{n}'])"]
            elif t in ("str","path"):
                out_map_lines += [f"if '{n}' in result: out_dict['{n}'] = str(result['{n}'])"]
            else:
                out_map_lines += [f"if '{n}' in result: out_dict['{n}'] = result['{n}']"]
        out_map = "\n        ".join(out_map_lines)

        # ---- Template à jetons ----
        template = r'''
# Wrapper auto-généré (typed+UI) pour __DISPLAY_NAME__
# ✨ Pins d'E/S selon la déclaration
# ✨ Panneau de paramètres auto (build_widget)
# 🔒 N'exécute le binaire que quand les entrées requises sont présentes
# 🔁 Debounce 300 ms + recalcul auto à la volée
# ⚡ Prévisualisation (fenêtre + décimation)
# 🧠 Cache tolist() pour RAW inchangé
# 🚀 Modes: auto / inprocess (Python) / subprocess (stdio→fallback)

import os, sys, json, subprocess, threading, importlib
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

# ---- Définition des paramètres (déclaratif) ----
PARAM_DEFS = __PARAM_DEFS__

class __CLASS_NAME__Plugin(BasePlugin):
    name = "__DISPLAY_NAME__"
    language = "__LANGUAGE__"
    category = "Custom"
    executable = r"__SCRIPT_PATH__"
    exec_mode = "__EXEC_MODE__"   # "auto" | "inprocess" | "subprocess"

    def setup(self):
        __PIN_INPUTS__
        __PIN_OUTPUTS__
        self._param_widgets = {}
        self._param_values = {}
        self._raw_list_cache = {'src_id': None, 'lst': None, 'shape': None, 'fs': None}
        self._mne_cache = {}
        # debounce timer
        try:
            from PyQt5.QtCore import QTimer
            self._deb_timer = QTimer()
            self._deb_timer.setSingleShot(True)
            self._deb_timer.setInterval(300)
            self._deb_timer.timeout.connect(self._recompute_from_cache)
        except Exception:
            self._deb_timer = None
        # worker persistant (stdio)
        self._proc = None

    # ---------- modes ----------
    def _resolve_exec_mode(self):
        m = (self.exec_mode or "auto").strip().lower()
        if m == "auto":
            if (self.language == "Python") and str(self.executable).lower().endswith(".py"):
                return "inprocess"
            return "subprocess"
        return m

    # ---------- worker stdio ----------
    def _ensure_worker(self):
        if self._proc and self._proc.poll() is None:
            return
        try:
            self._proc = subprocess.Popen(
                [self.executable, "--stdio"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1
            )
        except Exception:
            self._proc = None

    def _kill_worker(self):
        try:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass
        self._proc = None

    def _readline_with_timeout(self, timeout_s: float):
        if not self._proc or not self._proc.stdout:
            return None
        out = {"line": None}
        def _target():
            try:
                out["line"] = self._proc.stdout.readline()
            except Exception:
                out["line"] = None
        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout_s)
        if t.is_alive():
            return None
        return out["line"]

    def _rpc_call(self, payload: dict, timeout_s: float = 2.0) -> dict:
        self._ensure_worker()
        if self._proc is None:
            raise RuntimeError("worker not available")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            self._proc.stdin.write(line); self._proc.stdin.flush()
        except Exception as e:
            raise RuntimeError(f"worker write failed: {e}")
        out_line = self._readline_with_timeout(timeout_s)
        if not out_line:
            raise TimeoutError("worker timeout / closed")
        try:
            return json.loads(out_line)
        except Exception as e:
            raise RuntimeError(f"invalid JSON from worker: {e}")

    # ---------- UI de paramètres ----------
    def build_widget(self):
        try:
            from PyQt5.QtWidgets import (
                QWidget, QVBoxLayout, QFormLayout, QDoubleSpinBox, QSpinBox,
                QCheckBox, QComboBox, QLineEdit, QToolButton, QSizePolicy
            )
            from PyQt5.QtCore import Qt
        except Exception:
            return None

        if getattr(self, "_param_widget_cached", None) is not None:
            return self._param_widget_cached

        root = QWidget()
        vbox = QVBoxLayout(root); vbox.setContentsMargins(0,0,0,0); vbox.setSpacing(0)

        header = QToolButton(root)
        header.setText("Paramètres"); header.setCheckable(True); header.setChecked(True)
        header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); header.setArrowType(Qt.DownArrow)
        header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vbox.addWidget(header)

        panel = QWidget(root)
        form = QFormLayout(panel); form.setContentsMargins(6,6,6,6); form.setSpacing(6)
        vbox.addWidget(panel)

        def _update_arrow(checked: bool):
            header.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            panel.setVisible(checked)
        header.toggled.connect(_update_arrow); _update_arrow(True)

        for d in (PARAM_DEFS or []):
            name = d.get("name","").strip()
            ptype = (d.get("type","float") or "float").strip().lower()
            tip = d.get("tooltip",""); unit = d.get("unit","")

            def _f(x, default=None):
                try: return float(x)
                except Exception: return default
            def _i(x, default=None):
                try: return int(float(x))
                except Exception: return default

            label_txt = name + (f" ({unit})" if unit else "")
            widget = None
            if ptype in ("float","sfreq"):
                from PyQt5.QtWidgets import QDoubleSpinBox
                sb = QDoubleSpinBox(panel); sb.setDecimals(4)
                mn = _f(d.get("min",""), 0.0); mx = _f(d.get("max",""), 1e9)
                st = _f(d.get("step",""), 0.1) or 0.1
                if isinstance(mn, float): sb.setMinimum(mn)
                if isinstance(mx, float): sb.setMaximum(mx)
                sb.setSingleStep(st); dv = _f(d.get("default",""), 0.0) or 0.0; sb.setValue(dv)
                widget = sb
            elif ptype == "int":
                from PyQt5.QtWidgets import QSpinBox
                sb = QSpinBox(panel)
                mn = _i(d.get("min",""), 0); mx = _i(d.get("max",""), 10**9)
                st = _i(d.get("step",""), 1) or 1
                sb.setMinimum(mn); sb.setMaximum(mx); sb.setSingleStep(st)
                dv = _i(d.get("default",""), 0) or 0; sb.setValue(dv)
                widget = sb
            elif ptype == "bool":
                from PyQt5.QtWidgets import QCheckBox
                cb = QCheckBox(panel)
                dv = str(d.get("default","")).strip().lower() in ("1","true","yes","on")
                cb.setChecked(dv); widget = cb
            elif ptype == "enum":
                from PyQt5.QtWidgets import QComboBox
                cb = QComboBox(panel)
                raw = d.get("choices","") or ""
                choices = [c.strip() for c in raw.split(",") if c.strip()] or ["off","on"]
                for c in choices: cb.addItem(c)
                dv = str(d.get("default","")).strip()
                if dv in choices: cb.setCurrentText(dv)
                widget = cb
            else:
                from PyQt5.QtWidgets import QLineEdit
                le = QLineEdit(panel); le.setText(str(d.get("default",""))); widget = le

            if tip:
                try: widget.setToolTip(tip)
                except Exception: pass

            self._param_widgets[name] = (ptype, widget, d)
            form.addRow(label_txt, widget)

            try:
                if hasattr(widget, "valueChanged"):
                    widget.valueChanged.connect(self._on_params_changed)
                elif hasattr(widget, "stateChanged"):
                    widget.stateChanged.connect(self._on_params_changed)
                elif hasattr(widget, "currentTextChanged"):
                    widget.currentTextChanged.connect(self._on_params_changed)
                elif hasattr(widget, "editingFinished"):
                    widget.editingFinished.connect(self._on_params_changed)
            except Exception:
                pass

        self._param_widget_cached = root
        self._param_panel = panel
        self._param_header = header
        return root

    # ---------- Config persistante ----------
    def export_config(self):
        params = self._gather_params_safe()
        return {"params": params}

    def import_config(self, cfg: dict):
        try:
            params = (cfg or {}).get("params", {})
            for k,(ptype, widget, d) in (self._param_widgets or {}).items():
                if k not in params: continue
                val = params.get(k)
                try:
                    if ptype in ("float","sfreq"):
                        widget.setValue(float(val))
                    elif ptype == "int":
                        widget.setValue(int(val))
                    elif ptype == "bool":
                        widget.setChecked(bool(val))
                    elif ptype == "enum":
                        widget.setCurrentText(str(val))
                    else:
                        widget.setText(str(val))
                except Exception:
                    pass
        except Exception:
            pass

    # ---------- Helpers params ----------
    def _gather_params_safe(self):
        out = {}
        for name,(ptype, widget, d) in (self._param_widgets or {}).items():
            try:
                if ptype in ("float","sfreq"):
                    out[name] = float(widget.value())
                elif ptype == "int":
                    out[name] = int(widget.value())
                elif ptype == "bool":
                    out[name] = bool(widget.isChecked())
                elif ptype == "enum":
                    out[name] = str(widget.currentText())
                else:
                    out[name] = str(widget.text())
            except Exception:
                pass
        return out

    # ---------- Commande ----------
    def _build_command(self, in_path, out_path):
        ext = os.path.splitext(self.executable)[1].lower()
        if ext in (".exe",""):     # Windows exe / binaire POSIX
            return [self.executable, "--in", in_path, "--out", out_path]
        if ext == ".js":  return ["node", self.executable, "--in", in_path, "--out", out_path]
        if ext == ".py":  return ["python", self.executable, "--in", in_path, "--out", out_path]
        if ext == ".r":   return ["Rscript", self.executable, in_path, out_path]
        if ext == ".jl":  return ["julia", self.executable, in_path, out_path]
        if ext == ".sh":  return ["bash", self.executable, "--in", in_path, "--out", out_path]
        if ext == ".m":   return ["octave", "--quiet", "--eval", "run('%s')" % self.executable]
        return [self.executable, "--in", in_path, "--out", out_path]

    # ---------- Relance auto quand un param change ----------
    def _have_all_required_inputs(self):
        try:
            vals = getattr(self, "_values", {}) or {}
            for name in (self.inputs or {}):
                if str(name).startswith("opt_"):
                    continue
                if vals.get(name, None) is None:
                    return False
            return True
        except Exception:
            return False

    def _recompute_from_cache(self):
        try:
            if not self._have_all_required_inputs():
                return
            vals = dict(getattr(self, "_values", {}) or {})
            result = self.execute(in_data=vals, **vals)
            if isinstance(result, dict):
                for k, subj in (self.outputs or {}).items():
                    if k in result:
                        subj.on_next(result[k])
        except Exception as e:
            print(f"[LowCode Wrapper] recompute error: {e}")

    def _on_params_changed(self, *args):
        try:
            if getattr(self, "_deb_timer", None) is not None:
                self._deb_timer.start()
            else:
                self._recompute_from_cache()
        except Exception:
            self._recompute_from_cache()

    # ---------- util inprocess (Python) ----------
    def _load_inproc_func(self):
        try:
            if not str(self.executable).lower().endswith(".py"):
                return None
            mod_dir = os.path.dirname(self.executable)
            mod_name = os.path.splitext(os.path.basename(self.executable))[0]
            if mod_dir and (mod_dir not in sys.path):
                sys.path.insert(0, mod_dir)
            mod = importlib.import_module(mod_name)
            mod = importlib.reload(mod)
            fn = getattr(mod, "process", None)
            return fn
        except Exception:
            return None

    # ---------- Exécution ----------
    def execute(self, **kwargs):
        # 0) paramètres UI
        params = self._gather_params_safe()
        mode = self._resolve_exec_mode()

        # 1) Construire payloads
        __IN_SER__

        # 1.b) fusion params
        try:
            payload.update(params or {})
            for k,v in (params or {}).items():
                if k not in payload_np:
                    payload_np[k] = v
        except Exception:
            pass

        # 1.c) Nyquist
        try:
            fs = float(kwargs.get("sfreq", 0.0) or payload.get("sfreq", 0.0) or payload_np.get("sfreq", 0.0) or 0.0)
            if fs > 0:
                nyq = max(0.0, fs*0.5 - 1e-6)
                if "low" in payload:
                    payload["low"] = max(0.01, min(float(payload["low"]), nyq))
                if "high" in payload:
                    payload["high"] = max(0.01, min(float(payload["high"]), nyq))
                if "low" in payload_np:
                    payload_np["low"] = max(0.01, min(float(payload_np["low"]), nyq))
                if "high" in payload_np:
                    payload_np["high"] = max(0.01, min(float(payload_np["high"]), nyq))
                if ("low" in payload) and ("high" in payload) and (payload["low"] >= payload["high"]):
                    payload["low"] = max(0.01, payload["high"]*0.5)
                if ("low" in payload_np) and ("high" in payload_np) and (payload_np["low"] >= payload_np["high"]):
                    payload_np["low"] = max(0.01, payload_np["high"]*0.5)
        except Exception:
            pass

        # 2) Exécution selon mode
        result = None
        if mode == "inprocess":
            fn = self._load_inproc_func()
            if fn is None:
                # Pas de process() -> bascule subprocess
                mode = "subprocess"
            else:
                try:
                    try:
                        result = fn(payload_np)      # def process(payload)
                    except TypeError:
                        result = fn(**payload_np)    # def process(**kwargs)
                except Exception as e:
                    raise RuntimeError(f"[LowCode InProcess] process() error: {e}")

        if result is None and mode == "subprocess":
            # stdio d'abord
            try:
                result = self._rpc_call(payload, timeout_s=3.0)
            except Exception:
                try:
                    self._kill_worker()
                    result = self._rpc_call(payload, timeout_s=3.0)
                except Exception:
                    result = None

        if result is None:
            # fallback fichiers
            os.makedirs("temp_io", exist_ok=True)
            in_path  = os.path.join("temp_io", "input___SLUG__.json")
            out_path = os.path.join("temp_io", "output___SLUG__.json")
            with open(in_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), ensure_ascii=False)
            cmd = self._build_command(in_path, out_path)
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                raise RuntimeError("[LowCode Wrapper] Subprocess error %d\nSTDERR:\n%s\nSTDOUT:\n%s" % (res.returncode, res.stderr, res.stdout))
            if not os.path.exists(out_path):
                raise RuntimeError("[LowCode Wrapper] Fichier sortie manquant: %s" % out_path)
            with open(out_path, "r", encoding="utf-8") as f:
                result = json.load(f)

        # 3) Mapper sortie -> pins
        __OUT_MAP__
        return out_dict

    def on_remove(self):
        try:
            self._kill_worker()
        except Exception:
            pass
'''
        wrapper = template.replace("__DISPLAY_NAME__", display_name)\
                          .replace("__CLASS_NAME__", class_name)\
                          .replace("__LANGUAGE__", language)\
                          .replace("__SCRIPT_PATH__", script_path_norm)\
                          .replace("__PIN_INPUTS__", _pin_decl(inputs, "inputs"))\
                          .replace("__PIN_OUTPUTS__", _pin_decl(outputs, "outputs"))\
                          .replace("__IN_SER__", in_ser)\
                          .replace("__OUT_MAP__", out_map)\
                          .replace("__SLUG__", slug)\
                          .replace("__EXEC_MODE__", exec_mode)\
                          .replace("__PARAM_DEFS__", param_defs_py)

        return dedent(wrapper)
