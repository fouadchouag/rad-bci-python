RBciAD App Kit — Drop-In Help Integration

1) Copy `rbciad_app/` to your project root (next to core/, gui/, plugins/, docs/, site/).
2) Build docs: `mkdocs build`.
3) Copy `site/` to `rbciad_app/docs_site/`.
4) Add a pyproject.toml at root with:
   [project.scripts]
   rbciad = "rbciad_app.__main__:main"
   [tool.setuptools.package-data]
   rbciad_app = ["docs_site/**/*"]
5) pip install -e .
6) Run: `rbciad`

F1 = Help (User/Developer) • Shift+F1 = Context Help (selected node) • Ctrl+F1 = Quick Help dialog.
