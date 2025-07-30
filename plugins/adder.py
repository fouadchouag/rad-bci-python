from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class Adder(BasePlugin):
    name = "Adder"
    category = "Processing Nodes"
    language = "Python"

    def setup(self):
        self.inputs = {
            "a": BehaviorSubject(None),
            "b": BehaviorSubject(None)
        }
        self.outputs = {
            "sum": BehaviorSubject(None)
        }

    def execute(self, a=0, b=0):
        if a is None or b is None:
            return {"sum": None}
        return {"sum": a + b}

