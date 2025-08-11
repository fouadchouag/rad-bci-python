# core/plugin_registry.py

import os
import importlib.util
import inspect

PLUGIN_FOLDERS = {
    "plugins": "plugins",
    "custom_plugins": "custom_plugins"
}

def discover_plugins():
    registry = {}

    for origin, folder in PLUGIN_FOLDERS.items():
        if not os.path.exists(folder):
            continue

        for filename in os.listdir(folder):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_path = os.path.join(folder, filename)
                module_name = f"{folder}.{filename[:-3]}".replace('/', '.').replace('\\', '.')

                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        #if hasattr(obj, "name") and hasattr(obj, "execute"):
                        if hasattr(obj, "name") and hasattr(obj, "setup"):
                            category = getattr(obj, "category", "Uncategorized")
                            registry.setdefault(category, []).append(obj)
                except Exception as e:
                    print(f"[Registry] Failed to load {filename}: {e}")

    return registry
