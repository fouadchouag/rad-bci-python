#!/usr/bin/env python3
"""
Generate Nodes Catalog (user docs) from plugin wrappers.
Scans plugins/ and custom_plugins/ by default.
Writes docs/user/nodes/index.md and per-node pages.

Run:
  python tools/generate_node_catalog.py
"""
from __future__ import annotations
import os, sys, re, json, importlib.util, inspect
from pathlib import Path
from typing import Dict, Any, List

TITLE = os.getenv("DOCS_TITLE", "Nodes Catalog")

def slugify(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_]+', '-', s).strip('-').lower() or "node"

def read_files(dirs: List[Path]) -> List[Path]:
    files: List[Path] = []
    for d in dirs:
        if not d.exists(): continue
        for p in d.rglob("*.py"):
            if p.name == "__init__.py": continue
            files.append(p)
    return files

def load_module_from_path(path: Path):
    name = f"_docmod_{path.stem}_{abs(hash(str(path)))%10**8}"
    spec = importlib.util.spec_from_file_location(name, str(path))
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        os.environ.setdefault("DOCS_BUILD", "1")
        spec.loader.exec_module(mod)  # type: ignore
        return mod
    except Exception as e:
        print(f"[docgen] Skipped {path}: import error: {e}")
        return None

def extract_plugins(mod) -> List[Dict[str,Any]]:
    items = []
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        h = getattr(obj, "help", None)
        disp = getattr(obj, "display_name", None) or getattr(obj, "name", None)
        if isinstance(h, dict) and isinstance(disp, str) and disp.strip():
            items.append({
                "class": f"{mod.__name__}.{name}",
                "display_name": disp.strip(),
                "category": getattr(obj, "category", "Custom"),
                "language": getattr(obj, "language", ""),
                "help": h,
            })
    return items

def md_escape(s: str) -> str:
    return str(s).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")

def render_node_page(node: Dict[str,Any]) -> str:
    h = node.get("help", {}) or {}
    inputs = h.get("inputs", {}) or {}
    outputs = h.get("outputs", {}) or {}
    params = h.get("parameters", []) or []
    gotchas = h.get("gotchas", []) or []
    if isinstance(gotchas, str):
        gotchas = [gotchas]

    def table_io(d: Dict[str,str]) -> str:
        if not d: return "_None_"
        rows = ["| Name | Description |", "|---|---|"]
        for k,v in d.items():
            rows.append(f"| {md_escape(k)} | {md_escape(v)} |")
        return "\n".join(rows)

    def table_params(lst):
        if not lst: return "_None_"
        rows = ["| Name | Type | Default | Unit | Description |", "|---|---|---|---|---|"]
        for p in lst:
            rows.append("| {name} | {type} | {default} | {unit} | {desc} |".format(
                name=md_escape(p.get("name","")),
                type=md_escape(p.get("type","")),
                default=md_escape(p.get("default","")),
                unit=md_escape(p.get("unit","")),
                desc=md_escape(p.get("desc","")),
            ))
        return "\n".join(rows)

    md = f"# {node['display_name']}\n\n"
    if node.get("category"):
        md += f"**Category:** {node['category']}\n\n"
    if node.get("language"):
        md += f"**Language:** {node['language']}\n\n"

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
            md += f"- {g}\n"
        md += "\n"

    return md

def render_catalog_page(nodes_by_cat):
    md = f"# {TITLE}\n\n"
    md += "> Auto-generated from plugin `help` dicts. Use Shift+F1 on a node to open its page.\n\n"
    for cat, items in sorted(nodes_by_cat.items(), key=lambda kv: kv[0].lower()):
        md += f"## {cat}\n\n"
        if not items:
            md += "_No nodes in this category._\n\n"
            continue
        rows = ["| Node | Summary |", "|---|---|"]
        for n in sorted(items, key=lambda x: x['display_name'].lower()):
            slug = slugify(n["display_name"])
            summary = (n.get("help",{}).get("summary","") or "").strip()
            rows.append(f"| [{md_escape(n['display_name'])}](./{slug}.md) | {md_escape(summary)} |")
        md += "\n".join(rows) + "\n\n"
    return md

def main():
    project_root = Path(__file__).resolve().parents[1]
    src_dirs = os.getenv("DOCS_SRC_DIRS", "plugins,custom_plugins").split(",")
    src_paths = [(project_root / d.strip()) for d in src_dirs if d.strip()]
    out_dir = Path(os.getenv("DOCS_OUT_DIR", str(project_root / "docs" / "user" / "nodes")))
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes = []
    for pyfile in read_files(src_paths):
        mod = load_module_from_path(pyfile)
        if not mod: continue
        nodes.extend(extract_plugins(mod))

    # group by category
    by_cat = {}
    for n in nodes:
        by_cat.setdefault(n.get("category") or "Custom", []).append(n)

    # write per-node pages
    for n in nodes:
        slug = slugify(n["display_name"])
        md = render_node_page(n)
        (out_dir / f"{slug}.md").write_text(md, encoding="utf-8")

    # write catalog
    catalog = render_catalog_page(by_cat)
    (out_dir / "index.md").write_text(catalog, encoding="utf-8")

    # trampoline
    user_dir = out_dir.parent
    (user_dir / "nodes.md").write_text(f"# {TITLE}\n\n[Open catalog](nodes/index.md)\n", encoding="utf-8")

    print(f"[docgen] Wrote {len(nodes)} node pages in {out_dir}")
    print(f"[docgen] Catalog: {out_dir/'index.md'}")

if __name__ == "__main__":
    main()
