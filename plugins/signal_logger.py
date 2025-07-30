from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class SignalLogger(BasePlugin):
    name = "Logger"
    category = "Output Nodes"
    language = "Python"

    def setup(self):
        self.inputs = {
            "input": BehaviorSubject(None)
        }

    def execute(self, input=0):
        print(f"[Logger] Value received: {input}")
        return {}
