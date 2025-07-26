
from collections import defaultdict, deque

class GraphExecutor:
    def __init__(self, scene):
        self.scene = scene
        self.connections = []
        self.node_inputs = defaultdict(dict)
        self.node_outputs = {}
        self.adjacency = defaultdict(list)
        self.in_degrees = defaultdict(int)

    def execute(self):
        self._gather_connections()
        ordered_nodes = self._topological_sort()
        self._execute_nodes_in_order(ordered_nodes)

    def _gather_connections(self):
        self.connections.clear()
        self.node_inputs.clear()
        self.node_outputs.clear()
        self.adjacency.clear()
        self.in_degrees.clear()

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
                self.adjacency[source_node].append(dest_node)
                self.in_degrees[dest_node] += 1

        # Préparer les entrées
        for start, end in self.connections:
            source_node = start.parentItem()
            dest_node = end.parentItem()
            source_name = start.name
            dest_name = end.name
            if source_node and dest_node:
                output = self.node_outputs.get(source_node, {})
                self.node_inputs[dest_node][dest_name] = output.get(source_name)

    def _topological_sort(self):
        queue = deque()
        result = []

        # Ajouter les nodes sans dépendances
        for item in self.scene.items():
            if hasattr(item, "plugin"):
                if self.in_degrees[item] == 0:
                    queue.append(item)

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self.adjacency[node]:
                self.in_degrees[neighbor] -= 1
                if self.in_degrees[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def _execute_nodes_in_order(self, ordered_nodes):
        for item in ordered_nodes:
            if hasattr(item, "plugin"):
                inputs = self.node_inputs.get(item, {})
                plugin = item.plugin

                if hasattr(plugin, "execute"):
                    output = plugin.execute(inputs)
                    self.node_outputs[item] = output or {}
                    print(f"Node: {plugin.name} -> Output: {output}")
                else:
                    print(f"Warning: Plugin '{plugin.name}' has no execute method!")

        print("--- Graphe exécuté dans l’ordre logique ---")
