import sys
print(">>> main.py lancé")

def main():
    # Importé ici pour éviter que des objets Qt soient créés trop tôt
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)

    # Import maintenant, après QApplication
    from gui.main_window import MainWindow

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
