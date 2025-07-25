from plugins.base import BasePlugin

class EEGReaderPlugin(BasePlugin):
    name = "EEG Reader"
    inputs = []
    outputs = ["eeg_data"]

    def __init__(self):
        super().__init__()

    def execute(self, inputs):
        return {"eeg_data": [0.0] * 256}  # Valeurs simulées
