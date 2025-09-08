# Customize RBCIAD

- **Palette categories**: use `category = "Input" | "Processing" | "ML" | "Output" | "Web/Utils" | "Custom"` in your plugin class.
- **Keyboard shortcuts**: F1/Shift+F1/Ctrl+F1 are wired in `rbciad_app.integrate_help` and `rbciad_app.shift_f1_nodes`.
- **Node badges**: `rbciad_app.badge.install_node_badges(scene, main_window)` adds the clickable "?" on nodes.
- **Low-code presets**: edit `gui/lowcode_creator.py` to add preset buttons for common I/O or parameter sets.
- **Docs catalog**: run `python tools/generate_node_catalog.py` to update user docs from your nodes' `help` blocks.
