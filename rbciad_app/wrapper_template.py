
# rbciad_app/wrapper_template.py
from __future__ import annotations
import pprint
from typing import List, Dict, Any

def make_wrapper_code(module_name: str,
                      class_name: str,
                      display_name: str,
                      category: str = "Processing",
                      inputs: Dict[str,str] = None,
                      outputs: Dict[str,str] = None,
                      parameters: List[Dict[str,Any]] = None,
                      summary: str = "",
                      usage: str = "",
                      gotchas: List[str] = None) -> str:
    """
    Return a ready-to-save Python wrapper skeleton with a class-level `help = {...}`.
    """
    inputs = inputs or {"segment":"2D float [ch x samples]"}
    outputs = outputs or {"segment":"processed array"}
    parameters = parameters or []
    gotchas = gotchas or []
    helpd = {
        "summary": summary or "Describe what this node does in one sentence.",
        "inputs": inputs,
        "outputs": outputs,
        "parameters": parameters,
        "usage": usage or "Connect upstream node(s), set parameters, route to next step.",
        "gotchas": gotchas,
    }
    help_txt = pprint.pformat(helpd, width=88, compact=False, indent=2)
    code = f"""
# plugins/{{module_name}}.py
from core.base_plugin import BasePlugin  # adjust import to your base
# import other deps here

class {{class_name}}(BasePlugin):
    category = "{{category}}"
    display_name = "{{display_name}}"

    help = {{help_txt}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # init your state here

    def setup(self):
        # allocate resources
        pass

    def process(self, **kwargs):
        # read from kwargs your inputs
        # return dict for outputs
        return {{}}

    def teardown(self):
        # free resources
        pass
"""
    return code
