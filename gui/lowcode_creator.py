import os
import shutil
import json
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QComboBox, QFileDialog, QMessageBox, QApplication
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QClipboard

class LowCodeCreator(QWidget):
    def __init__(self, main_window=None):
        super().__init__()
        self.setWindowTitle("🧐 Création de Node")
        self.setMinimumWidth(600)
        self.main_window = main_window

        layout = QVBoxLayout()
        layout.setSpacing(10)

        self.name_input = QLineEdit()
        self.inputs_input = QLineEdit("1")
        self.outputs_input = QLineEdit("1")
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["Python", "R", "Julia", "NodeJS", "Shell", "Octave", "C", "C++", "Rust"])

        layout.addLayout(self._form_row("Nom du node", self.name_input))
        layout.addLayout(self._form_row("Nombre d'entrées", self.inputs_input))
        layout.addLayout(self._form_row("Nombre de sorties", self.outputs_input))
        layout.addLayout(self._form_row("Langage", self.lang_combo))

        btn_generate = QPushButton("🛠️ Générer et copier squelette")
        btn_load = QPushButton("📂 Choisir le fichier source")
        btn_add = QPushButton("➕ Ajouter à la palette")

        btn_generate.clicked.connect(self._generate_skeleton)
        btn_load.clicked.connect(self._load_script)
        btn_add.clicked.connect(self._add_to_palette)

        layout.addWidget(btn_generate)
        layout.addWidget(btn_load)
        layout.addWidget(btn_add)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(QLabel("Log / Info :"))
        layout.addWidget(self.log)

        self.setLayout(layout)

    def _form_row(self, label_text, widget):
        row = QHBoxLayout()
        label = QLabel(f"{label_text} :")
        label.setFixedWidth(150)
        row.addWidget(label)
        row.addWidget(widget)
        return row

    def _generate_skeleton(self):
        name = self.name_input.text().strip()
        n_inputs = int(self.inputs_input.text().strip())
        n_outputs = int(self.outputs_input.text().strip())
        lang = self.lang_combo.currentText()

        if not name:
            QMessageBox.warning(self, "Erreur", "Veuillez indiquer un nom.")
            return

        if lang == "Python":
            skeleton = self._generate_python_skeleton(name, n_inputs, n_outputs)
        else:
            skeleton = self._generate_polyglot_skeleton(name, lang)

        QApplication.clipboard().setText(skeleton)
        self.log.append(f"✅ Squelette généré pour {name} en {lang}.")
        self.log.append("📋 Copié dans le presse-papiers.")

    def _generate_python_skeleton(self, name, n_inputs, n_outputs):
        input_lines = "\n        ".join([f'self.inputs["input{i+1}"] = BehaviorSubject(None)' for i in range(n_inputs)])
        output_lines = "\n        ".join([f'self.outputs["output{i+1}"] = BehaviorSubject(None)' for i in range(n_outputs)])
        results = "\n        ".join([f'result["output{i+1}"] = None  # Remplacer' for i in range(n_outputs)])

        return f'''# custom_plugins/{name.lower()}_plugin.py
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class {name}Plugin(BasePlugin):
    name = "{name}"
    language = "Python"
    category = "Custom"

    def setup(self):
        {input_lines}
        {output_lines}

    def execute(self, **kwargs):
        # 💡 Implémentez ici votre logique
        result = {{}}
        {results}
        return result
'''

    def _generate_polyglot_skeleton(self, name, lang):
        input_file = f"temp_io/input_{name}.json"
        output_file = f"temp_io/output_{name}.json"
        templates = {
            "C": f"""// {name}.c – Compiler avec: gcc {name}.c -o {name}
#include <stdio.h>
#include <stdlib.h>

int main() {{
    // Lire input.json
    // TODO: logique de traitement
    // Écrire output.json
    return 0;
}}""",

            "C++": f"""// {name}.cpp – Compiler avec: g++ {name}.cpp -o {name}
#include <iostream>

int main() {{
    // Lire input.json
    // TODO: logique de traitement
    // Écrire output.json
    return 0;
}}""",

            "Rust": f"""use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::collections::HashMap;

fn main() {{
    let mut file = File::open("{input_file}").expect("Impossible d'ouvrir input");
    let mut contents = String::new();
    file.read_to_string(&mut contents).unwrap();

    let data: HashMap<String, i32> = serde_json::from_str(&contents).unwrap();
    let input1 = data.get("input1").unwrap();

    // 👉 Logique métier à compléter ici
    let output1 = input1 * 2;

    let mut file = File::create("{output_file}").unwrap();
    let result = serde_json::json!({{"output1": output1}});
    write!(file, "{{}}", result.to_string()).unwrap();
}}
""",

            "NodeJS": f"""const fs = require('fs');
const path = require('path');

const inputPath = path.join(__dirname, '..', '{input_file}');
const outputPath = path.join(__dirname, '..', '{output_file}');

const data = JSON.parse(fs.readFileSync(inputPath));

// 👉 Logique métier à compléter ici
const input1 = data.input1;
const output1 = input1 * 2; // exemple

fs.writeFileSync(outputPath, JSON.stringify({{ output1 }}));
""",

            "Shell": f"""#!/bin/bash
# {name}.sh
echo "🔧 Implémentez votre logique shell ici" """,

            "R": f"""#!/usr/bin/env Rscript
# {name}.R
cat("🔧 Implémentez votre logique R ici\\n")""",

            "Julia": f"""#!/usr/bin/env julia
# {name}.jl
println("🔧 Implémentez votre logique Julia ici")""",

            "Octave": f"""#!/usr/bin/env octave
% {name}.m
disp("🔧 Implémentez votre logique Octave ici");""",

            
        }

        return templates.get(lang, f"// Langage {lang} non pris en charge")

    def _load_script(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier script", "", "Tous (*.*)")
        if filepath:
            self.selected_file = filepath
            self.log.append(f"📂 Fichier sélectionné : {filepath}")

    def _add_to_palette(self):
        if not hasattr(self, "selected_file"):
            QMessageBox.warning(self, "Erreur", "Veuillez d’abord charger un script.")
            return

        name = self.name_input.text().strip()
        lang = self.lang_combo.currentText()
        if not name:
            QMessageBox.warning(self, "Erreur", "Veuillez spécifier un nom.")
            return

        dest_script_dir = os.path.join("custom_plugins", "external_scripts")
        os.makedirs(dest_script_dir, exist_ok=True)
        script_name = os.path.basename(self.selected_file)
        dest_script_path = os.path.join(dest_script_dir, script_name)
        shutil.copy(self.selected_file, dest_script_path)

        # ✅ Génération du wrapper Python
        wrapper_code = self._generate_wrapper_code(name, dest_script_path)
        wrapper_path = os.path.join("custom_plugins", f"{name.lower()}_plugin.py")
        with open(wrapper_path, "w", encoding="utf-8") as f:
            f.write(wrapper_code)

        self.log.append(f"📦 Wrapper Python généré : {wrapper_path}")
        self.log.append(f"✅ Script externe copié : {dest_script_path}")

        try:
            from importlib import import_module
            module = import_module(f"custom_plugins.{name.lower()}_plugin")
            plugin_class = getattr(module, f"{name}Plugin")
            if self.main_window:
                self.main_window.add_plugin_to_palette("Custom", plugin_class)
            self.log.append("🎉 Plugin ajouté dynamiquement à la palette.")
        except Exception as e:
            self.log.append(f"[ERREUR] Ajout échoué : {e}")

    def _generate_wrapper_code(self, name, script_path):
        script_path = script_path.replace("\\", "/")
        return f'''# Wrapper auto-généré pour {name}
import os
import subprocess
import json
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class {name}Plugin(BasePlugin):
    name = "{name}"
    language = "external"
    category = "Custom"
    executable = r"{script_path}"

    def setup(self):
        self.inputs["input1"] = BehaviorSubject(None)
        self.outputs["output1"] = BehaviorSubject(None)

    def _build_command(self):
        ext = os.path.splitext(self.executable)[1].lower()
        if ext == ".js":
            return ["node", self.executable]
        elif ext == ".sh":
            return ["bash", self.executable]
        elif ext == ".py":
            return ["python", self.executable]
        elif ext == ".r":
            return ["Rscript", self.executable]
        
        elif ext == ".m":
            return ["octave", "--quiet", "--eval", f"run('{{self.executable}}')"]
        elif ext == ".jl":
            return ["julia", self.executable]          
        elif ext in [".exe"]:
            return [self.executable]
        else:
            raise Exception("Type de script non pris en charge.")

    def execute(self, **kwargs):
        try:
            temp_dir = "temp_io"
            os.makedirs(temp_dir, exist_ok=True)
            input_path = os.path.join(temp_dir, f"input_{name}.json")
            output_path = os.path.join(temp_dir, f"output_{name}.json")
            
            
            os.makedirs(temp_dir, exist_ok=True)

            with open(input_path, "w") as f:
                json.dump(kwargs, f)

            cmd = self._build_command()
            subprocess.run(cmd, check=True)

            with open(output_path, "r") as f:
                result = json.load(f)

            # (facultatif mais conseillé)
            #if os.path.exists(input_path): os.remove(input_path)
            #if os.path.exists(output_path): os.remove(output_path)

            return result
        except Exception as e:
            print(f"[ERREUR] Subprocess échoué: {'{e}'}")
            return {{}}
'''
