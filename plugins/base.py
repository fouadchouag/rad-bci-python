class BasePlugin:
    name = "Unnamed"
    language = "Unknown"  # ✅ Nouveau champ
    inputs = ()
    outputs = ()

    def __init__(self):
        self.widget = None

    def execute(self, inputs):
        raise NotImplementedError("execute() must be implemented by the plugin.")
