class ConstantPlugin:
    name = "Constant"
    inputs = {}
    outputs = {"value": float}

    def __init__(self):
        self.value = 1.0  # Valeur par défaut

    def execute(self, inputs):
        return {"value": self.value}
