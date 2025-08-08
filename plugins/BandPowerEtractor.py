# plugins/BandPowerExtractorPlugin.py

import numpy as np
import mne
from scipy.signal import welch
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin


class BandPowerExtractorPlugin(BasePlugin):
    name = "BandPowerExtractor"
    category = "Processing Nodes"

    def setup(self):
        self.inputs["raw_data"] = BehaviorSubject(None)
        self.inputs["channel"] = BehaviorSubject("Cz")
        self.inputs["bands"] = BehaviorSubject({
            "delta": [1, 4],
            "theta": [4, 8],
            "alpha": [8, 12],
            "beta": [12, 30],
            "gamma": [30, 45]
        })
        self.outputs["band_powers"] = BehaviorSubject(None)

    def execute(self, raw_data=None, channel="Cz", bands=None):
        if raw_data is None or not isinstance(raw_data, mne.io.BaseRaw):
            print("[BandPowerExtractor] Erreur : raw_data est invalide ou manquant.")
            return

        if bands is None or not isinstance(bands, dict):
            print("[BandPowerExtractor] Erreur : bands est invalide.")
            return

        try:
            # Extraire les données du canal spécifié
            picks = mne.pick_channels(raw_data.info["ch_names"], include=[channel])
            if not picks:
                print(f"[BandPowerExtractor] Canal '{channel}' introuvable.")
                return

            data, times = raw_data[picks, :]
            data = data[0]  # Un seul canal
            sfreq = raw_data.info["sfreq"]

            # Calculer le spectre de puissance avec Welch
            freqs, psd = welch(data, sfreq, nperseg=1024)

            # Intégrer les puissances dans chaque bande
            band_powers = {}
            for name, (fmin, fmax) in bands.items():
                idx = np.logical_and(freqs >= fmin, freqs <= fmax)
                band_power = np.trapz(psd[idx], freqs[idx])
                band_powers[name] = float(band_power)

            return {"band_powers": band_powers}

        except Exception as e:
            print(f"[BandPowerExtractor] Erreur durant le calcul : {e}")
            return
