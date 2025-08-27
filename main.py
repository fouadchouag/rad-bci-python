# main.py
from core.version import __version__

import sys
print(">>> main.py lancé")

def main():
    # 1) App Qt
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # 2) Fenêtre principale
    from gui.main_window import MainWindow
    window = MainWindow()
    window.show()
    window.setWindowTitle(f"RBciAD {__version__} – Reactive BCI Builder")

    # 3) Installer les hotkeys F9/F10 pour les métriques (aucun fichier créé tant qu'on n'appuie pas)
    try:
        from core.metrics_hotkeys import install_global_metrics_hotkeys
        install_global_metrics_hotkeys(app_name="RBciAD", out_dir="runs")
        print("[metrics] Hotkeys installés : F9=Start/Stop, F10=Stop forcé")
    except Exception as e:
        print(f"[metrics] hotkeys non installés ({e})")

    # 4) Arrêt propre des métriques (seulement si actives) quand l'app se ferme
    def _shutdown_metrics():
        try:
            from core.metrics_logger import metrics, deinit_metrics_logger, is_active
            if is_active():
                try:
                    metrics().event("APP_EXIT")
                except Exception:
                    pass
                deinit_metrics_logger()
        except Exception:
            pass

    try:
        app.aboutToQuit.connect(_shutdown_metrics)
    except Exception:
        pass

    # 5) Plus de run_meta au démarrage : ce sera géré automatiquement à F9 (voir init_metrics_logger)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
