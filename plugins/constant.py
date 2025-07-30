from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class Constant(BasePlugin):
    name = "Constant"
    category = "Input Nodes"
    language = "Python"

    def setup(self):
        self.outputs = {
            "value": BehaviorSubject(1)
        }

    def execute(self, **kwargs):
        return {"value": self.outputs["value"].value}
