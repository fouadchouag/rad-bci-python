import os, json
from runtime.plugin_descriptor import ComponentDescriptor

class PluginManager:
    @staticmethod
    def load_all_plugins(folder):
        plugins = []
        for file in os.listdir(folder):
            if file.endswith(".json"):
                path = os.path.join(folder, file)
                if os.path.getsize(path) == 0:
                    continue
                with open(path, "r") as f:
                    try:
                        metadata = json.load(f)
                        plugin = ComponentDescriptor(metadata)
                        plugins.append(plugin)
                    except json.JSONDecodeError:
                        print(f"Invalid JSON in {file}")
        return plugins
