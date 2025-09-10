# -*- coding: utf-8 -*-
"""
MNESampleLoader — charge le dataset d'exemple MNE (sample_audvis_raw.fif)
→ Avec section Paramètres pliable (fermée par défaut, sans espace gris)
"""
from typing import Optional
import os

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QCheckBox, QFrame, QSizePolicy, QLayout
)
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


# ---------------------- CollapsibleSection robuste (anti "rectangle gris") ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu min/max=0 + invisible (aucun espace). Ouverte: hauteur naturelle.
    Émet `collapsedChanged(bool)` et force le recalcul des layouts/parents.
    """
    collapsedChanged = pyqtSignal(bool)  # True si fermé

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._base_title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # on gère nous-mêmes l'état (démarrage fermé)
        self._btn.setStyleSheet(
            "QPushButton {"
            " text-align: left; padding:6px 8px; font-weight:600;"
            " border:1px solid #ccc; border-radius:6px; background:#f7f7f7;"
            "}"
        )
        self._btn.toggled.connect(self._on_toggled)
        root.addWidget(self._btn)

        self._content = QWidget()
        self._content.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(10, 8, 10, 8)
        self._content_layout.setSpacing(6)
        self._content_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._apply_collapsed_state(True)  # fermé sans espace
        self._update_btn_text()

    # API
    def content_layout(self):
        return self._content_layout

    def add_content_widget(self, w: QWidget):
        self._content_layout.addWidget(w)

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)  # checked => ouvert
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Slots
    def _on_toggled(self, checked: bool):
        collapsed = (not checked)
        self._apply_collapsed_state(collapsed)
        self._update_btn_text()
        self.collapsedChanged.emit(collapsed)
        self._reflow()

    # Implémentation
    def _apply_collapsed_state(self, collapsed: bool):
        if collapsed:
            self._content.setMaximumHeight(0)
            self._content.setMinimumHeight(0)
            self._content.setVisible(False)
            self._line.setVisible(False)
        else:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            self._content.setMinimumHeight(0)
            self._line.setVisible(True)

    def _update_btn_text(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._base_title
        if base.startswith(("▼ ", "▶ ")):
            base = base[2:]
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry()
        self.updateGeometry()
        p = self.parentWidget()
        if p is not None:
            if p.layout():
                p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._delayed_adjust)

    def _delayed_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout():
                    w.layout().activate()
                w.adjustSize()
                w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


class MNESampleLoader(BasePlugin):
    help = {
        'gotchas': ['Télécharge le dataset au 1er appel (via mne.datasets.sample).'],
        'inputs': {},
        'outputs': {'raw': 'mne.Raw', 'status': 'str'},
        'parameters': [
            {'name': 'duration_s', 'type': 'float', 'default': 60.0, 'unit': 's',
             'desc': 'Durée à garder'},
            {'name': 'preload', 'type': 'bool', 'default': True,
             'desc': 'Précharger les données en mémoire'}
        ],
        'summary': "MNESampleLoader — dataset d'exemple MNE (FIF)",
        'usage': "Placez-le en début de pipeline; connectez `raw` vers MNE Viewer 2D."
    }

    name = "MNESampleLoader"
    language = "Python"
    category = "Input Nodes"

    def setup(self):
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        self._widget: Optional[QWidget] = None
        self._dur_s = 60.0
        self._preload = True

    def build_widget(self) -> QWidget:
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("MNE Sample Loader (FIF)")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        if not HAVE_MNE:
            warn = QLabel("MNE n'est pas installé. Faites `pip install mne`.")
            warn.setStyleSheet("color:#b00")
            warn.setWordWrap(True)
            root.addWidget(warn)
            self._widget = w
            return w

        # ---------- Section pliable: Paramètres (fermée par défaut) ----------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)
        # Reflow du node quand on ouvre/ferme
        try:
            sec.collapsedChanged.connect(lambda _: (w.adjustSize(), w.updateGeometry()))
        except Exception:
            pass

        # Ligne durée + preload
        row1 = QWidget()
        r1 = QHBoxLayout(row1); r1.setContentsMargins(0, 0, 0, 0); r1.setSpacing(6)
        r1.addWidget(QLabel("Durée gardée (s)"))
        self._sp_dur = QDoubleSpinBox()
        self._sp_dur.setRange(0.0, 600.0)
        self._sp_dur.setDecimals(1)
        self._sp_dur.setSingleStep(1.0)
        self._sp_dur.setValue(self._dur_s)
        r1.addWidget(self._sp_dur)
        self._chk_preload = QCheckBox("Précharger")
        self._chk_preload.setChecked(self._preload)
        r1.addWidget(self._chk_preload)
        r1.addStretch(1)

        # Bouton Charger
        row_btn = QWidget()
        rbtn = QHBoxLayout(row_btn); rbtn.setContentsMargins(0, 0, 0, 0); rbtn.setSpacing(6)
        self._btn = QPushButton("Charger")
        self._btn.clicked.connect(self._on_load)
        rbtn.addStretch(1)
        rbtn.addWidget(self._btn)

        # Ajout au contenu pliable
        sec.add_content_widget(row1)
        sec.add_content_widget(row_btn)

        # Status (toujours visible)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl)

        # Contraintes pour supprimer tout résidu d’espace
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def _on_load(self):
        if not HAVE_MNE:
            self._set_status("MNE non dispo")
            return
        try:
            self._dur_s = float(self._sp_dur.value())
            self._preload = bool(self._chk_preload.isChecked())

            # 1) chemin du dataset sample (télécharge si absent)
            data_dir = mne.datasets.sample.data_path()
            fif_path = os.path.join(data_dir, "MEG", "sample", "sample_audvis_raw.fif")
            if not os.path.exists(fif_path):
                raise FileNotFoundError("Fichier FIF introuvable après data_path().")

            # 2) lire le Raw FIF
            raw = mne.io.read_raw_fif(fif_path, preload=self._preload, verbose=False)

            # 3) Crop si demandé
            if self._dur_s and self._dur_s > 0:
                try:
                    raw.crop(tmin=0.0, tmax=self._dur_s)
                except TypeError:
                    raw.crop(tmax=self._dur_s)

            # Si pas preload mais nécessaire pour le viewer, on force le chargement
            if self._preload is False:
                try:
                    raw.load_data()
                except Exception:
                    pass

            # 4) sortie
            self.outputs["raw"].on_next(raw)
            nchan = len(raw.ch_names)
            sf = float(raw.info.get('sfreq', 0.0))
            dur = raw.n_times / sf if sf else float('nan')
            self._set_status(
                f"Chargé: {os.path.basename(fif_path)} | Canaux: {nchan} | "
                f"sf: {sf:.2f} Hz | durée: {dur:.1f} s"
            )
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    def execute(self, *args, **kwargs):
        try:
            if getattr(self, "_lbl", None) is not None and self._lbl.text() == "":
                self._set_status("Prêt. Ouvrez ‘Paramètres’ puis cliquez ‘Charger’.")
        except Exception:
            pass
