# gui/main_window.py
# -*- coding: utf-8 -*-

from contextlib import contextmanager

# Support SVG optionnel
try:
    from PyQt5.QtSvg import QSvgGenerator
    _HAVE_SVG = True
except Exception:
    QSvgGenerator = None
    _HAVE_SVG = False

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsView, QGraphicsScene, QLabel, QScrollArea, QFrame,
    QGraphicsPathItem, QFileDialog, QAction, QMessageBox,
    QDialog, QListWidget, QDialogButtonBox, QSplitter
)
from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, QSizeF, QSize, QMarginsF, QThread, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QKeySequence, QTransform, QMouseEvent, QImage, QPdfWriter
import sip

import json
import re
from json import JSONDecodeError
from pathlib import Path
import numpy as np
import os
import logging

from core.plugin_registry import discover_plugins
from .node_item import NodeItem, LANG_BADGE, BADGE_SCALE
from gui.lowcode_creator import LowCodeCreator
from .connection_item import ConnectionItem

# ✅ perf
try:
    from core.rt_perf import init_fast_defaults
except Exception:
    def init_fast_defaults(*_a, **_k): pass

# Templates
try:
    from .workflow_templates import TEMPLATES, instantiate_template
except Exception:
    try:
        from workflow_templates import TEMPLATES, instantiate_template
    except Exception:
        TEMPLATES = {}
        def instantiate_template(*_a, **_k):
            raise RuntimeError("workflow_templates.py manquant (placez-le dans gui/ ou à la racine).")

# 🔹 Console de logs
try:
    from gui.log_console import LogConsoleDock
except Exception:
    LogConsoleDock = None


# ------------------------------------------------------------
# ZoomableGraphicsView : molette (Ctrl), pan (molette/space),
# boutons +/−/100%/Fit, raccourcis : Ctrl+=, Ctrl+-, Ctrl+0, Ctrl+F
# ------------------------------------------------------------
class ZoomableGraphicsView(QGraphicsView):
    def __init__(self, scene=None, parent=None):
        super().__init__(scene, parent)

        self._min_scale = 0.1
        self._max_scale = 8.0
        self._zoom_step = 1.25  # facteur par cran
        self._space_drag = False

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)

    # --- API publique pour MainWindow ---
    def set_zoom_limits(self, min_scale: float = 0.1, max_scale: float = 8.0):
        self._min_scale = float(min_scale)
        self._max_scale = float(max_scale)

    def zoom_in(self):
        self._apply_scale(self._zoom_step)

    def zoom_out(self):
        self._apply_scale(1.0 / self._zoom_step)

    def zoom_reset(self):
        self.setTransform(Qtransform())  # remet à 100%
        self.setTransform(QTransform())

    def fit_to_scene(self, margin: float = 40.0):
        sc = self.scene()
        if sc is None:
            return
        rect = sc.itemsBoundingRect() if sc.items() else sc.sceneRect()
        if rect.isNull() or not rect.isValid():
            rect = QRectF(0, 0, 100, 100)
        r = QRectF(rect)
        r.adjust(-margin, -margin, margin, margin)
        if r.width() <= 0 or r.height() <= 0:
            return
        self.setTransform(QTransform())
        try:
            self.fitInView(r, Qt.KeepAspectRatio)
        except Exception:
            pass

    # --- évènements ---
    def wheelEvent(self, event):
        # Zoom si Ctrl enfoncé, sinon comportement standard (scroll)
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                return
            factor = self._zoom_step if delta > 0 else (1.0 / self._zoom_step)
            self._apply_scale(factor)
            event.accept()
        else:
            super().wheelEvent(event)

    def _apply_scale(self, factor: float):
        t = self.transform()
        sx = t.m11()
        new_sx = sx * factor
        if new_sx < self._min_scale:
            factor = self._min_scale / max(sx, 1e-12)
        elif new_sx > self._max_scale:
            factor = self._max_scale / max(sx, 1e-12)
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent):
        # Pan au bouton du milieu
        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            fake = QMouseEvent(QMouseEvent.MouseButtonPress, event.localPos(), Qt.LeftButton,
                               Qt.LeftButton, event.modifiers())
            super().mousePressEvent(fake)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton and self.dragMode() == QGraphicsView.ScrollHandDrag:
            fake = QMouseEvent(QMouseEvent.MouseButtonRelease, event.localPos(), Qt.LeftButton,
                               Qt.NoButton, event.modifiers())
            super().mouseReleaseEvent(fake)
            self.setDragMode(QGraphicsView.NoDrag)
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        # Espace = pan temporaire
        if event.key() == Qt.Key_Space and not self._space_drag:
            self._space_drag = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and self._space_drag:
            self._space_drag = False
            self.setDragMode(QGraphicsView.NoDrag)
            return
        super().keyReleaseEvent(event)


# ---------- petit worker Qt pour découvrir les plugins en arrière-plan ----------
class _PluginLoader(QObject):
    finished = pyqtSignal(dict)
    def run(self):
        try:
            res = discover_plugins() or {}
        except Exception:
            res = {}
        self.finished.emit(res)


class MainWindow(QMainWindow):
    # -------------------------- Synonymes de pins --------------------------
    PIN_SYNONYMS = {
        "raw":        ["data", "eeg", "Raw", "X"],
        "sfreq":      ["fs", "Fs", "sampling_rate", "sample_rate", "sf"],
        "ch_names":   ["channels", "ch", "chan_names", "labels", "names"],
        "segment":    ["segments", "window", "trial", "epoch", "sample"],
        "label":      ["labels", "y", "target", "class"],
        "features":   ["feature", "X", "x", "vec", "embedding"],
        "model":      ["clf", "classifier", "estimator"],
        "cov":        ["covariance", "C"],
        "feature_transform": ["transform", "feat_transform", "csp"],
        "ts_transform":      ["transform", "tspace", "tangent", "feat_transform"],
    }

    def __init__(self):
        super().__init__()

        # ✅ BLAS
        try:
            init_fast_defaults(blas_threads=1)
        except Exception:
            pass

        self.setWindowTitle("RBciAD – Reactive BCI Builder")
        self.setGeometry(100, 100, 1200, 800)

        self._closing = False

        # --- Scene / View ---------------------------------------------------
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 3000, 3000)
        try:
            self.scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        except Exception:
            pass

        self.view = ZoomableGraphicsView(self.scene, parent=self)
        self.view.centerOn(0, 0)
        self.view.set_zoom_limits(0.08, 8.0)

        # ⚙️ Réglages anti-traînées
        self.view.setViewport(QWidget(self.view))  # QWidget standard
        self.view.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.view.setCacheMode(QGraphicsView.CacheNone)
        self.view.setBackgroundBrush(QColor(255, 255, 255))
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.view.setRenderHints(QPainter.Antialiasing |
                                 QPainter.TextAntialiasing |
                                 QPainter.SmoothPixmapTransform)

        # Z-order
        self._z_counter = 0
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)

        # ⚠️ Plugins: NE PAS bloquer ici. On initialise vide et on chargera en arrière-plan.
        self.plugins_by_category = {}
        self.plugin_classes_by_name = {}
        self.all_plugins = []

        # Logs UI
        self.log_dock = None
        self.logger = logging.getLogger("RBciAD")
        self.logger.setLevel(logging.DEBUG)
        if LogConsoleDock is not None:
            try:
                self.log_dock = LogConsoleDock(self, title="Console (logs)")
                self.log_dock.attach_logger(name="RBciAD", level=logging.INFO)
            except Exception:
                self.log_dock = None

        self._init_ui()
        self.category_widgets = {}
        self.current_workflow_path = None

        # 🎯 Afficher immédiatement "Plugin loading…" puis lancer la découverte en arrière-plan
        self._show_plugin_loading_message()
        self._start_plugin_discovery_async()

        # Hotkeys métriques
        try:
            from core.metrics_hotkeys import install_global_metrics_hotkeys
            install_global_metrics_hotkeys(app_name="RBciAD", out_dir="runs")
            self.logger.info("[metrics] Hotkeys installés : F9=Start/Stop, F10=Stop forcé")
        except Exception as e:
            self.logger.warning(f"[metrics] hotkeys non installés ({e})")

        # Raccourcis zoom + Export
        self._install_zoom_shortcuts()

        # Autosave toutes les 2 minutes
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._autosave_timer.start(120000)

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _init_ui(self):
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

        # Toolbar
        toolbar = QHBoxLayout()
        btn_new = QPushButton("🆕 Nouveau")
        btn_load = QPushButton("📂 Charger")
        btn_save = QPushButton("💾 Sauvegarder")
        btn_save_as = QPushButton("💾 Enregistrer sous...")
        btn_lowcode = QPushButton("🛠️ Dev Mode (➕ Ajouter un Node)")

        btn_logs = QPushButton("🪵 Logs")
        btn_logs.setCheckable(True)
        if self.log_dock is not None:
            btn_logs.toggled.connect(lambda vis: self.log_dock.setVisible(vis))

        for btn in [btn_new, btn_load, btn_save, btn_save_as, btn_lowcode, btn_logs]:
            btn.setMinimumHeight(40)
            btn.setStyleSheet("font-weight: bold; font-size: 14px;")
            toolbar.addWidget(btn)

        # --- Contrôles Zoom ---
        btn_zoom_out = QPushButton("−")
        btn_zoom_in = QPushButton("+")
        btn_zoom_100 = QPushButton("100%")
        btn_zoom_fit = QPushButton("Fit")
        btn_export = QPushButton("🖼️ Export PNG/PDF/SVG")

        for b in (btn_zoom_out, btn_zoom_in, btn_zoom_100, btn_zoom_fit, btn_export):
            b.setMinimumHeight(40)
            b.setStyleSheet("font-weight: bold; font-size: 16px;")
            toolbar.addWidget(b)

        btn_zoom_out.clicked.connect(self.view.zoom_out)
        btn_zoom_in.clicked.connect(self.view.zoom_in)
        btn_zoom_100.clicked.connect(self.view.zoom_reset)
        btn_zoom_fit.clicked.connect(self.view.fit_to_scene)
        btn_export.clicked.connect(lambda: self._export_scene_any(
            selected_only=False, margin_px=16, dpi=300, transparent_png=False
        ))

        toolbar_widget = QWidget()
        toolbar_widget.setLayout(toolbar)
        toolbar_widget.setFixedHeight(60)
        main_layout.addWidget(toolbar_widget)

        # --- Palette (gauche) + Éditeur (centre) ---
        self.palette_frame = QFrame()
        self.palette_layout = QVBoxLayout(self.palette_frame)
        self.palette_frame.setLayout(self.palette_layout)

        # Label de chargement (immédiat)
        self._loading_label = QLabel("Plugin loading…")
        self._loading_label.setStyleSheet("color: #666; margin: 8px;")
        self.palette_layout.addWidget(self._loading_label)
        self.palette_layout.addStretch(1)

        palette_scroll = QScrollArea()
        palette_scroll.setWidgetResizable(True)
        palette_scroll.setWidget(self.palette_frame)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.addWidget(palette_scroll)
        self.splitter.addWidget(self.view)
        self.palette_frame.setMinimumWidth(160)
        self.splitter.setSizes([240, 960])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.splitter, stretch=1)

        # Fichier courant
        self.workflow_label = QLabel("🗂️ Aucun fichier")
        self.workflow_label.setStyleSheet("font-style: italic; color: gray; margin-left: 8px;")
        main_layout.addWidget(self.workflow_label)

        # Connexions
        btn_new.clicked.connect(self._action_new_workflow_from_template)
        btn_load.clicked.connect(self._load_workflow)
        btn_save.clicked.connect(self._save_workflow)
        btn_lowcode.clicked.connect(self._show_lowcode_creator)
        btn_save_as.clicked.connect(self._save_workflow_as)

        # Dock logs
        if self.log_dock is not None:
            try:
                self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
                self.log_dock.hide()
                self.log_dock.visibilityChanged.connect(lambda vis: btn_logs.setChecked(vis))
                self.logger.info("Console de logs initialisée.")
            except Exception as e:
                self.logger.error(f"Erreur ajout dock logs: {e}")

    def _install_zoom_shortcuts(self):
        acts = []
        acts.append(QAction("Zoom In", self, shortcut=QKeySequence("Ctrl++"), triggered=self.view.zoom_in))
        acts.append(QAction("Zoom In (Alt)", self, shortcut=QKeySequence("Ctrl+="), triggered=self.view.zoom_in))
        acts.append(QAction("Zoom Out", self, shortcut=QKeySequence("Ctrl+-"), triggered=self.view.zoom_out))
        acts.append(QAction("Reset Zoom", self, shortcut=QKeySequence("Ctrl+0"), triggered=self.view.zoom_reset))
        acts.append(QAction("Fit to Scene", self, shortcut=QKeySequence("Ctrl+F"), triggered=self.view.fit_to_scene))
        acts.append(QAction("Export Workflow", self, shortcut=QKeySequence("Ctrl+E"),
                            triggered=lambda: self._export_scene_any(
                                selected_only=False, margin_px=16, dpi=300, transparent_png=False
                            )))
        for a in acts:
            self.addAction(a)

    def closeEvent(self, ev):
        self._closing = True
        try:
            self.scene.selectionChanged.disconnect(self._on_scene_selection_changed)
        except Exception:
            pass
        return super().closeEvent(ev)

    # ---------- async plugin loading ----------
    def _show_plugin_loading_message(self):
        # déjà ajouté dans _init_ui, mais au cas où
        if not hasattr(self, "_loading_label") or self._loading_label is None:
            self._loading_label = QLabel("Plugin loading…")
            self._loading_label.setStyleSheet("color: #666; margin: 8px;")
            self.palette_layout.insertWidget(0, self._loading_label)

    def _start_plugin_discovery_async(self):
        self._plugin_thread = QThread(self)
        self._plugin_worker = _PluginLoader()
        self._plugin_worker.moveToThread(self._plugin_thread)
        self._plugin_thread.started.connect(self._plugin_worker.run)
        self._plugin_worker.finished.connect(self._on_plugins_loaded)
        self._plugin_worker.finished.connect(self._plugin_thread.quit)
        self._plugin_worker.finished.connect(self._plugin_worker.deleteLater)
        self._plugin_thread.finished.connect(self._plugin_thread.deleteLater)
        self._plugin_thread.start()

    def _on_plugins_loaded(self, plugins_by_category: dict):
        self.plugins_by_category = plugins_by_category or {}
        self.plugin_classes_by_name = {}

        # Liste à plat des plugins
        self.all_plugins = []
        for plugin_list in self.plugins_by_category.values():
            self.all_plugins.extend(plugin_list)

        self.logger.info("📦 Plugins chargés dans all_plugins :")
        for cls in self.all_plugins:
            self.logger.info(f"   - {cls.__name__}")

        # Construire la palette (et retirer le label de chargement)
        self._populate_palette()

    # ---------- Helpers langage (palette) ----------
    def _canon_language(self, s: str) -> str:
        s = (s or "").strip().lower()
        if s in ("py", "python"): return "Python"
        if s in ("rs", "rust"): return "Rust"
        if s in ("js", "node", "nodejs", "node.js", "javascript"): return "Node.js"
        if s in ("c++", "cpp"): return "C++"
        if s in ("jl", "julia"): return "Julia"
        if s in ("r", "r-lang", "rscript"): return "R"
        if s in ("sh", "bash", "shell"): return "Shell"
        if s in ("go", "golang"): return "Go"
        if s in ("c",): return "C"
        return s.capitalize()

    def _detect_language_from_class(self, plugin_class):
        lang = getattr(plugin_class, "language", None) or getattr(plugin_class, "lang", None)
        if isinstance(lang, str) and lang.strip():
            return self._canon_language(lang)

        cname = plugin_class.__name__.lower()
        mod   = getattr(plugin_class, "__module__", "").lower()
        hint  = " ".join([cname, mod])
        if any(k in hint for k in ["rust", "cargo"]): return "Rust"
        if any(k in hint for k in ["node", "node.js", "javascript"]): return "Node.js"
        if any(k in hint for k in ["cpp", "c++"]): return "C++"
        if "julia" in hint: return "Julia"
        if "rscript" in hint or cname.endswith("r"): return "R"
        return "Python"

    # ---------- Widget ligne palette avec badge ----------
    def _make_palette_row(self, plugin_class):
        row = QWidget(self.palette_frame)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(8, 4, 8, 4)
        spacing_base = 8
        hl.setSpacing(max(4, int(round(spacing_base * BADGE_SCALE))))

        name = getattr(plugin_class, "name", plugin_class.__name__)
        lang = self._detect_language_from_class(plugin_class)
        code, color = LANG_BADGE.get(lang, (lang.upper()[:2], QColor(40, 120, 200)))

        btn = QPushButton(name, row)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet("""
            QPushButton { text-align: left; color: #222; background: transparent; border: none; }
            QPushButton:hover { color: #000; }
        """)
        btn.clicked.connect(lambda _, cls=plugin_class: self._add_node(cls))

        base_font_px  = 11
        base_pad_x_px = 6
        base_pad_y_px = 2
        base_radius   = 7

        font_px  = max(8, int(round(base_font_px  * BADGE_SCALE)))
        pad_x_px = max(3, int(round(base_pad_x_px * BADGE_SCALE)))
        pad_y_px = max(1, int(round(base_pad_y_px * BADGE_SCALE)))
        radius   = max(5, int(round(base_radius   * BADGE_SCALE)))

        badge = QLabel(code, row)
        badge.setStyleSheet(f"""
            QLabel {{
                color: white;
                background-color: rgba({color.red()},{color.green()},{color.blue()},255);
                border-radius: {radius}px;
                padding: {pad_y_px}px {pad_x_px}px;
                font-weight: bold;
                font-size: {font_px}px;
            }}
        """)

        hl.addWidget(btn, 1, Qt.AlignVCenter)
        hl.addWidget(badge, 0, Qt.AlignRight | Qt.AlignVCenter)
        return row

    def _populate_palette(self):
        # ⚠️ NE pas redécouvrir si déjà fournis par le worker
        if not self.plugins_by_category:
            self.plugins_by_category = discover_plugins()

        self.plugin_classes_by_name = {}
        self._normalize_plugin_languages()

        self.logger.info("📦 Plugins détectés :")
        for cat, plugins in self.plugins_by_category.items():
            self.logger.info(f"  📁 {cat} : {[cls.__name__ for cls in plugins]}")

        # Nettoyer la palette (retire aussi le label "Plugin loading…")
        for i in reversed(range(self.palette_layout.count())):
            widget = self.palette_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Reconstruire la palette + registre
        for category, plugin_list in self.plugins_by_category.items():
            cat_label = QLabel(f"📁 {category}")
            cat_label.setStyleSheet("font-weight: bold; margin-top: 10px; color: #222;")
            self.palette_layout.addWidget(cat_label)

            container = QWidget(self.palette_frame)
            v = QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            self.palette_layout.addWidget(container)
            self.category_widgets[category] = v

            for plugin_class in plugin_list:
                self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
                try:
                    self.plugin_classes_by_name[plugin_class.name] = plugin_class
                except Exception:
                    pass

                row = self._make_palette_row(plugin_class)
                v.addWidget(row)

        self.palette_layout.addStretch(1)

    def add_plugin_to_palette(self, category, plugin_class):
        if category not in self.category_widgets:
            label = QLabel(f"📁 {category}")
            label.setStyleSheet("font-weight: bold; margin-top: 10px; color: #222;")
            self.palette_layout.addWidget(label)

            container = QWidget(self.palette_frame)
            v = QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            self.palette_layout.addWidget(container)

            self.category_widgets[category] = v

        v = self.category_widgets[category]
        row = self._make_palette_row(plugin_class)
        v.addWidget(row)

        self.plugin_classes_by_name[plugin_class.__name__] = plugin_class
        try:
            self.plugin_classes_by_name[plugin_class.name] = plugin_class
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # Z-order helpers
    # ---------------------------------------------------------------------
    def _raise_node(self, node_item: NodeItem):
        try:
            self._z_counter += 1
            node_item.setZValue(self._z_counter)
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ raise_node: {e}")

    def _on_scene_selection_changed(self):
        if self._closing:
            return
        scene = getattr(self, "scene", None)
        if scene is None or sip.isdeleted(scene):
            return
        try:
            items = scene.selectedItems()
        except RuntimeError:
            return
        for item in items:
            if isinstance(item, NodeItem):
                self._raise_node(item)

    # ---------------------------------------------------------------------
    # Création / Connexions de nœuds
    # ---------------------------------------------------------------------
    def _add_node(self, plugin_class):
        try:
            self.logger.info(f">>> Ajout du nœud : {plugin_class.name}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(200, 200)
            self.scene.addItem(node_item)
            self._raise_node(node_item)
            self.view.centerOn(node_item)
            self.view.viewport().update()
        except Exception as e:
            self.logger.error(f"[ERROR] Failed to create node: {e}")

    def add_node_at(self, plugin_class, pos: QPointF):
        try:
            self.logger.info(f">>> Ajout du nœud : {plugin_class.name} @ {pos.x():.0f},{pos.y():.0f}")
            node_item = NodeItem(plugin_class)
            node_item.setPos(pos)
            self.scene.addItem(node_item)
            self._raise_node(node_item)
            self.view.centerOn(node_item)
            self.view.viewport().update()
            return node_item
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ add_node_at({plugin_class}): {e}")
            return None

    # ---------------- Connexion tolérante par nom de pin -------------------
    def _list_pin_names(self, node_item, is_output):
        names = []
        try:
            d = node_item.output_pins if is_output else node_item.input_pins
            if isinstance(d, list):
                names.extend([p.name for p in d if hasattr(p, "name")])
        except Exception:
            pass
        try:
            getter = node_item.get_output_pin_names if is_output else node_item.get_input_pin_names
            names.extend(list(getter()))
        except Exception:
            pass
        return sorted(set(str(n) for n in names))

    def _resolve_pin(self, node_item, wanted_name, is_output):
        wanted_name = str(wanted_name)
        get = node_item.get_output_pin_by_name if is_output else node_item.get_input_pin_by_name

        # exact
        pin = get(wanted_name)
        if pin:
            return pin

        # case-insensitive
        names = self._list_pin_names(node_item, is_output)
        for n in names:
            if n.lower() == wanted_name.lower():
                return get(n)

        # synonymes
        syns = self.PIN_SYNONYMS.get(wanted_name.lower(), [])
        for syn in syns:
            pin = get(syn)
            if pin:
                return pin
            for n in names:
                if n.lower() == syn.lower():
                    return get(n)

        return None

    def connect_by_name(self, src_node_item, src_pin_name: str, dst_node_item, dst_pin_name: str) -> bool:
        try:
            out_pin = self._resolve_pin(src_node_item, src_pin_name, True)
            in_pin  = self._resolve_pin(dst_node_item, dst_pin_name, False)

            if not out_pin or not in_pin:
                out_names = self._list_pin_names(src_node_item, True)
                in_names  = self._list_pin_names(dst_node_item, False)
                self.logger.error(f"[Templates] ❌ Échec connexion {src_node_item.plugin.name}.{src_pin_name} → "
                                  f"{dst_node_item.plugin.name}.{dst_pin_name}")
                self.logger.error(f"           ├─ sorties dispo: {out_names}")
                self.logger.error(f"           └─ entrées  dispo: {in_names}")
                return False

            conn_item = ConnectionItem(out_pin, in_pin)
            try:
                if conn_item.scene() is None:
                    self.scene.addItem(conn_item)
            except Exception:
                pass

            try:
                conn_item.track_both_pins()
                conn_item.setZValue(-1000)
            except Exception:
                pass

            try:
                out_pin.set_connected(True)
                in_pin.set_connected(True)
            except Exception:
                pass

            self.view.viewport().update()
            self.logger.info(f"✅ Connecté: {src_node_item.plugin.name}.{out_pin.name} → {dst_node_item.plugin.name}.{in_pin.name}")
            return True
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ connect_by_name: {e}")
            return False

    # ---------------------------------------------------------------------
    # Événements / suppression
    # ---------------------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            for item in self.scene.selectedItems():
                if hasattr(item, "plugin"):
                    # connexions
                    to_remove = []
                    for obj in self.scene.items():
                        if isinstance(obj, QGraphicsPathItem) and hasattr(obj, "output_pin") and hasattr(obj, "input_pin"):
                            if obj.output_pin.node == item or obj.input_pin.node == item:
                                to_remove.append(obj)

                    for conn in to_remove:
                        if hasattr(conn, "cleanup"):
                            conn.cleanup()
                            if hasattr(conn, "input_pin") and conn.input_pin and hasattr(conn.input_pin, "node"):
                                input_node = conn.input_pin.node
                                if hasattr(input_node, "plugin"):
                                    input_node.plugin.set_input(conn.input_pin.name, None)
                        self.scene.removeItem(conn)

                    # nœud
                    item.plugin.cleanup()
                    self.scene.removeItem(item)

                elif isinstance(item, QGraphicsPathItem):
                    if hasattr(item, "cleanup"):
                        item.cleanup()
                        if hasattr(item, "input_pin") and item.input_pin and hasattr(item.input_pin, "node"):
                            input_node = item.input_pin.node
                            if hasattr(input_node, "plugin"):
                                input_node.plugin.set_input(item.input_pin.name, None)
                    self.scene.removeItem(item)

            self.view.viewport().update()
        else:
            super().keyPressEvent(event)

    # ---------------------------------------------------------------------
    # Workflows
    # ---------------------------------------------------------------------
    def _clear_scene_only(self):
        try:
            self.scene.selectionChanged.disconnect(self._on_scene_selection_changed)
        except Exception:
            pass

        for obj in list(self.scene.items()):
            if isinstance(obj, ConnectionItem) or (isinstance(obj, QGraphicsPathItem) and hasattr(obj, "output_pin")):
                try:
                    if hasattr(obj, "cleanup"): obj.cleanup()
                    if hasattr(obj, "input_pin") and obj.input_pin and hasattr(obj, "node"):
                        input_node = obj.input_pin.node
                        if hasattr(input_node, "plugin"):
                            input_node.plugin.set_input(obj.input_pin.name, None)
                except Exception:
                    pass
                try:
                    self.scene.removeItem(obj)
                except Exception:
                    pass

        for it in list(self.scene.items()):
            if isinstance(it, NodeItem):
                try:
                    if hasattr(it.plugin, "on_remove") and callable(it.plugin.on_remove): it.plugin.on_remove()
                except Exception:
                    pass
                try:
                    it.plugin.cleanup()
                except Exception:
                    pass
                try:
                    self.scene.removeItem(it)
                except Exception:
                    pass
            else:
                try:
                    self.scene.removeItem(it)
                except Exception:
                    pass

        try:
            self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        except Exception:
            pass

        self.view.viewport().update()

    def _action_new_workflow_from_template(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Nouveau workflow…")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Choisissez un modèle de pipeline :"))

        lst = QListWidget(dlg)
        items = [("blank", "Vierge (vide)")] + [(k, TEMPLATES[k]["title"]) for k in TEMPLATES.keys()]
        for _key, title in items:
            lst.addItem(title)
        lst.setCurrentRow(0)
        layout.addWidget(lst)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=dlg)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec_() != QDialog.Accepted:
            return

        idx = lst.currentRow()
        if idx < 0:
            return
        key = items[idx][0]

        self._clear_scene_only()
        self.nodes = []
        self.connections = []
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()

        if key == "blank":
            self.logger.info("🆕 Nouveau workflow vierge")
            self._update_workflow_label()
            return

        if not TEMPLATES:
            self.logger.warning("⚠️ Aucun template disponible (workflow_templates.py manquant).")
            self._update_workflow_label()
            return

        self.logger.info("[Templates] clés disponibles : %s", list(TEMPLATES.keys()))
        try:
            created, title = instantiate_template(self, key)
            self.logger.info(f"[MainWindow] ✅ Workflow modèle: {title} — {len(created)} nœuds instanciés.")
        except Exception as e:
            self.logger.error(f"[MainWindow] ❌ échec instanciation template '{key}': {e}")

        self._update_workflow_label()

    def _new_workflow(self):
        self._clear_scene_only()
        self.nodes = []
        self.connections = []
        self.current_workflow_path = None
        self.temp_suggested_path = self._generate_temp_filename()
        self._update_workflow_label()

    # ---------- helpers config (save/load) ----------
    def _gather_node_config(self, plugin) -> dict:
        try:
            if hasattr(plugin, "export_config") and callable(plugin.export_config):
                cfg = plugin.export_config() or {}
                if isinstance(cfg, dict):
                    return cfg
        except Exception:
            pass
        try:
            outs = getattr(plugin, "outputs", None)
            if isinstance(outs, dict) and "config_out" in outs:
                val = getattr(outs["config_out"], "value", None)
                if isinstance(val, dict):
                    return val.get("config", val)
        except Exception:
            pass
        return {}

    def _apply_config_to_node(self, plugin, cfg: dict):
        ok = False
        try:
            if hasattr(plugin, "import_config") and callable(plugin.import_config):
                plugin.import_config(cfg); ok = True
        except Exception:
            ok = False
        if not ok:
            try:
                ins = getattr(plugin, "inputs", None)
                if isinstance(ins, dict) and "config_in" in ins and hasattr(ins["config_in"], "on_next"):
                    ins["config_in"].on_next(cfg); ok = True
            except Exception:
                ok = False
        if not ok and isinstance(cfg, dict):
            changed = False
            def _flatten(d: dict, parent=""):
                flat = {}
                for k, v in (d or {}).items():
                    key = f"{parent}.{k}" if parent else str(k)
                    if isinstance(v, dict):
                        flat.update(_flatten(v, key))
                    else:
                        flat[key] = v
                return flat
            flat = _flatten(cfg)
            for k, v in flat.items():
                try:
                    if hasattr(plugin, k) and isinstance(v, (int, float, bool, str, list, tuple)):
                        setattr(plugin, k, v); changed = True
                except Exception:
                    pass
            ok = changed
        try:
            if ok and hasattr(plugin, "_emit_config") and callable(plugin._emit_config):
                plugin._emit_config()
        except Exception:
            pass
        return ok

    def _save_workflow(self):
        if not self.current_workflow_path:
            return self._save_workflow_as()
        self._write_workflow_to_file(self.current_workflow_path)
        self._update_workflow_label()

    def _save_workflow_as(self):
        suggested = self.temp_suggested_path if hasattr(self, "temp_suggested_path") else ""
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le workflow sous...", suggested, "JSON Files (*.json)")
        if path:
            self.current_workflow_path = path
            self._write_workflow_to_file(path)
            self._update_workflow_label()

    # --------- Convertit récursivement en objets JSON-sérialisables ---------
    def _json_safe(self, obj, *, max_array_elems: int = 2000):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {str(self._json_safe(k)): self._json_safe(v) pour k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._json_safe(x) for x in obj]
        if isinstance(obj, Path):
            return str(obj)
        if hasattr(obj, "__fspath__"):
            try: return os.fspath(obj)
            except Exception: return str(obj)
        if isinstance(obj, np.generic):
            return obj.item()
        if isinstance(obj, np.ndarray):
            if obj.size <= max_array_elems:
                return obj.tolist()
            return {"__ndarray__": True, "shape": list(obj.shape), "dtype": str(obj.dtype)}
        if isinstance(obj, QPointF):
            return [float(obj.x()), float(obj.y())]
        try:
            return str(obj)
        except Exception:
            return repr(obj)

    def _write_workflow_to_file(self, path):
        data = {"version": 2, "nodes": [], "connections": []}

        for item in self.scene.items():
            if isinstance(item, NodeItem):
                plugin = getattr(item, "plugin", None)
                cfg = self._gather_node_config(plugin) if plugin else {}
                data["nodes"].append({
                    "name": plugin.name if plugin else "Unknown",
                    "type": type(plugin).__name__ if plugin else "Unknown",
                    "position": [item.pos().x(), item.pos().y()],
                    "config": cfg
                })

        for item in self.scene.items():
            if isinstance(item, ConnectionItem):
                out_pin = item.output_pin
                in_pin = item.input_pin
                if not out_pin or not in_pin:
                    continue
                data["connections"].append({
                    "from": out_pin.parentItem().plugin.name,
                    "from_pin": out_pin.name,
                    "to": in_pin.parentItem().plugin.name,
                    "to_pin": in_pin.name
                })

        dirname = os.path.dirname(path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        data_safe = self._json_safe(data)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_safe, f, indent=2, ensure_ascii=False)
        self.logger.info(f"✅ Workflow enregistré : {path}")
        self._update_workflow_label()

    # (legacy) Export PNG seul — conservé pour compat.
    def _export_scene_png(self, *, selected_only=False, margin_px=16, dpi=300, transparent=False):
        try:
            scene = self.scene
            if scene is None:
                QMessageBox.warning(self, "Export", "Aucune scène active.")
                return

            items = scene.selectedItems() if selected_only else scene.items()
            if not items:
                QMessageBox.information(self, "Export", "Aucun élément à exporter.")
                return

            bbox = None
            for it in items:
                r = it.sceneBoundingRect()
                bbox = r if bbox is None else bbox.united(r)
            if bbox is None or bbox.isNull():
                QMessageBox.information(self, "Export", "Zone vide.")
                return

            bbox = bbox.adjusted(-margin_px, -margin_px, margin_px, margin_px)

            scale = float(dpi) / 96.0
            width_px  = max(1, int(bbox.width()  * scale))
            height_px = max(1, int(bbox.height() * scale))
            MAX = 16000
            if width_px > MAX or height_px > MAX:
                k = min(MAX / float(width_px), MAX / float(height_px))
                scale *= k
                width_px  = max(1, int(bbox.width()  * scale))
                height_px = max(1, int(bbox.height() * scale))

            img = QImage(width_px, height_px, QImage.Format_ARGB32)
            img.fill(Qt.transparent if transparent else Qt.white)

            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setRenderHint(QPainter.SmoothPixmapTransform, True)
            target = QRectF(0, 0, width_px, height_px)
            source = QRectF(bbox)
            scene.render(p, target, source)
            p.end()

            dpm = int(dpi / 25.4 * 1000)
            img.setDotsPerMeterX(dpm)
            img.setDotsPerMeterY(dpm)

            path, _ = QFileDialog.getSaveFileName(self, "Exporter la scène en PNG", "scene.png", "PNG (*.png)")
            if not path:
                return

            ok = img.save(path, "PNG")
            if ok:
                self.logger.info(f"✅ Export PNG: {path} ({width_px}×{height_px}px, dpi={dpi}, transparent={transparent})")
            else:
                QMessageBox.warning(self, "Export", "Échec d’export PNG.")
        except Exception as e:
            QMessageBox.critical(self, "Export", str(e))

    def _autosave_tick(self):
        try:
            os.makedirs("workflows", exist_ok=True)
            path = os.path.join("workflows", "_autosave.json")
            self._write_workflow_to_file(path)
            self.logger.info(f"[autosave] {path}")
        except Exception as e:
            self.logger.error(f"[autosave] {e}")

    def _load_workflow(self):
        self.logger.info("📂 Charger workflow")
        path, _ = QFileDialog.getOpenFileName(self, "Charger un workflow", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            data = self._load_json_lenient(path)
        except Exception as e:
            self.logger.error(f"❌ Échec de lecture JSON: {e}")
            QMessageBox.critical(self, "Erreur JSON", f"Impossible de charger le workflow:\n\n{e}")
            return

        self._new_workflow()
        self.logger.info(f"➡️ Données lues depuis le JSON : {list(data.keys())}")

        node_map = {}

        # Reconstruction des nœuds
        for node_data in data.get("nodes", []):
            node_type = node_data.get("type")
            node_name = node_data.get("name")
            pos = node_data.get("position", [200, 200])
            cfg = node_data.get("config", {}) or {}

            found = False
            for plugin_class in self.all_plugins:
                if plugin_class.__name__ == node_type:
                    self.logger.info(f"✅ Plugin trouvé : {plugin_class.__name__}")
                    node_item = NodeItem(plugin_class)
                    node_item.setPos(pos[0], pos[1])
                    self.scene.addItem(node_item)
                    self._raise_node(node_item)

                    try:
                        if cfg:
                            ok = self._apply_config_to_node(node_item.plugin, cfg)
                            self.logger.info(f"   ↳ Config appliquée: {ok}")
                        else:
                            self.logger.info("   ↳ Aucun paramètre de config à appliquer.")
                    except Exception as e:
                        self.logger.error(f"   ↳ Erreur application config: {e}")

                    node_map[node_name] = node_item
                    found = True
                    break
            if not found:
                self.logger.warning(f"⚠️ Plugin introuvable pour type={node_type}")

        # Reconstruction des connexions
        for conn in data.get("connections", []):
            from_node = node_map.get(conn.get("from"))
            to_node = node_map.get(conn.get("to"))
            if from_node and to_node:
                ok = self.connect_by_name(from_node, conn.get("from_pin"), to_node, conn.get("to_pin"))
                if ok:
                    self.logger.info(f"✅ Connexion recréée : {conn}")
            else:
                self.logger.warning(f"⚠️ Nœuds introuvables : {conn.get('from')} ou {conn.get('to')}")

        self.logger.info(f"✅ Workflow chargé : {path}")
        self.current_workflow_path = path
        self._update_workflow_label()

    def _show_lowcode_creator(self):
        self.lowcode_window = LowCodeCreator(main_window=self)
        self.lowcode_window.show()

    def _update_workflow_label(self):
        if self.current_workflow_path:
            self.workflow_label.setText(f"🗂️ Fichier courant : {self.current_workflow_path}")
        elif hasattr(self, "temp_suggested_path"):
            self.workflow_label.setText(f"🗂️ Nouveau fichier : {self.temp_suggested_path} (non enregistré)")
        else:
            self.workflow_label.setText("🗂️ Aucun fichier")

    def _generate_temp_filename(self):
        base_name = "workflow"
        os.makedirs("workflows", exist_ok=True)
        i = 1
        while True:
            candidate = os.path.join("workflows", f"{base_name}_{i:04d}.json")
            if not os.path.exists(candidate):
                return candidate
            i += 1

    # ---------------- JSON loader tolérant ----------------
    def _read_text(self, path: str) -> str:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            return f.read()

    def _json_lenient_cleanup(self, s: str) -> str:
        txt = s
        txt = re.sub(r'//.*?$', '', txt, flags=re.MULTILINE)
        txt = re.sub(r'/\*.*?\*/', '', txt, flags=re.DOTALL)
        txt = re.sub(r'\bNaN\b', 'null', txt)
        txt = re.sub(r'\bInfinity\b', 'null', txt)
        txt = re.sub(r'\b-Infinity\b', 'null', txt)
        txt = re.sub(r',(\s*[\}\]])', r'\1', txt)
        last_brace = txt.rfind('}')
        if last_brace != -1:
            tail = txt[last_brace+1:].strip()
            if tail:
                txt = txt[:last_brace+1]
        return txt

    def _load_json_lenient(self, path: str):
        raw = self._read_text(path)
        try:
            return json.loads(raw)
        except JSONDecodeError:
            pass
        cleaned = self._json_lenient_cleanup(raw)
        try:
            return json.loads(cleaned)
        except JSONDecodeError as e:
            line, col = e.lineno, e.colno
            lines = cleaned.splitlines()
            start = max(0, line-3); end = min(len(lines), line+2)
            context = "\n".join(f"{i+1:>4}: {lines[i]}" for i in range(start, end))
            msg = (f"JSON invalide (ligne {line}, colonne {col}): {e.msg}\nContexte proche:\n{context}")
            raise RuntimeError(msg) from e

    def _normalize_plugin_languages(self):
        for _, plugin_list in self.plugins_by_category.items():
            for cls in plugin_list:
                val = getattr(cls, "language", None) or getattr(cls, "lang", None)
                if not isinstance(val, str) or not val.strip():
                    setattr(cls, "language", "Python")
                else:
                    setattr(cls, "language", self._canon_language(val))

    # ——————————————————————————————————————————————————————————————
    # Export multi-format (PNG/SVG/PDF) recadré sur les items
    # ——————————————————————————————————————————————————————————————
    def _export_scene_any(self, *, selected_only=False, margin_px=16, dpi=300, transparent_png=False):
        """
        Export PNG / SVG / PDF recadré sur les items.
        SVG/PDF : rendu vectoriel fidèle + traits pas trop fins (désactive temporairement les 'cosmetic' pens).
        """
        scene = getattr(self, "scene", None)
        if scene is None:
            QMessageBox.warning(self, "Export", "Aucune scène active.")
            return

        # Items + bbox
        items = scene.selectedItems() if selected_only else scene.items()
        if not items:
            QMessageBox.information(self, "Export", "Aucun élément à exporter.")
            return
        bbox = None
        for it in items:
            r = it.sceneBoundingRect()
            bbox = r if bbox is None else bbox.united(r)
        if bbox is None or bbox.isNull():
            QMessageBox.information(self, "Export", "Zone vide.")
            return
        bbox = bbox.adjusted(-margin_px, -margin_px, margin_px, margin_px)

        # Choix format
        filters = "PNG (*.png);;PDF (*.pdf)"
        if _HAVE_SVG:
            filters = "PNG (*.png);;SVG (*.svg);;PDF (*.pdf)"
        path, selected_filter = QFileDialog.getSaveFileName(self, "Exporter le workflow", "workflow.png", filters)
        if not path:
            return
        lower = path.lower()
        if lower.endswith(".png"):
            fmt = "png"
        elif lower.endswith(".svg") and _HAVE_SVG:
            fmt = "svg"
        elif lower.endswith(".pdf"):
            fmt = "pdf"
        else:
            if "svg" in selected_filter.lower() and _HAVE_SVG:
                fmt = "svg"; path += ".svg"
            elif "pdf" in selected_filter.lower():
                fmt = "pdf"; path += ".pdf"
            else:
                fmt = "png"; path += ".png"

        # Dimensions / échelle (PNG & PDF)
        scale = float(dpi) / 96.0
        width_px  = max(1, int(bbox.width()  * scale))
        height_px = max(1, int(bbox.height() * scale))
        MAX = 16000
        if width_px > MAX or height_px > MAX:
            k = min(MAX / float(width_px), MAX / float(height_px))
            scale *= k
            width_px  = max(1, int(bbox.width()  * scale))
            height_px = max(1, int(bbox.height() * scale))

        # Helpers pour stylo cosmetic
        def _disable_cosmetic_pens():
            changed = []
            try:
                for it in scene.items():
                    if isinstance(it, ConnectionItem):
                        for p in (getattr(it, "_pen_normal", None),
                                  getattr(it, "_pen_hover", None),
                                  getattr(it, "_pen_selected", None)):
                            if p is None:
                                continue
                            changed.append((it, p, p.isCosmetic()))
                            p.setCosmetic(False)
                        if hasattr(it, "_apply_pen"):
                            it._apply_pen()
            except Exception:
                pass
            return changed

        def _restore_cosmetic_pens(changed):
            try:
                done = set()
                for it, p, was in changed:
                    p.setCosmetic(was)
                    done.add(it)
                for it in done:
                    if hasattr(it, "_apply_pen"):
                        it._apply_pen()
            except Exception:
                pass

        # Rendu selon format
        try:
            if fmt == "png":
                img = QImage(width_px, height_px, QImage.Format_ARGB32)
                img.fill(Qt.transparent if transparent_png else Qt.white)
                p = QPainter(img)
                p.setRenderHint(QPainter.Antialiasing, True)
                p.setRenderHint(QPainter.TextAntialiasing, True)
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                target = QRectF(0, 0, width_px, height_px)
                source = QRectF(bbox)
                scene.render(p, target, source)
                p.end()
                dpm = int(dpi / 25.4 * 1000)
                img.setDotsPerMeterX(dpm); img.setDotsPerMeterY(dpm)
                if not img.save(path, "PNG"):
                    raise RuntimeError("Échec de la sauvegarde PNG.")

            elif fmt == "svg":
                if not _HAVE_SVG:
                    QMessageBox.warning(self, "Export", "Support SVG non disponible (PyQt5.QtSvg manquant).")
                    return
                changed = _disable_cosmetic_pens()
                try:
                    gen = QSvgGenerator()
                    gen.setFileName(path)
                    gen.setViewBox(QRectF(0, 0, bbox.width(), bbox.height()))  # repère scène
                    gen.setSize(QSize(width_px, height_px))                    # métadonnée
                    gen.setTitle("Workflow Export"); gen.setDescription("Export vectoriel du workflow.")
                    p = QPainter(gen)
                    p.setRenderHint(QPainter.Antialiasing, True)
                    target = QRectF(0, 0, bbox.width(), bbox.height())        # 1:1 avec viewBox
                    source = QRectF(bbox)
                    scene.render(p, target, source)
                    p.end()
                finally:
                    _restore_cosmetic_pens(changed)

            elif fmt == "pdf":
                changed = _disable_cosmetic_pens()
                try:
                    writer = QPdfWriter(path)
                    writer.setResolution(dpi)

                    # Taille de page exacte (aucune marge)
                    width_mm  = (width_px  / float(dpi)) * 25.4
                    height_mm = (height_px / float(dpi)) * 25.4
                    writer.setPageSizeMM(QSizeF(width_mm, height_mm))
                    try:
                        # Supprime TOUTES les marges pour que target==page
                        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
                    except Exception:
                        pass

                    p = QPainter(writer)
                    p.setRenderHint(QPainter.Antialiasing, True)
                    p.setRenderHint(QPainter.TextAntialiasing, True)

                    # Utilise la page utile du writer (équivalent à width_px/height_px si marges=0)
                    target = QRectF(0, 0, writer.width(), writer.height())
                    source = QRectF(bbox)
                    self.scene.render(p, target, source)
                    p.end()
                finally:
                    _restore_cosmetic_pens(changed)

            else:
                QMessageBox.warning(self, "Export", f"Format non supporté: {fmt}")
                return

            self.logger.info(f"✅ Export {fmt.upper()}: {path} ({width_px}×{height_px}px, dpi={dpi})")
        except Exception as e:
            QMessageBox.critical(self, "Export", str(e))
