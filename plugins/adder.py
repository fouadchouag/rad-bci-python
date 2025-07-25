class AdderPlugin:
    name = "Adder"
    inputs = {"a": float, "b": float}
    outputs = {"sum": float}

    def execute(self, inputs):
        a = inputs.get("a", 0.0)
        b = inputs.get("b", 0.0)
        return {"sum": a + b}
