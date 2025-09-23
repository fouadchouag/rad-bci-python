# -*- coding: utf-8 -*-
"""
MNEAveragePlugin
- Entrée:  epochs (mne.Epochs)
- Sortie:  evoked (mne.Evoked), n_epochs (int)
- Option:  picks_eeg_only (bool)  [def True]
"""
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

from PyQt5.QtWidgets import QWidget, QFormLayout, QCheckBox
from PyQt5.QtCore import Qt
from core.collapsible import CollapsibleSection

try:
    import mne
    HAVE_MNE = True
except Exception:
    HAVE_MNE = False

class MNEAveragePlugin(BasePlugin):
    help = help = { 'gotchas': [],
  'inputs': {'segment': '2D float [ch x samples] (or raw/epochs)'},
  'outputs': {'segment': 'processed array'},
  'parameters': [],
  'summary': 'MNEAveragePlugin',
  'usage': 'Wire upstream data and route downstream.'}

    name = "MNEAverage"
    language = "Python"
    category = "Preprocessing"
    supports_collapse = True
    start_hidden = True

    def setup(self):
        self.inputs = {
            "epochs": BehaviorSubject(None),
            "picks_eeg_only": BehaviorSubject(True),
        }
        self.outputs = {
            "evoked": BehaviorSubject(None),
            "n_epochs": BehaviorSubject(0),
        }
        self._chk = None
        self._widget = None

    def build_widget(self):
        if self._widget: return self._widget
        panel = QWidget()
        form = QFormLayout(panel)
        self._chk = QCheckBox("Picks EEG only")
        self._chk.setChecked(True)
        self._chk.stateChanged.connect(lambda s: self.set_input("picks_eeg_only", bool(s == Qt.Checked)))

        form.addRow(self._chk)
        w = QWidget()
        lay = QFormLayout(w)
        lay.addRow(CollapsibleSection("Average options", panel, collapsed=True))
        self._widget = w
        return w

    def execute(self, **kwargs):
        in_data = kwargs.get("in_data", {}) if "in_data" in kwargs else {}
        in_data.update(kwargs)

        epochs = in_data.get("epochs", None)
        if (not HAVE_MNE) or (epochs is None):
            # pas d’update de BehaviorSubject ici; on retourne un dict vide/sûr
            return {"evoked": None, "n_epochs": 0}

        picks_eeg_only = bool(in_data.get("picks_eeg_only", True))

        try:
            ep = epochs
            if picks_eeg_only and hasattr(ep, "info"):
                try:
                    picks = mne.pick_types(ep.info, eeg=True, meg=False, eog=False, ecg=False,
                                           stim=False, misc=False, exclude=[])
                    if picks is not None:
                        ep = ep.copy().pick(picks)
                except Exception:
                    pass

            evoked = ep.average(method="mean")
            n_ep = len(ep)
            # Propager sur BS (optionnel, mais on renvoie aussi dans le dict pour la compat BasePlugin)
            self.outputs["evoked"].on_next(evoked)
            self.outputs["n_epochs"].on_next(n_ep)
            return {"evoked": evoked, "n_epochs": n_ep}
        except Exception as e:
            print(f"[MNEAverage] Error: {e}")
            return {"evoked": None, "n_epochs": 0}