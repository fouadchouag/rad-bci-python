# plugins/base.py

class BasePlugin:
    name = "Unnamed"
    language = "Unknown"
    inputs = []
    outputs = []

    def __init__(self):
        self.widget = None
        self._node_item = None
        self._last_result = {}  # 🧠 Mémoriser la dernière sortie calculée

    def execute(self, inputs):
        raise NotImplementedError("execute() must be implemented by the plugin.")

    def on_input_updated(self):
        if not self._node_item:
            return

        inputs = {}
        scene = self._node_item.scene()

        for pin in self._node_item.input_pins:
            for item in scene.items():
                if hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                    if item.end_pin == pin:
                        source_node = item.start_pin.parentItem()
                        source_result = source_node.plugin._last_result  # ✅ lire le dernier résultat calculé
                        inputs[pin.name] = source_result.get(item.start_pin.name)

        print(f"[DEBUG] Propagation depuis {self.name}")
        result = self.execute(inputs)
        self._last_result = result  # ✅ enregistrer le résultat pour les suivants
        print(f"Node: {self.name} -> Output: {result}")

        for output_pin in self._node_item.output_pins:
            if output_pin.name in result:
                output_value = result[output_pin.name]
                for item in scene.items():
                    if hasattr(item, "start_pin") and item.start_pin == output_pin:
                        dest_node = item.end_pin.parentItem()
                        if hasattr(dest_node.plugin, "on_input_updated"):
                            dest_node.plugin.on_input_updated()
