# plugins/bandpower_ext_plugin.py
import os, sys, json, uuid, subprocess
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

class BandpowerExtPlugin(BasePlugin):
    """
    Entrées acceptées:
      - segment: ndarray/list (n_ch, n_samples) OU (n_samples, n_ch)
      - sfreq: float  (optionnel si 'info' fourni)
      - ch_names: list[str] (optionnel si 'info' fourni)
      - info: dict {"sfreq": float, "ch_names": list[str]}  (optionnel)

    Sorties:
      - features: dict
      - band_labels: list[str]

    execute(...) retourne TOUJOURS {"features": ..., "band_labels": ...}
    """
    name = "BandpowerExt"
    language = "Python"
    category = "Processing Nodes"

    def setup(self):
        self.inputs["segment"]   = BehaviorSubject(None)
        self.inputs["sfreq"]     = BehaviorSubject(None)
        self.inputs["ch_names"]  = BehaviorSubject(None)
        self.inputs["info"]      = BehaviorSubject(None)  # <— NOUVEAU (rendra le nœud robuste)

        self.outputs["features"]     = BehaviorSubject(None)
        self.outputs["band_labels"]  = BehaviorSubject(["delta","theta","alpha","beta","gamma"])

        # IO temp
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.abspath(os.path.join(here, os.pardir))
        self._uid = uuid.uuid4().hex[:8]
        self._io_dir = os.path.join(root, "temp_io"); os.makedirs(self._io_dir, exist_ok=True)
        self._input_path  = os.path.join(self._io_dir, f"input_bandpower_{self._uid}.json")
        self._output_path = os.path.join(self._io_dir, f"output_bandpower_{self._uid}.json")

        # script externe
        candidates = [
            os.path.join(root, "custom_plugins", "external_scripts", "bandpower_ext.py"),
            os.path.join(root, "custom_plugins", "bandpower_ext.py"),
            os.path.join(root, "external_scripts", "bandpower_ext.py"),
            os.path.join(root, "custom_plugins", "external_scripts", "bandpower_ext.exe"),
            os.path.join(root, "external_scripts", "bandpower_ext.exe"),
        ]
        self._script_candidates = candidates
        self._script_path = next((p for p in candidates if os.path.isfile(p)), None)
        if self._script_path:
            print(f"[BandpowerExt] Using external script: {self._script_path}")
        else:
            print("[BandpowerExt] Missing external script.")

        # caches (au cas où on reçoit les méta une seule fois)
        self._sfreq_cache = None
        self._ch_names_cache = None

    # --------- helpers ---------
    @staticmethod
    def _to_2d_channels_first(x):
        arr = np.asarray(x)
        if arr.ndim == 1:
            arr = arr[None, :]
        # (n_ch, n_samples) attendu
        if arr.shape[0] > arr.shape[1]:
            arr = arr.T
        return arr

    def _resolve_meta(self, inp_dict):
        # info dict prioritaire
        info = inp_dict.get("info", None)
        if isinstance(info, dict):
            sf = info.get("sfreq", None)
            chn = info.get("ch_names", None)
            if isinstance(sf, (int, float)) and sf:
                self._sfreq_cache = float(sf)
            if isinstance(chn, (list, tuple)) and len(chn) > 0:
                self._ch_names_cache = list(chn)

        sf2  = inp_dict.get("sfreq", None)
        chn2 = inp_dict.get("ch_names", None)
        if isinstance(sf2, (int, float)) and sf2:
            self._sfreq_cache = float(sf2)
        if isinstance(chn2, (list, tuple)) and len(chn2) > 0:
            self._ch_names_cache = list(chn2)

        return self._sfreq_cache, self._ch_names_cache

    # --------- main ---------
    def execute(self, *args, **kwargs):
        # Normalisation des inputs (dict + kwargs)
        inp = {}
        if args and isinstance(args[0], dict): inp.update(args[0])
        if kwargs: inp.update(kwargs)

        segment = inp.get("segment", self._values.get("segment"))
        sfreq, ch_names = self._resolve_meta(inp)

        # Valeur de retour par défaut
        ret = {"features": None, "band_labels": self.outputs["band_labels"].value}

        # Données incomplètes
        if segment is None or sfreq is None:
            return ret

        # Normalise segment
        try:
            arr = self._to_2d_channels_first(segment)  # -> (n_ch, n_samples)
        except Exception as e:
            print(f"[BandpowerExt] Bad segment: {e}")
            return ret

        # ch_names par défaut si manquants/mismatch
        if not ch_names or len(ch_names) != int(arr.shape[0]):
            ch_names = [f"ch{i+1}" for i in range(int(arr.shape[0]))]
            self._ch_names_cache = ch_names  # update cache

        # Script introuvable
        if not getattr(self, "_script_path", None) or not os.path.exists(self._script_path):
            print("[BandpowerExt] External script not found.\nTried:\n  " + "\n  ".join(self._script_candidates))
            return ret

        # Écrire input.json
        try:
            seg_list = arr.astype(float, copy=False).tolist()
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
            return ret

        # Construire commande
        is_py = self._script_path.lower().endswith(".py")
        cmd = [sys.executable, self._script_path, "--input", self._input_path, "--output", self._output_path] if is_py \
              else [self._script_path, "--input", self._input_path, "--output", self._output_path]

        # Lancer
        try:
            completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if completed.stdout: print(f"[BandpowerExt][stdout] {completed.stdout.strip()}")
            if completed.stderr: print(f"[BandpowerExt][stderr] {completed.stderr.strip()}")
        except subprocess.CalledProcessError as e:
            print(f"[BandpowerExt] Subprocess error (code {e.returncode}): {e.stderr}")
            return ret
        except Exception as e:
            print(f"[BandpowerExt] Failed to run subprocess: {e}")
            return ret

        # Lire output.json
        try:
            with open(self._output_path, "r", encoding="utf-8") as f:
                out = json.load(f)
            features = out.get("features", None)
            bands = out.get("band_labels", ["delta", "theta", "alpha", "beta", "gamma"])

            # émettre sorties
            self.outputs["features"].on_next(features)
            self.outputs["band_labels"].on_next(bands)

            ret["features"] = features
            ret["band_labels"] = bands
        except Exception as e:
            print(f"[BandpowerExt] Failed to read output json: {e}")

        return ret  # TOUJOURS un dict
