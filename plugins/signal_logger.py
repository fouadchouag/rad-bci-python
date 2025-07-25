class SignalLoggerPlugin:
    name = "Signal Logger"
    inputs = {"signal": object}
    outputs = {}

    def execute(self, inputs):
        signal = inputs.get("signal", None)
        print("Signal logged:", signal)
        return {}
