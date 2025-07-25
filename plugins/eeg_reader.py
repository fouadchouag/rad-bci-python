class EEGReaderPlugin:
    name = "EEG Reader"
    inputs = {}
    outputs = {"eeg_data": list}

    def __init__(self):
        self.eeg_data = [0.0] * 100  # Exemple de données EEG factices

    def execute(self, inputs):
        return {"eeg_data": self.eeg_data}
