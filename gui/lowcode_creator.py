import os
import uuid
from PyQt5.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QComboBox, QPushButton, QTextEdit, QLabel, QFileDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QClipboard

class LowCodeCreatorWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🧠 Création de Node Polyglotte")
        self.resize(500, 450)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        self.name_input = QLineEdit()
        self.inputs_spin = QSpinBox(); self.inputs_spin.setRange(0, 10)
        self.outputs_spin = QSpinBox(); self.outputs_spin.setRange(0, 10)
        self.language_combo = QComboBox()
        self.language_combo.addItems(["Python", "Bash", "R", "Julia", "C", "C++", "NodeJS", "Rust"])

        form_layout.addRow("🔤 Nom du Node :", self.name_input)
        form_layout.addRow("🔢 Nombre d'Entrées :", self.inputs_spin)
        form_layout.addRow("🔢 Nombre de Sorties :", self.outputs_spin)
        form_layout.addRow("🌐 Langage :", self.language_combo)

        layout.addLayout(form_layout)

        self.copy_skeleton_btn = QPushButton("📋 Copier le Squelette")
        self.choose_file_btn = QPushButton("📂 Choisir le fichier source")
        self.add_to_palette_btn = QPushButton("➕ Ajouter à la palette")

        layout.addWidget(self.copy_skeleton_btn)
        layout.addWidget(self.choose_file_btn)
        layout.addWidget(self.add_to_palette_btn)

        self.info_log = QTextEdit()
        self.info_log.setReadOnly(True)
        layout.addWidget(QLabel("📋 Log / Instructions :"))
        layout.addWidget(self.info_log)

        self.setLayout(layout)

        self.copy_skeleton_btn.clicked.connect(self.copy_skeleton)
        self.choose_file_btn.clicked.connect(self.choose_file)
        self.add_to_palette_btn.clicked.connect(self.add_to_palette)

    def copy_skeleton(self):
        name = self.name_input.text().strip() or "MyNode"
        lang = self.language_combo.currentText().lower()
        inputs = self.inputs_spin.value()
        outputs = self.outputs_spin.value()

        code = f'''"""
Plugin : {name}
Langage : {lang}
Instructions :
- Collez ce squelette dans votre IDE.
- Complétez la fonction `execute` selon la logique de votre node.
- Placez ensuite le fichier dans plugins/ ou chargez-le via le bouton 'Choisir le fichier source'.
"""

from core.reactive_node import ReactiveNode

class {name}Plugin(ReactiveNode):
    def __init__(self):
        super().__init__(name="{name}")
        self.language = "{lang}"
        self.add_inputs({[f"input{i}" for i in range(inputs)]})
        self.add_outputs({[f"output{i}" for i in range(outputs)]})

    def execute(self, *args):
        # TODO : Implémentez la logique ici
        result = ...  # votre traitement
        self.emit('output0', result)  # Exemple
'''

        QApplication.clipboard().setText(code)
        self.info_log.append("✅ Squelette copié dans le presse-papiers. Collez-le dans votre IDE, complétez-le, puis chargez-le avec le bouton ci-dessous.")

    def choose_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier source", "", "Fichiers Python (*.py);;Tous les fichiers (*)")
        if file_name:
            self.selected_file = file_name
            self.info_log.append(f"📂 Fichier sélectionné : {file_name}")

    def add_to_palette(self):
        if hasattr(self, "selected_file"):
            self.info_log.append("✅ Ajout du fichier à la palette (à implémenter)")
            # TODO : Import dynamique ou reload
        else:
            self.info_log.append("❌ Aucun fichier source sélectionné.")

# Test manuel
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = LowCodeCreatorWindow()
    window.show()
    sys.exit(app.exec_())
