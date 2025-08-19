# workflow_templates.py
# -*- coding: utf-8 -*-
"""
Modèles de workflows RBciAD.
- Chaque template déclare des noeuds {id, class_names, pos(x,y)} et des connexions [src_id, src_pin, dst_id, dst_pin].
- class_names peut être str OU list[str] (on prend le 1er plugin dispo).
- instantiate_template(main_window, key) crée les noeuds et tente les connexions par NOM de pin.
"""

from PyQt5.QtCore import QPointF

TEMPLATES = {
    "bandpower_basic": {
        "title": "Pipeline simple (Bandpower)",
        "nodes": [
            {"id": "R",  "class_names": ["EEGReaderPlugin", "EEGReader"], "pos": (0, 0)},
            {"id": "S",  "class_names": ["SegmenterPlugin", "EEGSegmenter", "WindowPlugin", "Segmenter"], "pos": (220, 0)},
            {"id": "BP", "class_names": ["BandpowerFeaturesPlugin", "BandpowerFeatures"], "pos": (440, 0)},
            {"id": "CT", "class_names": ["ClassifierTrainerPlugin", "ClassifierTrainer"], "pos": (660, 0)},
            {"id": "CR", "class_names": ["ClassifierRuntimePlugin", "ClassifierRuntime"], "pos": (660, 140)},
            {"id": "V",  "class_names": ["EEGLiveDisplayPlugin","EEGVisualizerPlugin","EEGLiveDisplay","EEGVisualizer"], "pos": (220, 140)},
        ],
        "connections": [
            ["R", "raw",      "S", "raw"],
            ["R", "sfreq",    "S", "sfreq"],
            ["R", "ch_names", "S", "ch_names"],

            ["S", "segment",  "BP", "segment"],
            ["S", "sfreq",    "BP", "sfreq"],

            ["BP", "features","CT", "features"],
            ["S",  "label",   "CT", "label"],

            ["BP", "features","CR", "features"],
            ["CT", "model",   "CR", "model"],

            ["R", "raw",      "V",  "raw"],
            ["R", "sfreq",    "V",  "sfreq"],
            ["R", "ch_names", "V",  "ch_names"],
        ],
    },

    "csp_pipeline": {
        "title": "Pipeline CSP (features séparées)",
        "nodes": [
            {"id": "R",   "class_names": ["EEGReaderPlugin","EEGReader"], "pos": (0, 0)},
            {"id": "S",   "class_names": ["SegmenterPlugin","EEGSegmenter","WindowPlugin","Segmenter"], "pos": (220, 0)},
            {"id": "FLT", "class_names": ["EEGFilterPlugin","FilterPlugin","EEGFilter"], "pos": (440, -80)},  # optionnel
            {"id": "CSPT","class_names": ["CSPTrainerPlugin","CSPTrainer"], "pos": (440, 0)},
            {"id": "CSPA","class_names": ["CSPApplyPlugin","CSPApply"], "pos": (660, 0)},
            {"id": "CT",  "class_names": ["ClassifierTrainerPlugin","ClassifierTrainer"], "pos": (880, 0)},
            {"id": "CR",  "class_names": ["ClassifierRuntimePlugin","ClassifierRuntime"], "pos": (880, 140)},
        ],
        "connections": [
            ["R", "raw",      "S", "raw"],
            ["R", "sfreq",    "S", "sfreq"],
            ["R", "ch_names", "S", "ch_names"],

            # Préproc optionnelle
            ["S", "segment",  "FLT", "segment"],
            ["S", "sfreq",    "FLT", "sfreq"],

            # Entraînement CSP
            ["S", "segment",  "CSPT", "segment"],
            ["S", "label",    "CSPT", "label"],

            # Application CSP
            ["S", "segment",  "CSPA", "segment"],
            ["CSPT", "feature_transform", "CSPA", "feature_transform"],

            # Entraînement classifieur
            ["CSPA", "features", "CT", "features"],
            ["S",    "label",    "CT", "label"],

            # Runtime
            ["CSPA", "features", "CR", "features"],
            ["CT",   "model",    "CR", "model"],
        ],
    },

    "riemann_pipeline": {
        "title": "Pipeline Riemann (covariance → Tangent Space)",
        "nodes": [
            {"id": "R",   "class_names": ["EEGReaderPlugin","EEGReader"], "pos": (0, 0)},
            {"id": "S",   "class_names": ["SegmenterPlugin","EEGSegmenter","WindowPlugin","Segmenter"], "pos": (220, 0)},
            {"id": "RCV", "class_names": ["RiemannCovPlugin","RiemannCov"], "pos": (440, 0)},
            {"id": "RST", "class_names": ["RiemannTSTrainerPlugin","RiemannTSTrainer"], "pos": (660, 0)},
            {"id": "RSA", "class_names": ["RiemannTSApplyPlugin","RiemannTSApply"], "pos": (880, 0)},
            {"id": "CT",  "class_names": ["ClassifierTrainerPlugin","ClassifierTrainer"], "pos": (1100, 0)},
            {"id": "CR",  "class_names": ["ClassifierRuntimePlugin","ClassifierRuntime"], "pos": (1100, 140)},
        ],
        "connections": [
            ["R", "raw",      "S", "raw"],
            ["R", "sfreq",    "S", "sfreq"],
            ["R", "ch_names", "S", "ch_names"],

            ["S", "segment",  "RCV", "segment"],

            # Entraînement TS
            ["RCV", "cov",    "RST", "cov"],
            ["S",   "label",  "RST", "label"],

            # Application TS
            ["RCV", "cov",          "RSA", "cov"],
            ["RST", "ts_transform", "RSA", "ts_transform"],

            # Entraînement classifieur
            ["RSA", "features", "CT", "features"],
            ["S",   "label",    "CT", "label"],

            # Runtime
            ["RSA", "features", "CR", "features"],
            ["CT",  "model",    "CR", "model"],
        ],
    },
}


def instantiate_template(main_window, template_key: str):
    """Instancie les nœuds + connexions d’un template dans la scène de main_window."""
    if template_key not in TEMPLATES:
        raise ValueError(f"Template inconnu: {template_key}")

    tpl = TEMPLATES[template_key]
    created = {}  # id -> NodeItem

    def _resolve_class(class_names):
        names = class_names if isinstance(class_names, (list, tuple)) else [class_names]
        reg = getattr(main_window, "plugin_classes_by_name", {}) or {}
        # 1) direct match
        for name in names:
            cls = reg.get(name)
            if cls is not None:
                return cls
        # 2) case-insensitive
        lowmap = {k.lower(): v for k, v in reg.items()}
        for name in names:
            cls = lowmap.get(str(name).lower())
            if cls is not None:
                return cls
        return None

    # Créer les nœuds
    for nd in tpl["nodes"]:
        cls = _resolve_class(nd["class_names"])
        if cls is None:
            print(f"[Templates] ⚠️ Plugin introuvable pour {nd['id']} ({nd['class_names']}) — ignoré.")
            continue
        x, y = nd["pos"]
        node_item = main_window.add_node_at(cls, QPointF(x, y))
        if node_item:
            created[nd["id"]] = node_item

    # Créer les connexions par nom de pin
    for src_id, src_pin, dst_id, dst_pin in tpl["connections"]:
        src_node = created.get(src_id)
        dst_node = created.get(dst_id)
        if not src_node or not dst_node:
            continue
        ok = main_window.connect_by_name(src_node, src_pin, dst_node, dst_pin)
        if not ok:
            print(f"[Templates] ⚠️ Connexion ignorée: {src_id}.{src_pin} → {dst_id}.{dst_pin}")

    return created, tpl.get("title", template_key)
