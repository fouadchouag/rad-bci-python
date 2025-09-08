# Troubleshooting

- *Node not visible in palette*: wrapper import error. Check console; fix missing deps or syntax.
- *Quick Help empty*: `help` dict missing or not a dict literal.
- *Shift+F1 opens catalog instead of node*: display name doesn't match slugged page; re-generate docs.
- *No search bar in docs viewer*: ensure assets are from MkDocs Material; use the in-app helper utilities.
- *Subprocess timeout*: confirm your binary supports `--stdio` or `--in/--out` and returns well-formed JSON.
