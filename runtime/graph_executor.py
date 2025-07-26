from collections import defaultdict

class GraphExecutor:
    def __init__(self, scene):
        self.scene = scene
        self.connections = []
        self.node_outputs = {}
        self.node_inputs = defaultdict(dict)

    def execute(self):
        self._gather_connections()
        self._execute_all_nodes()
        self._route_outputs_to_inputs()

        print("--- Graph auto-executed ---")

    def _gather_connections(self):
        self.connections.clear()
        self.node_inputs.clear()
        self.node_outputs.clear()

        for item in self.scene.items():
            if hasattr(item, "start_pin") and hasattr(item, "end_pin"):
                start = item.start_pin
                end = item.end_pin
                if start and end:
                    self.connections.append((start, end))

    def _execute_all_nodes(self):
        for item in self.scene.items():
            if hasattr(item, "plugin"):
                plugin = item.plugin
                # Donne des entrées vides pour tous au départ
                try:
                    output = plugin.execute({})
                    self.node_outputs[item] = output or {}
                    print(f"Node: {plugin.name} -> Output: {output}")
                except Exception as e:
                    print(f"[GraphExecutor Error] executing {plugin.name}: {e}")

    def _route_outputs_to_inputs(self):
        for start_pin, end_pin in self.connections:
            source_node = start_pin.parentItem()
            dest_node = end_pin.parentItem()

            if source_node in self.node_outputs:
                source_val = self.node_outputs[source_node].get(start_pin.name)
                self.node_inputs[dest_node][end_pin.name] = source_val

        for dest_node, inputs in self.node_inputs.items():
            if hasattr(dest_node, "plugin"):
                try:
                    result = dest_node.plugin.execute(inputs)
                    print(f"📥 {dest_node.plugin.name} receives {inputs} -> {result}")
                except Exception as e:
                    print(f"[GraphExecutor Error] input-routing {dest_node.plugin.name}: {e}")
