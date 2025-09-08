# Release & Packaging (overview)

- **Source zip**: include `requirements.txt` (or `environment.yml`) and a `README.md` with install/run instructions.
- **Editable dev install**:
  ```bash
  pip install -e .
  rbciad
  ```
- **End-user (no dev tools)**: ship a frozen app (PyInstaller) or provide a one-liner launcher script.
- **Docs**: publish MkDocs site or bundle `site/` and use the in-app viewer (F1).
