# plugins/mne_ssp_projs_plugin.py
# -*- coding: utf-8 -*-
"""
MNE Compute SSP Projs — rapide (EOG / ECG)
→ Avec section Paramètres pliable (fermée par défaut, sans zone grise résiduelle)

Ajoute des projecteurs SSP au Raw pour suppression d'artéfacts et visualisation
avec mne.viz.plot_projs_topomap (dans ton MNE Viewer 2D).

Entrée
  - raw : mne.io.Raw (EEG/MEG)

Options UI
  - n_eog, l_freq_eog, h_freq_eog, ch_name_eog (facultatif)
  - n_ecg, l_freq_ecg, h_freq_ecg, ch_name_ecg (facultatif)
  - EOG virtuel A-B, ECG virtuel (depuis canal ou moyenne EEG)
  - Boutons: "Compute EOG", "Compute ECG", "Créer EOGv", "Créer ECGv"

Sorties
  - raw (même objet, mais avec raw.info['projs'] complété)
  - status (texte)

Notes
  - Les projecteurs ne sont PAS appliqués au signal (pas de raw.apply_proj()).
"""
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QDoubleSpinBox, QSpinBox, QSizePolicy, QLayout, QFrame
)
from PyQt5.QtCore import QTimer
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

try:
    import mne
    from mne.preprocessing import compute_proj_eog, compute_proj_ecg
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False


# ---------------------- Section pliable (anti “cadre gris”) ----------------------
class CollapsibleSection(QWidget):
    """
    Fermée: contenu invisible + hauteur max=0 (aucun espace).
    Ouverte: hauteur naturelle. Reflow en cascade pour éviter toute zone grise.
    """
    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._title = title

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        self._btn = QPushButton()
        self._btn.setCheckable(True)
        self._btn.setChecked(False)  # démarrage fermé
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
        self._lay = QVBoxLayout(self._content)
        self._lay.setContentsMargins(10, 8, 10, 8)
        self._lay.setSpacing(6)
        self._lay.setSizeConstraint(QLayout.SetMinAndMaxSize)
        root.addWidget(self._content)

        self._line = QFrame()
        self._line.setFrameShape(QFrame.HLine)
        self._line.setStyleSheet("color:#ddd;")
        root.addWidget(self._line)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.set_collapsed(True)  # fermé par défaut

    def content_layout(self):
        return self._lay

    def set_collapsed(self, collapsed: bool):
        self._btn.setChecked(not collapsed)
        self._apply(collapsed)
        self._update_title()
        self._reflow()

    def _on_toggled(self, checked: bool):
        self._apply(collapsed=not checked)
        self._update_title()
        self._reflow()

    def _apply(self, collapsed: bool):
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

    def _update_title(self):
        arrow = "▼ " if self._btn.isChecked() else "▶ "
        base = self._title[2:] if self._title[:2] in ("▼ ", "▶ ") else self._title
        self._btn.setText(arrow + base)

    def _reflow(self):
        self._content.updateGeometry(); self.updateGeometry()
        p = self.parentWidget()
        if p and p.layout():
            p.layout().activate()
            p.adjustSize()
            p.updateGeometry()
        QTimer.singleShot(0, self._bubble_adjust)

    def _bubble_adjust(self):
        w = self
        while w is not None:
            try:
                if w.layout(): w.layout().activate()
                w.adjustSize(); w.updateGeometry()
            except Exception:
                pass
            w = w.parentWidget()


class MNEComputeSSPProjs(BasePlugin):
    help = {
        'gotchas': [],
        'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
        'outputs': {'segment': 'processed array'},
        'parameters': [],
        'summary': 'MNE Compute SSP Projs — rapide (EOG / ECG)',
        'usage': 'Wire upstream data and route downstream.'
    }

    name = "MNE Compute SSP Projs"
    language = "Python"
    category = "Transform Nodes"

    def setup(self):
        self.inputs["raw"] = BehaviorSubject(None)
        self.outputs["raw"] = BehaviorSubject(None)
        self.outputs["status"] = BehaviorSubject("")
        self._widget: Optional[QWidget] = None
        self._raw = None
        # params
        self._n_eog = 2
        self._l_eog = 1.0
        self._h_eog = 10.0
        self._ch_eog = ""
        self._n_ecg = 2
        self._l_ecg = 8.0
        self._h_ecg = 20.0
        self._ch_ecg = ""

    def build_widget(self) -> QWidget:
        if self._widget is not None:
            return self._widget

        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        root.setSizeConstraint(QLayout.SetMinAndMaxSize)

        title = QLabel("SSP Projs (EOG/ECG) — rapide")
        title.setStyleSheet("font-weight:600;font-size:14px;")
        root.addWidget(title)

        if not HAVE_MNE:
            warn = QLabel("MNE non installé. `pip install mne`.")
            warn.setStyleSheet("color:#b00")
            root.addWidget(warn)

        # ---------- Section pliable: Paramètres (fermée par défaut) ----------
        sec = CollapsibleSection("Paramètres")
        sec.set_collapsed(True)

        # --- EOG compute ---
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("EOG: n="))
        self._sp_neog = QSpinBox(); self._sp_neog.setRange(0, 10); self._sp_neog.setValue(self._n_eog); row1.addWidget(self._sp_neog)
        row1.addWidget(QLabel("l_freq"))
        self._sp_leog = QDoubleSpinBox(); self._sp_leog.setRange(0.0, 50.0); self._sp_leog.setDecimals(1); self._sp_leog.setValue(self._l_eog); row1.addWidget(self._sp_leog)
        row1.addWidget(QLabel("h_freq"))
        self._sp_heog = QDoubleSpinBox(); self._sp_heog.setRange(0.0, 200.0); self._sp_heog.setDecimals(1); self._sp_heog.setValue(self._h_eog); row1.addWidget(self._sp_heog)
        row1.addWidget(QLabel("ch_name (opt)"))
        self._ed_ceog = QLineEdit(self._ch_eog); self._ed_ceog.setPlaceholderText("EOG / Fp1 / Fpz …"); row1.addWidget(self._ed_ceog, 1)
        self._btn_eog = QPushButton("Compute EOG"); self._btn_eog.clicked.connect(self._on_eog); row1.addWidget(self._btn_eog)

        # --- EOG virtuel ---
        row1b = QHBoxLayout()
        row1b.addWidget(QLabel("EOG virtuel: A - B"))
        self._ed_eogA = QLineEdit(); self._ed_eogA.setPlaceholderText("Fp1 (ex)")
        self._ed_eogB = QLineEdit(); self._ed_eogB.setPlaceholderText("Fp2/Fpz (ex)")
        row1b.addWidget(self._ed_eogA); row1b.addWidget(self._ed_eogB)
        self._btn_eogv = QPushButton("Créer EOGv"); self._btn_eogv.clicked.connect(self._make_virtual_eog); row1b.addWidget(self._btn_eogv)

        # --- ECG compute ---
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("ECG: n="))
        self._sp_necg = QSpinBox(); self._sp_necg.setRange(0, 10); self._sp_necg.setValue(self._n_ecg); row2.addWidget(self._sp_necg)
        row2.addWidget(QLabel("l_freq"))
        self._sp_lecg = QDoubleSpinBox(); self._sp_lecg.setRange(0.0, 50.0); self._sp_lecg.setDecimals(1); self._sp_lecg.setValue(self._l_ecg); row2.addWidget(self._sp_lecg)
        row2.addWidget(QLabel("h_freq"))
        self._sp_hecg = QDoubleSpinBox(); self._sp_hecg.setRange(0.0, 200.0); self._sp_hecg.setDecimals(1); self._sp_hecg.setValue(self._h_ecg); row2.addWidget(self._sp_hecg)
        row2.addWidget(QLabel("ch_name (opt)"))
        self._ed_cecg = QLineEdit(self._ch_ecg); self._ed_cecg.setPlaceholderText("ECG / ECG001 / …"); row2.addWidget(self._ed_cecg, 1)
        self._btn_ecg = QPushButton("Compute ECG"); self._btn_ecg.clicked.connect(self._on_ecg); row2.addWidget(self._btn_ecg)

        # --- ECG virtuel ---
        row2b = QHBoxLayout()
        row2b.addWidget(QLabel("ECG virtuel depuis canal (ou vide = moyenne EEG)"))
        self._ed_ecgFrom = QLineEdit(); self._ed_ecgFrom.setPlaceholderText("ECG source (ex: Cz), ou vide → moyenne EEG")
        row2b.addWidget(self._ed_ecgFrom, 1)
        self._btn_ecgv = QPushButton("Créer ECGv"); self._btn_ecgv.clicked.connect(self._make_virtual_ecg); row2b.addWidget(self._btn_ecgv)

        # Emballer les lignes dans des widgets (meilleur sizing)
        def pack(*layouts):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(6)
            for L in layouts:
                lay.addLayout(L)
            return box

        sec.content_layout().addWidget(pack(row1, row1b, row2, row2b))

        # Status (toujours visible)
        self._lbl = QLabel("")
        self._lbl.setStyleSheet("color:#666")

        root.addWidget(sec)
        root.addWidget(self._lbl)

        # Contraintes anti “cadre gris”
        w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        w.setMinimumSize(0, 0)
        w.updateGeometry()

        self._widget = w
        return w

    def _set_status(self, msg: str):
        self.outputs["status"].on_next(msg)
        if getattr(self, "_lbl", None) is not None:
            self._lbl.setText(msg)

    def execute(self, *args, **kwargs):
        try:
            inps = kwargs or (args[0] if args and isinstance(args[0], dict) else self.inputs)
            def _v(x):
                try: return x.value
                except Exception: return x
            raw = _v(inps.get("raw"))
            if raw is not None and raw is not self._raw:
                self._raw = raw
                self._set_status(self._summary())
        except Exception as e:
            self._set_status(f"Erreur: {e}")

    def _summary(self):
        if self._raw is None: return "Aucun Raw"
        nproj = len(self._raw.info.get('projs', []) or [])
        return f"Raw: {len(self._raw.ch_names)} ch | sf={self._raw.info.get('sfreq', 0):.1f} Hz | projs={nproj}"

    # ------------------- EOG -------------------
    def _on_eog(self):
        if not HAVE_MNE:
            self._set_status("MNE non installé"); return
        if self._raw is None:
            self._set_status("Aucun Raw"); return
        try:
            self._n_eog = int(self._sp_neog.value())
            self._l_eog = float(self._sp_leog.value())
            self._h_eog = float(self._sp_heog.value())
            self._ch_eog = self._ed_ceog.text().strip() or None
            projs, _ = compute_proj_eog(self._raw, n_grad=0, n_mag=0, n_eeg=self._n_eog,
                                        ch_name=self._ch_eog, l_freq=self._l_eog, h_freq=self._h_eog)
            if projs:
                self._raw.add_proj(projs, remove_existing=False)
                self.outputs["raw"].on_next(self._raw)
                self._set_status(f"EOG projs ajoutés: {len(projs)} | total={len(self._raw.info['projs'])}")
            else:
                self._set_status("Aucun proj EOG calculé (essayez un canal frontal en ch_name ou créez EOGv)")
        except Exception as e:
            self._set_status(f"Erreur EOG: {e}")

    def _make_virtual_eog(self):
        if not HAVE_MNE:
            self._set_status("MNE non installé"); return
        if self._raw is None:
            self._set_status("Aucun Raw"); return
        try:
            A = self._ed_eogA.text().strip(); B = self._ed_eogB.text().strip()
            if not A or not B:
                self._set_status("Renseignez A et B (ex: Fp1 et Fp2/Fpz)"); return
            if A not in self._raw.ch_names or B not in self._raw.ch_names:
                self._set_status("Canaux inconnus. Vérifiez les noms."); return
            new_name = 'EOGv'
            if new_name in self._raw.ch_names:
                self._set_status("EOGv existe déjà — utilisation telle quelle.")
            else:
                mne.set_bipolar_reference(self._raw, A, B, ch_name=new_name, drop_refs=False, copy=False)
                self._raw.set_channel_types({new_name: 'eog'})
                self._set_status(f"EOGv créé comme {A}-{B}.")
            self.outputs["raw"].on_next(self._raw)
        except Exception as e:
            self._set_status(f"Erreur EOGv: {e}")

    # ------------------- ECG -------------------
    def _on_ecg(self):
        if not HAVE_MNE:
            self._set_status("MNE non installé"); return
        if self._raw is None:
            self._set_status("Aucun Raw"); return
        try:
            self._n_ecg = int(self._sp_necg.value())
            self._l_ecg = float(self._sp_lecg.value())
            self._h_ecg = float(self._sp_hecg.value())
            self._ch_ecg = self._ed_cecg.text().strip() or None
            projs, _ = compute_proj_ecg(self._raw, n_grad=0, n_mag=0, n_eeg=self._n_ecg,
                                        ch_name=self._ch_ecg, l_freq=self._l_ecg, h_freq=self._h_ecg)
            if projs:
                self._raw.add_proj(projs, remove_existing=False)
                self.outputs["raw"].on_next(self._raw)
                self._set_status(f"ECG projs ajoutés: {len(projs)} | total={len(self._raw.info['projs'])}")
            else:
                self._set_status("Aucun proj ECG calculé (essayez un canal source ou créez ECGv)")
        except Exception as e:
            self._set_status(f"Erreur ECG: {e}")

    def _make_virtual_ecg(self):
        if not HAVE_MNE:
            self._set_status("MNE non installé"); return
        if self._raw is None:
            self._set_status("Aucun Raw"); return
        try:
            src = self._ed_ecgFrom.text().strip()
            if src and src in self._raw.ch_names:
                data = self._raw.copy().pick([src]).get_data()
            else:
                data = self._raw.copy().pick('eeg').get_data().mean(axis=0, keepdims=True)
            info = mne.create_info(['ECGv'], self._raw.info['sfreq'], ['ecg'])
            raw_ecg = mne.io.RawArray(data, info)
            self._raw.add_channels([raw_ecg], force_update_info=True)
            self.outputs["raw"].on_next(self._raw)
            self._set_status("ECGv créé (canal virtuel). Vous pouvez maintenant Compute ECG.")
        except Exception as e:
            self._set_status(f"Erreur ECGv: {e}")
