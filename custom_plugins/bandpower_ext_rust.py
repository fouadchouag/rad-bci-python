# plugins/bandpower_ext_plugin.py

import os
import sys
import json
import uuid
import subprocess
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin


class BandpowerExtPlugin(BasePlugin):
    """
    Calcule la puissance par bande (delta/theta/alpha/beta/gamma) via un script externe.
    Entrées:
      - segment: np.ndarray/list (n_ch, n_samples)
      - sfreq: float
      - ch_names: list[str]
    Sorties:
      - features: dict { ch_name: {band: value, ...}, ... }
      - band_labels: list[str]
    """
    name = "BandpowerExtRust"
    language = "Rust"
    category = "Custom"

    def setup(self):
        # --- Entrées ---
        self.inputs["segment"] = BehaviorSubject(None)
        self.inputs["sfreq"] = BehaviorSubject(None)
        self.inputs["ch_names"] = BehaviorSubject(None)

        # --- Sorties ---
        self.outputs["features"] = BehaviorSubject(None)
        self.outputs["band_labels"] = BehaviorSubject(["delta", "theta", "alpha", "beta", "gamma"])

        # --- Chemins IO ---
        here = os.path.dirname(os.path.abspath(__file__))     # ...\RAD_bci_python\plugins
        root = os.path.abspath(os.path.join(here, os.pardir)) # ...\RAD_bci_python

        self._uid = uuid.uuid4().hex[:8]
        self._io_dir = os.path.join(root, "temp_io")
        os.makedirs(self._io_dir, exist_ok=True)
        self._input_path  = os.path.join(self._io_dir, f"input_bandpower_{self._uid}.json")
        self._output_path = os.path.join(self._io_dir, f"output_bandpower_{self._uid}.json")

        # --- Résolution robuste du script externe (selon ton arborescence) ---
        candidates = [
            os.path.join(root, "custom_plugins", "external_scripts", "bandpower_ext_rs.exe"),
            os.path.join(root, "external_scripts", "bandpower_ext_rs.exe"),
        ]
        self._script_candidates = candidates
        self._script_path = None
        for p in candidates:
            if os.path.isfile(p):
                self._script_path = p
                break

        if self._script_path:
            print(f"[BandpowerExt] Using external script: {self._script_path}")
        else:
            print("[BandpowerExt] Missing external script. Tried paths:")
            for p in candidates:
                print("   -", p)

    def execute(self, **kwargs):
        segment = kwargs.get("segment", None)
        sfreq = kwargs.get("sfreq", None)
        ch_names = kwargs.get("ch_names", None)

        # Données incomplètes → on attend
        if segment is None or sfreq is None or ch_names is None:
            return {}

        # Script introuvable → on sort proprement (et on logge)
        if not getattr(self, "_script_path", None) or not os.path.exists(self._script_path):
            print("[BandpowerExt] External script not found.")
            tried = getattr(self, "_script_candidates", [])
            if tried:
                print("[BandpowerExt] Tried paths:\n  " + "\n  ".join(tried))
            return {}

        # Écrit input.json
        try:
            # segment: convertir en liste de listes de float (serializable)
            seg_list = [list(map(float, row)) for row in segment]
            payload = {
                "segment": seg_list,
                "sfreq": float(sfreq),
                "ch_names": list(ch_names),
                "bands": {
                    "delta": [1.0, 4.0],
                    "theta": [4.0, 8.0],
                    "alpha": [8.0, 13.0],
                    "beta":  [13.0, 30.0],
                    "gamma": [30.0, 45.0],
                },
            }
            with open(self._input_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)
        except Exception as e:
            print(f"[BandpowerExt] Failed to write input json: {e}")
            return {}

        # Construit et exécute la commande
        is_python_script = self._script_path.lower().endswith(".py")
        if is_python_script:
            cmd = [sys.executable, self._script_path, "--input", self._input_path, "--output", self._output_path]
        else:
            cmd = [self._script_path, "--input", self._input_path, "--output", self._output_path]

        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if completed.stdout:
                print(f"[BandpowerExt][stdout] {completed.stdout.strip()}")
            if completed.stderr:
                # Beaucoup d'outils écrivent sur stderr sans que ce soit une erreur
                print(f"[BandpowerExt][stderr] {completed.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            print(f"[BandpowerExt] Subprocess error (code {e.returncode}): {e.stderr}")
            return {}
        except Exception as e:
            print(f"[BandpowerExt] Failed to run subprocess: {e}")
            return {}

        # Lit output.json
        try:
            with open(self._output_path, "r", encoding="utf-8") as f:
                out = json.load(f)
            features = out.get("features", None)
            bands = out.get("band_labels", ["delta", "theta", "alpha", "beta", "gamma"])
            self.outputs["features"].on_next(features)
            self.outputs["band_labels"].on_next(bands)
        except Exception as e:
            print(f"[BandpowerExt] Failed to read output json: {e}")

        return {}

    def build_widget(self):
        # Headless (pas de widget nécessaire)
        return None
