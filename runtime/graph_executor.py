from collections import defaultdict

class GraphExecutor:
    def __init__(self, scene):
        self.scene = scene
        self.connections = []
        self.node_inputs = defaultdict(dict)
        self.node_outputs = {}

    def execute(self):
        self._gather_connections()
        self._execute_nodes()

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

        for start, end in self.connections:
            source_node = start.parentItem()
            dest_node = end.parentItem()
            source_name = start.name
            dest_name = end.name
            if source_node and dest_node:
                output = self.node_outputs.get(source_node, {})
                self.node_inputs[dest_node][dest_name] = output.get(source_name)

    def _execute_nodes(self):
        for item in self.scene.items():
            if hasattr(item, "plugin"):
                inputs = self.node_inputs.get(item, {})
                plugin = item.plugin

                if hasattr(plugin, "execute"):
                    output = plugin.execute(inputs)
                    self.node_outputs[item] = output or {}
                    print(f"Node: {plugin.name} -> Output: {output}")
                else:
                    print(f"Warning: Plugin '{plugin.name}' has no executable function!")

        print("--- Graph auto-executed ---")
