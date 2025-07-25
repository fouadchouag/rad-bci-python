from plugins.base import BasePlugin

class AdderPlugin(BasePlugin):
    name = "Adder"
    inputs = ["a", "b"]
    outputs = ["sum"]

    def __init__(self):
        super().__init__()

    def execute(self, inputs):
        a = inputs.get("a", 0.0)
        b = inputs.get("b", 0.0)
        try:
            return {"sum": float(a) + float(b)}
        except Exception:
            return {"sum": 0.0}
