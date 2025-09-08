
# rbciad_app/help_autofill.py
from __future__ import annotations
import re, ast, pprint
from typing import Any, Dict, List

# ---------- Spec Normalization ----------

def _norm_name(x):
    return str(x).strip()

def _as_dict_io(v) -> Dict[str,str]:
    # Accepts: dict{name:desc} OR list of names OR list of dicts
    if v is None:
        return {}
    if isinstance(v, dict):
        return { _norm_name(k): str(v) if isinstance(v, (int,float)) else str(v) for k,v in v.items() }
    out = {}
    if isinstance(v, (list,tuple)):
        for it in v:
            if isinstance(it, str):
                out[_norm_name(it)] = ""
            elif isinstance(it, dict):
                # single {name:desc} or param-like dict with name/desc
                if len(it)==1:
                    k, val = list(it.items())[0]
                    out[_norm_name(k)] = str(val)
                else:
                    name = it.get("name") or it.get("id") or it.get("key")
                    desc = it.get("desc") or it.get("description") or ""
                    if name: out[_norm_name(name)] = str(desc)
    return out

def _as_params(lst) -> List[Dict[str,Any]]:
    out = []
    if not lst: return out
    for it in lst:
        if isinstance(it, dict):
            name = it.get("name") or it.get("id")
            typ  = it.get("type") or it.get("dtype") or ""
            default = it.get("default", "")
            unit = it.get("unit","")
            desc = it.get("desc") or it.get("description") or ""
            out.append({"name":name, "type":typ, "default":default, "unit":unit, "desc":desc})
        elif isinstance(it, str):
            out.append({"name": it, "type":"", "default":"", "unit":"", "desc":""})
    return out

def normalize_spec(spec: Dict[str,Any]) -> Dict[str,Any]:
    """Normalize multiple possible schemas from lowcode_creator into a standard shape."""
    s = spec or {}
    display_name = s.get("display_name") or s.get("name") or s.get("title") or "New Node"
    category = s.get("category") or s.get("group") or "Processing"
    inputs = _as_dict_io(s.get("inputs") or s.get("in") or s.get("ports_in") or [])
    outputs = _as_dict_io(s.get("outputs") or s.get("out") or s.get("ports_out") or [])
    params = _as_params(s.get("parameters") or s.get("params") or s.get("arguments") or [])
    return {
        "display_name": display_name,
        "category": category,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": params,
    }

# ---------- Help Builder ----------

def build_help_from_spec(spec: Dict[str,Any], summary: str, usage: str, gotchas: List[str]|None=None) -> Dict[str,Any]:
    ns = normalize_spec(spec)
    helpd = {
        "summary": summary.strip(),
        "inputs": ns["inputs"],
        "outputs": ns["outputs"],
        "parameters": ns["parameters"],
        "usage": usage.strip(),
        "gotchas": gotchas or [],
    }
    return helpd

# ---------- Injection into wrapper ----------

def _find_primary_class(lines: list[str]):
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\([^)]*\))?\s*:\s*$', line)
        if m:
            indent = m.group(1)
            cname = m.group(2)
            if cname.lower().endswith(("plugin","node")) or "Plugin" in cname or "Node" in cname:
                return i, indent
    # fallback to first class
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)class\s+([A-Za-z_][A-Za-z0-9_]*)\s*', line)
        if m:
            return i, m.group(1)
    return None, ""

def _class_has_help(lines: list[str], class_idx: int, indent: str) -> bool:
    base = len(indent)
    for j in range(class_idx+1, len(lines)):
        ln = lines[j]
        if re.match(r'^\s*class\s+', ln) and (len(ln)-len(ln.lstrip(' '))) <= base:
            break
        if re.match(r'^\s{'+str(base+1)+r',}help\s*=', ln):
            return True
    return False

def inject_help_into_source(src: str, helpd: Dict[str,Any]) -> str:
    lines = src.splitlines()
    class_idx, indent = _find_primary_class(lines)
    block = "help = " + pprint.pformat(helpd, width=88, compact=False, indent=2) + "\n"
    if class_idx is None:
        # module-level insertion after module docstring if any
        m = re.match(r'^(\"\"\".*?\"\"\"|\'\'\'.*?\'\'\')', src, re.DOTALL)
        insert = len(m.group(0)) if m else 0
        return src[:insert] + ("\n" if insert else "") + block + src[insert:]
    # inside class: insert or replace existing
    base = len(indent)
    s = "\n".join(lines)
    if _class_has_help(lines, class_idx, indent):
        # replace existing help dict
        # naive brace matching from 'help' token
        start_search = sum(len(l)+1 for l in lines[:class_idx+1])
        pos = s.find("help", start_search)
        while pos != -1:
            # ensure at class indentation or deeper
            # find line start
            ls = s.rfind("\n", 0, pos) + 1
            col = pos - ls
            if col >= base:
                # find dict
                brace = s.find("{", pos)
                if brace == -1: break
                depth = 0; k = brace
                while k < len(s):
                    if s[k] == "{": depth += 1
                    elif s[k] == "}":
                        depth -= 1
                        if depth == 0: k += 1; break
                    k += 1
                return s[:ls] + indent + "    " + block + s[k:]
            pos = s.find("help", pos+1)
    # insert after header
    insert_idx = sum(len(l)+1 for l in lines[:class_idx+1])
    return s[:insert_idx] + indent + "    " + block + s[insert_idx:]
