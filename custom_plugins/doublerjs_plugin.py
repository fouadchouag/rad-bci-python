# Wrapper auto-généré pour doublerjs
import os
import subprocess
import json
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class doublerjsPlugin(BasePlugin):
    name = "doublerjs"
    language = "external"
    category = "Custom"
    executable = r"custom_plugins/external_scripts/double.js"

    def setup(self):
        self.inputs["input1"] = BehaviorSubject(None)
        self.outputs["output1"] = BehaviorSubject(None)

    def _build_command(self):
        ext = os.path.splitext(self.executable)[1].lower()
        if ext == ".js":
            return ["node", self.executable]
        elif ext == ".sh":
            return ["bash", self.executable]
        elif ext == ".py":
            return ["python", self.executable]
        elif ext == ".r":
            return ["Rscript", self.executable]
        
        elif ext == ".m":
            return ["octave", "--quiet", "--eval", f"run('{self.executable}')"]
        elif ext == ".jl":
            return ["julia", self.executable]          
        elif ext in [".exe"]:
            return [self.executable]
        else:
            raise Exception("Type de script non pris en charge.")

    def execute(self, **kwargs):
        try:
            temp_dir = "temp_io"
            os.makedirs(temp_dir, exist_ok=True)
            input_path = os.path.join(temp_dir, f"input_doublerjs.json")
            output_path = os.path.join(temp_dir, f"output_doublerjs.json")
            
            
            os.makedirs(temp_dir, exist_ok=True)

            with open(input_path, "w") as f:
                json.dump(kwargs, f)

            cmd = self._build_command()
            subprocess.run(cmd, check=True)

            with open(output_path, "r") as f:
                result = json.load(f)

            # (facultatif mais conseillé)
            #if os.path.exists(input_path): os.remove(input_path)
            #if os.path.exists(output_path): os.remove(output_path)

            return result
        except Exception as e:
            print(f"[ERREUR] Subprocess échoué: {e}")
            return {}
