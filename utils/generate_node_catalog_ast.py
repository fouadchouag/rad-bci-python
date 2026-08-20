#!/usr/bin/env python3
"""
Extract plugin help dicts using AST (no imports needed).
Writes RBciAD_docs/docs/user/nodes/ pages.
"""
import ast, os, re, sys
from pathlib import Path

def slugify(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]+', '-', s).strip('-').lower() or "node"

def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")

def extract_string(node):
    """Recursively extract a Python string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            elif isinstance(v, ast.FormattedValue):
                parts.append("{...}")
            else:
                parts.append("{...}")
        return "".join(parts)
    if isinstance(node, ast.Name) and node.id in ('True', 'False', 'None'):
        return node.id
    return None

def extract_dict_value(node):
    """Extract a simple dict from AST node to Python dict (strings only)."""
    if isinstance(node, ast.Dict):
        d = {}
        for k, v in zip(node.keys, node.values):
            key = extract_string(k)
            if key is None:
                continue
            val = extract_string(v)
            if val is not None:
                d[key] = val
            elif isinstance(v, ast.Dict):
                d[key] = extract_dict_value(v)
        return d
    return {}

def extract_list_value(node):
    """Extract a list of strings from AST."""
    if isinstance(node, ast.List):
        result = []
        for elt in node.elts:
            s = extract_string(elt)
            if s is not None:
                result.append(s)
            elif isinstance(elt, ast.Dict):
                result.append(extract_dict_value(elt))
        return result
    return []

def parse_help_dict(node):
    """Parse a help = {...} assignment node into a dict."""
    if isinstance(node, ast.Dict):
        h = {}
        for k, v in zip(node.keys, node.values):
            key = extract_string(k)
            if key is None:
                continue
            if key == 'inputs':
                h['inputs'] = extract_dict_value(v)
            elif key == 'outputs':
                h['outputs'] = extract_dict_value(v)
            elif key == 'parameters':
                h['parameters'] = extract_list_value(v)
            elif key == 'gotchas':
                h['gotchas'] = extract_list_value(v)
            else:
                val = extract_string(v)
                if val is not None:
                    h[key] = val
        return h
    return {}

def extract_plugins_from_file(filepath):
    """Parse a .py file and extract plugin classes with help dicts."""
    try:
        source = filepath.read_text(encoding='utf-8')
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError):
        return []

    plugins = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Find help = {...} assignment
        help_dict = {}
        attrs = {}
        for item in ast.walk(node):
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        attrs[target.id] = item.value

        if 'help' in attrs:
            help_dict = parse_help_dict(attrs['help'])

        if not help_dict:
            continue

        # Extract class attributes
        display_name = None
        category = None
        language = ""

        for attr_name, attr_val in attrs.items():
            if attr_name == 'name':
                display_name = extract_string(attr_val)
            elif attr_name == 'category':
                category = extract_string(attr_val)
            elif attr_name == 'language':
                language = extract_string(attr_val) or ""

        if not display_name:
            display_name = node.name

        # Try to get category from parent class
        if not category:
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_name = base.id
                    if 'ui' in base_name.lower() or 'visual' in base_name.lower():
                        category = 'Visualization'
                    elif 'reader' in base_name.lower():
                        category = 'Input/Output'
                    elif 'train' in base_name.lower():
                        category = 'Machine Learning'
                    elif 'filter' in base_name.lower() or 'preproc' in base_name.lower():
                        category = 'Signal Processing'
                    elif 'node' in base_name.lower():
                        category = 'Neural Processing'

        if not category:
            category = 'Custom'

        plugins.append({
            'class_name': node.name,
            'display_name': display_name or node.name,
            'category': category,
            'language': language,
            'help': help_dict,
            'file': str(filepath.name),
        })

    return plugins

def render_node_page(node):
    h = node.get("help", {}) or {}
    inputs = h.get("inputs", {}) or {}
    outputs = h.get("outputs", {}) or {}
    params = h.get("parameters", []) or []
    gotchas = h.get("gotchas", []) or []
    if isinstance(gotchas, str):
        gotchas = [gotchas]

    def table_io(d):
        if not d:
            return "_None_"
        rows = ["| Name | Description |", "|---|---|"]
        for k, v in d.items():
            rows.append(f"| {md_escape(k)} | {md_escape(v)} |")
        return "\n".join(rows)

    def table_params(lst):
        if not lst:
            return "_None_"
        rows = ["| Name | Type | Default | Unit | Description |", "|---|---|---|---|---|"]
        for p in lst:
            if isinstance(p, dict):
                rows.append("| {name} | {type} | {default} | {unit} | {desc} |".format(
                    name=md_escape(p.get("name", "")),
                    type=md_escape(p.get("type", "")),
                    default=md_escape(p.get("default", "")),
                    unit=md_escape(p.get("unit", "")),
                    desc=md_escape(p.get("desc", "")),
                ))
        return "\n".join(rows)

    md = f"# {node['display_name']}\n\n"
    md += f"**Category:** {node['category']}\n\n"
    if node.get("language"):
        md += f"**Language:** {node['language']}\n\n"
    md += f"**Source:** `{node['file']}`\n\n"

    if h.get("summary"):
        md += f"## Summary\n{h['summary']}\n\n"

    md += "## Inputs\n" + table_io(inputs) + "\n\n"
    md += "## Outputs\n" + table_io(outputs) + "\n\n"
    md += "## Parameters\n" + table_params(params) + "\n\n"

    if h.get("usage"):
        md += f"## Usage\n{h['usage']}\n\n"

    if gotchas:
        md += "## Gotchas\n"
        for g in gotchas:
            if isinstance(g, str):
                md += f"- {g}\n"
        md += "\n"

    return md

def render_catalog_page(nodes_by_cat):
    md = "# Nodes Catalog\n\n"
    md += "> Auto-generated from plugin `help` dicts. Use Shift+F1 on a node to open its page.\n\n"
    for cat, items in sorted(nodes_by_cat.items(), key=lambda kv: kv[0].lower()):
        md += f"## {cat}\n\n"
        if not items:
            md += "_No nodes in this category._\n\n"
            continue
        rows = ["| Node | Summary |", "|---|---|"]
        for n in sorted(items, key=lambda x: x['display_name'].lower()):
            slug = slugify(n["display_name"])
            summary = (n.get("help", {}).get("summary", "") or "").strip()
            rows.append(f"| [{md_escape(n['display_name'])}](./{slug}.md) | {md_escape(summary)} |")
        md += "\n".join(rows) + "\n\n"
    return md

def main():
    project_root = Path(__file__).resolve().parents[1]
    src_dirs = ['plugins', 'custom_plugins']
    out_dir = project_root / 'RBciAD_docs' / 'docs' / 'user' / 'nodes'
    out_dir.mkdir(parents=True, exist_ok=True)

    all_plugins = []
    for d in src_dirs:
        dir_path = project_root / d
        if not dir_path.exists():
            continue
        for pyfile in dir_path.rglob("*.py"):
            if pyfile.name == "__init__.py":
                continue
            plugins = extract_plugins_from_file(pyfile)
            all_plugins.extend(plugins)

    # Group by category
    by_cat = {}
    for p in all_plugins:
        cat = p.get('category', 'Custom')
        by_cat.setdefault(cat, []).append(p)

    # Write per-node pages
    for p in all_plugins:
        slug = slugify(p['display_name'])
        md = render_node_page(p)
        (out_dir / f"{slug}.md").write_text(md, encoding="utf-8")

    # Write catalog
    catalog = render_catalog_page(by_cat)
    (out_dir / "index.md").write_text(catalog, encoding="utf-8")

    # Trampoline
    user_dir = out_dir.parent
    (user_dir / "nodes.md").write_text(
        "# Nodes Catalog\n\n[Open catalog](nodes/index.md)\n", encoding="utf-8"
    )

    print(f"[docgen] Extracted {len(all_plugins)} nodes (AST-based, no imports needed)")
    cats_summary = {k: len(v) for k, v in by_cat.items()}
    for cat, count in sorted(cats_summary.items()):
        print(f"  {cat}: {count}")
    print(f"[docgen] Output: {out_dir}")

if __name__ == "__main__":
    main()
