class ComponentDescriptor:
    def __init__(self, metadata):
        self.name = metadata.get("name")
        self.language = metadata.get("language")
        self.inputs = metadata.get("inputs", [])
        self.outputs = metadata.get("outputs", [])
        self.script_path = metadata.get("script")
        self.description = metadata.get("description", "")
