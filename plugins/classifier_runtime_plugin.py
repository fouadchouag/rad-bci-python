# plugins/classifier_runtime_plugin.py
# -*- coding: utf-8 -*-
import numpy as np
from rx.subject import BehaviorSubject
from core.node_base import BasePlugin

class ClassifierRuntimePlugin(BasePlugin):
    help = help = { 'gotchas': ['Model-version mismatch can reduce accuracy.'],
  'inputs': {'features': 'array/dict', 'model': 'trained model'},
  'outputs': {'pred': 'labels', 'proba': 'optional probabilities'},
  'parameters': [ { 'default': 0.5,
                    'desc': 'Decision threshold (if applicable)',
                    'name': 'threshold',
                    'type': 'float'}],
  'summary': 'Apply a trained model or compute predictions/probabilities.',
  'usage': 'Connect features and a compatible model.'}

    name = "ClassifierRuntime"
    language = "Python"
    category = "ML / Classifier"

    def setup(self):
        self.inputs["model"] = BehaviorSubject(None)     # sklearn classifier (fit)
        self.inputs["features"] = BehaviorSubject(None)  # (n_feat,)
        self.outputs["pred_label"] = BehaviorSubject(None)
        self.outputs["pred_idx"] = BehaviorSubject(None)
        self.outputs["proba"] = BehaviorSubject(None)    # dict label->p (si dispo)

    def execute(self, inputs):
        clf = inputs.get("model"); feats = inputs.get("features")
        if clf is None or feats is None: return
        x = np.asarray(feats).reshape(1, -1)
        try:
            y_idx = int(clf.predict(x)[0])
        except Exception as e:
            print("[ClassifierRuntime] predict error:", e); return
        labels = getattr(clf, "classes_", None)
        y_lbl = labels[y_idx] if labels is not None and y_idx < len(labels) else y_idx
        self.outputs["pred_idx"].on_next(y_idx)
        self.outputs["pred_label"].on_next(y_lbl)

        # proba si dispo
        proba = None
        try:
            p = clf.predict_proba(x)[0]
            if labels is not None:
                proba = {str(lbl): float(p[i]) for i, lbl in enumerate(labels)}
            else:
                proba = {str(i): float(p[i]) for i in range(len(p))}
        except Exception:
            pass
        self.outputs["proba"].on_next(proba)